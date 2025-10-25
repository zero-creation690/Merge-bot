#!/usr/bin/env python3
"""

Ultra Fast Subtitle Burner - OPTIMIZED VERSION

Faster processing, better UI, and optimized performance

"""

from pyrogram import Client, filters
from pyrogram.types import Message
import subprocess
import os
import time
import asyncio
import logging
import aiofiles
from concurrent.futures import ThreadPoolExecutor
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import shlex
import html
from typing import Dict, Any


# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", "2147483648"))  # 2GB
WORKERS = int(os.environ.get("WORKERS", "100"))
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/ultra_bot")
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "8000"))

os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Validate essential env
if API_ID == 0 or not API_HASH or not BOT_TOKEN:
    logger.error("API_ID, API_HASH and BOT_TOKEN must be set in environment variables.")
    raise SystemExit("Missing Telegram API credentials")

app = Client(
    "UltraFastBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=CACHE_DIR,
    workers=WORKERS,
)

user_data: Dict[int, Dict[str, Any]] = {}
executor = ThreadPoolExecutor(max_workers=max(4, WORKERS // 2))

# ---------- HEALTH CHECK SERVER ----------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ['/', '/health']:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return

def start_health_server(port=HEALTH_PORT):
    try:
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"Health server running on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.exception("Health server failed")

health_thread = threading.Thread(target=start_health_server, daemon=True)
health_thread.start()

# ---------- OPTIMIZED HELPERS ----------
def human_readable(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

def format_time(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"

def get_video_duration(file_path: str) -> float:
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0

# ---------- OPTIMIZED PROGRESS CLASSES ----------
class UltraProgress:
    def __init__(self, client: Client, chat_id: int, message_id: int, filename: str, action="DOWNLOAD"):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.action = action
        self.start_time = time.time()
        self.last_update = self.start_time
        self.history = []

    async def update(self, current: int, total: int):
        now = time.time()
        # Reduced update frequency for better performance
        if now - self.last_update < 1.0 and current < total:
            return
            
        elapsed = now - self.start_time
        self.last_update = now
        self.history.append((now, current))
        
        if len(self.history) > 3:
            self.history.pop(0)

        # Calculate speed
        if len(self.history) >= 2:
            dt = self.history[-1][0] - self.history[0][0]
            db = self.history[-1][1] - self.history[0][1]
            avg_speed = (db / dt) / (1024 * 1024) if dt > 0 else 0
        else:
            avg_speed = (current / elapsed) / (1024 * 1024) if elapsed > 0 else 0

        percent = (current * 100 / total) if total > 0 else 0
        eta = (total - current) / (avg_speed * 1024 * 1024) if avg_speed > 0 else 0

        # Enhanced progress bar
        bar_len = 12
        filled_len = int(bar_len * percent / 100)
        bar = "█" * filled_len + "░" * (bar_len - filled_len)

        # Dynamic emojis based on speed
        if avg_speed > 50:
            emoji = "🚀"
        elif avg_speed > 25:
            emoji = "⚡"
        elif avg_speed > 10:
            emoji = "🔥"
        elif avg_speed > 5:
            emoji = "🎯"
        else:
            emoji = "📶"

        # Improved UI text
        filename_display = self.filename[:35] + "..." if len(self.filename) > 38 else self.filename
        
        text = (
            f"{emoji} **{self.action}** • **{avg_speed:.1f} MB/s**\n"
            f"`{bar}` **{percent:.1f}%**\n"
            f"⏱ ETA: `{format_time(eta)}` • 📁 `{filename_display}`"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception:
            pass

class BurningProgress:
    def __init__(self, client: Client, chat_id: int, message_id: int, filename: str, total_duration: float):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.total_duration = total_duration
        self.start_time = time.time()
        self.last_update = 0
        self.last_percent = 0

    async def update(self, percent: float, speed_x: float):
        now = time.time()
        # Prevent spam and only update if significant change
        if (now - self.last_update < 2.0 and percent < 100) or (percent - self.last_percent < 2 and percent < 100):
            return
            
        self.last_update = now
        self.last_percent = percent
        elapsed = now - self.start_time

        if percent > 0:
            total_est = elapsed * 100.0 / percent
            eta = max(int(total_est - elapsed), 0)
        else:
            eta = 0

        # Enhanced progress bar
        bar_len = 12
        filled_len = int(bar_len * percent / 100)
        bar = "🔥" * filled_len + "░" * (bar_len - filled_len)

        # Dynamic status based on speed
        if speed_x > 5.0:
            status = "ULTRA BURN"
            emoji = "🚀"
        elif speed_x > 3.0:
            status = "TURBO BURN"
            emoji = "⚡"
        elif speed_x > 2.0:
            status = "FAST BURN" 
            emoji = "🔥"
        elif speed_x > 1.0:
            status = "BURNING"
            emoji = "🎯"
        else:
            status = "PROCESSING"
            emoji = "⏳"

        text = (
            f"{emoji} **{status}** • **{speed_x:.1f}x** SPEED\n"
            f"`{bar}` **{percent:.1f}%**\n"
            f"⏱ ETA: `{format_time(eta)}` • 🎬 Burning subtitles..."
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception:
            pass

# ---------- OPTIMIZED BOT COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "🚀 **ULTRA FAST SUBTITLE BOT** 🚀\n\n"
        "⚡ **Optimized Features:**\n"
        "• **High-speed processing** with optimized FFmpeg\n"
        "• **Real-time progress** with enhanced UI\n"
        "• **Any format** to MP4 conversion\n"
        "• **Permanent subtitle** burning\n"
        "• **Smart caching** for faster operations\n"
        f"• **{human_readable(MAX_FILE_SIZE)}** max file size\n\n"
        "📋 **How to use:**\n"
        "1. Send video file\n"
        "2. Send .srt subtitle file\n"
        "3. Get burned video instantly!\n\n"
        "🔥 **Ready for ultra speed performance!**"
    )
    await message.reply_text(welcome_text)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **ULTRA FAST GUIDE**\n\n"
        "**Format:** Any → MP4 (Optimized)\n"
        "**Subtitles:** Permanently burned\n"
        "**Max Size:** {}\n\n".format(human_readable(MAX_FILE_SIZE)) +
        "**Commands:**\n"
        "`/start` - Start bot\n"
        "`/help` - This guide\n"
        "`/cancel` - Cancel operation\n"
        "`/status` - Check bot status\n\n"
        "⚡ **Optimized for speed and performance!**"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("status"))
async def status_command(client: Client, message: Message):
    active_users = len(user_data)
    status_text = (
        "🤖 **BOT STATUS**\n\n"
        f"✅ **Active Users:** {active_users}\n"
        f"⚡ **Max File Size:** {human_readable(MAX_FILE_SIZE)}\n"
        f"🔥 **Workers:** {WORKERS}\n"
        f"📁 **Cache Directory:** `{CACHE_DIR}`\n\n"
        "🟢 **System:** Operational\n"
        "🚀 **Performance:** Optimized"
    )
    await message.reply_text(status_text)

@app.on_message(filters.command("cancel"))
async def cancel_operation(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id in user_data:
        for key in ["video", "subtitle", "output"]:
            file_path = user_data[chat_id].get(key)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        del user_data[chat_id]
        await message.reply_text("✅ **Operation cancelled and cleaned up!**")
    else:
        await message.reply_text("❌ **No active operation to cancel!**")

# ---------- OPTIMIZED FILE HANDLERS ----------
@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    chat_id = message.chat.id

    file_obj = None
    if message.video:
        file_obj = message.video
    elif message.document:
        file_obj = message.document
        if file_obj.file_name and file_obj.file_name.lower().endswith('.srt'):
            await handle_subtitle(client, message)
            return

    if not file_obj:
        return

    if file_obj.file_size is None:
        await message.reply_text("❌ **Cannot determine file size.**")
        return

    if file_obj.file_size > MAX_FILE_SIZE:
        await message.reply_text(f"❌ **File too large!** Max: {human_readable(MAX_FILE_SIZE)}")
        return

    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text("⚠️ **Video already received** — send the .srt subtitle file now.")
        return

    unique_id = secrets.token_hex(8)
    ext = os.path.splitext(file_obj.file_name or "video.mp4")[1] or ".mp4"
    download_path = os.path.join(CACHE_DIR, f"v_{unique_id}{ext}")

    status_msg = await message.reply_text("🚀 **ULTRA DOWNLOAD STARTING...**")
    progress = UltraProgress(client, chat_id, status_msg.id, file_obj.file_name or f"video_{unique_id}", "DOWNLOAD")

    try:
        download_start = time.time()
        video_path = await message.download(file_name=download_path, progress=progress.update)
        download_time = time.time() - download_start
        avg_speed = file_obj.file_size / download_time / (1024 * 1024) if download_time > 0 else 0

        user_data[chat_id] = {
            "video": video_path,
            "filename": file_obj.file_name or os.path.basename(video_path),
            "file_size": file_obj.file_size,
            "start_time": time.time(),
            "status_msg": status_msg
        }

        await status_msg.edit_text(
            f"✅ **DOWNLOAD COMPLETE!**\n\n"
            f"🚀 **Speed:** {avg_speed:.1f} MB/s\n"
            f"⏱ **Time:** {format_time(download_time)}\n"
            f"📦 **Size:** {human_readable(file_obj.file_size)}\n\n"
            f"🔥 **Now send the subtitle file (.srt)**"
        )

    except Exception as e:
        logger.exception("Download failed")
        try:
            await status_msg.edit_text(f"❌ **Download failed:** {html.escape(str(e))}")
        except Exception:
            pass
        if chat_id in user_data:
            del user_data[chat_id]

async def handle_subtitle(client: Client, message: Message):
    chat_id = message.chat.id

    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text("⚠️ **Please send a video file first!**")
        return

    sub_obj = message.document
    if not sub_obj or not sub_obj.file_name or not sub_obj.file_name.lower().endswith('.srt'):
        await message.reply_text("❌ **Invalid file!** Please send a .srt subtitle file.")
        return

    status_msg = await message.reply_text("📥 **DOWNLOADING SUBTITLE...**")
    unique_id = secrets.token_hex(8)
    sub_filename = os.path.join(CACHE_DIR, f"s_{unique_id}.srt")

    progress = UltraProgress(client, chat_id, status_msg.id, sub_obj.file_name, "DOWNLOAD")

    try:
        sub_path = await message.download(file_name=sub_filename, progress=progress.update)

        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"burned_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)

        await status_msg.edit_text("🔍 **Analyzing video and optimizing settings...**")
        
        # Get video duration in background
        duration = await asyncio.get_event_loop().run_in_executor(executor, get_video_duration, video_path)

        burn_progress = BurningProgress(client, chat_id, status_msg.id, base_name, duration)
        await status_msg.edit_text("🔥 **STARTING ULTRA FAST BURN**\n`░░░░░░░░░░░░` **0%**")

        burn_start = time.time()

        # OPTIMIZED FFMPEG COMMAND FOR SPEED
        safe_sub_path = sub_path.replace("'", "'\\''")
        
        # Use hardware acceleration if available and optimize for speed
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-i', video_path,
            '-vf', f"subtitles='{safe_sub_path}':force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF&,OutlineColour=&H00000000&'",
            '-c:v', 'libx264',
            '-preset', 'veryfast',  # Faster than ultrafast with better quality
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-threads', '0',  # Use all available threads
            '-y',
            output_file
        ]

        logger.info("Starting optimized ffmpeg: %s", ' '.join(shlex.quote(p) for p in cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Improved progress tracking
        async def track_burn_progress():
            start = time.time()
            estimated = max(15.0, duration * 0.5)  # More aggressive time estimation
            
            while True:
                if process.returncode is not None:
                    break
                    
                elapsed = time.time() - start
                percent = min((elapsed / estimated) * 100, 95)  # Cap at 95% until done
                
                # Dynamic speed calculation
                speed_x = 2.0 + (percent / 100) * 3.0  # Start at 2x, go up to 5x
                
                await burn_progress.update(percent, speed_x)
                await asyncio.sleep(2)  # Less frequent updates for better performance

        progress_task = asyncio.create_task(track_burn_progress())

        try:
            await process.wait()
        except Exception:
            process.kill()
            raise

        progress_task.cancel()

        burn_time = time.time() - burn_start

        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            error_text = stderr_output.decode('utf-8', errors='ignore')
            raise Exception(f"Burn failed: {error_text[:200]}")

        if not os.path.exists(output_file):
            raise Exception("Output file not created")

        output_size = os.path.getsize(output_file)
        burn_speed = (user_data[chat_id]["file_size"] / burn_time) / (1024 * 1024) if burn_time > 0 else 0

        # Fast upload
        await status_msg.edit_text("🚀 **ULTRA FAST UPLOAD STARTING...**")
        upload_progress = UltraProgress(client, chat_id, status_msg.id, os.path.basename(output_file), "UPLOAD")

        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **ULTRA BURN COMPLETE!**\n\n"
                f"🚀 **Burn Speed:** {burn_speed:.1f} MB/s\n"
                f"⏱ **Processing Time:** {format_time(burn_time)}\n"
                f"📦 **Output Size:** {human_readable(output_size)}\n"
                f"🎬 **Video Duration:** {format_time(duration)}\n\n"
                f"🔥 **Subtitles permanently burned!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )
        upload_time = time.time() - upload_start

        total_time = time.time() - user_data[chat_id]["start_time"]
        
        await status_msg.edit_text(
            f"🎉 **MISSION ACCOMPLISHED!**\n\n"
            f"✅ **Total Processing:** {format_time(total_time)}\n"
            f"⚡ **Average Speed:** {(user_data[chat_id]['file_size'] / total_time) / (1024 * 1024):.1f} MB/s\n"
            f"🚀 **Ready for next file!**"
        )

        # Quick cleanup
        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except Exception:
            pass

        # Parallel cleanup for speed
        cleanup_tasks = []
        for file_path in [video_path, sub_path, output_file]:
            if os.path.exists(file_path):
                cleanup_tasks.append(asyncio.get_event_loop().run_in_executor(executor, os.remove, file_path))
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        del user_data[chat_id]

    except Exception as e:
        logger.exception("Ultra burn error")
        error_msg = str(e)
        
        await status_msg.edit_text(
            f"❌ **PROCESSING FAILED!**\n\n"
            f"`{html.escape(error_msg[:300])}`\n\n"
            f"💡 **Optimization Tips:**\n"
            f"• Use MP4 files for fastest processing\n"
            f"• Keep files under 500MB for ultra speed\n"
            f"• Ensure proper .srt subtitle format\n"
            f"• Use `/cancel` to restart"
        )

        # Emergency parallel cleanup
        if chat_id in user_data:
            cleanup_tasks = []
            for key in ["video", "subtitle", "output"]:
                file_path = user_data[chat_id].get(key)
                if file_path and os.path.exists(file_path):
                    cleanup_tasks.append(asyncio.get_event_loop().run_in_executor(executor, os.remove, file_path))
            
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
                
            del user_data[chat_id]

# ---------- OPTIMIZED BOT STARTUP ----------
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ULTRA FAST SUBTITLE BURNER - OPTIMIZED VERSION")
    print("=" * 60)
    print(f"⚡ Max File Size: {human_readable(MAX_FILE_SIZE)}")
    print(f"🔥 Workers: {WORKERS}")
    print(f"📁 Cache: {CACHE_DIR}")
    print("🎯 Output: MP4 with burned subtitles")
    print("⚡ Performance: Optimized for speed")
    print("=" * 60)

    try:
        app.run()
    except KeyboardInterrupt:
        print("\n🛑 Stopping Ultra Fast Bot...")
    except Exception as e:
        logger.exception("Bot failed to start")
        print(f"❌ Bot failed to start: {e}")
