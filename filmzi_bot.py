#!/usr/bin/env python3
"""
Ultra Fast Subtitle Burner - Production-Ready Single-File Bot
Enhanced version with better progress tracking, ASS support, and improved reliability
"""

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
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
import json
from pathlib import Path
import re

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", "2147483648"))  # 2GB
WORKERS = int(os.environ.get("WORKERS", "100"))
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/ultra_bot")
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "8000"))
SESSION_STRING = os.environ.get("SESSION_STRING", "")

os.makedirs(CACHE_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
    in_memory=True,  # Avoid session file issues
    parse_mode=ParseMode.MARKDOWN
)

user_data = {}
executor = ThreadPoolExecutor(max_workers=max(2, WORKERS // 2))

# ---------- HEALTH CHECK SERVER ----------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ['/', '/health']:
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                "status": "healthy",
                "timestamp": time.time(),
                "service": "ultra-subtitle-bot",
                "active_sessions": len(user_data)
            }
            self.wfile.write(json.dumps(response).encode())
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

# ---------- HELPERS ----------
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"Could not get video duration: {e}")
    return 0.0

def get_video_resolution(file_path: str) -> tuple:
    """Get video width and height"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            dimensions = result.stdout.strip().split(',')
            if len(dimensions) == 2:
                return int(dimensions[0]), int(dimensions[1])
    except Exception as e:
        logger.warning(f"Could not get video resolution: {e}")
    return (1920, 1080)  # Default fallback

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe use"""
    return re.sub(r'[^\w\-_. ]', '', filename)

# ---------- PROGRESS CLASSES ----------
class UltraProgress:
    def __init__(self, client: Client, chat_id: int, message_id: int, filename: str, action="DOWNLOAD"):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.action = action
        self.start_time = time.time()
        self.last_update = self.start_time
        self.history = []  # [(timestamp, bytes)]

    async def update(self, current: int, total: int):
        now = time.time()
        # Do not spam updates
        if now - self.last_update < 0.5 and current < total:
            return
        elapsed = now - self.start_time
        self.last_update = now
        self.history.append((now, current))
        # keep last 5
        if len(self.history) > 5:
            self.history.pop(0)

        # calculate average speed in MB/s using history
        if len(self.history) >= 2:
            dt = self.history[-1][0] - self.history[0][0]
            db = self.history[-1][1] - self.history[0][1]
            avg_speed = (db / dt) / (1024 * 1024) if dt > 0 else 0
        else:
            avg_speed = (current / elapsed) / (1024 * 1024) if elapsed > 0 else 0

        percent = (current * 100 / total) if total > 0 else 0
        eta = (total - current) / (avg_speed * 1024 * 1024) if avg_speed > 0 else 0

        # compact progress bar
        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        bar = "█" * filled_len + "░" * (bar_len - filled_len)

        # emoji
        if avg_speed > 20:
            emoji = "🚀"
        elif avg_speed > 10:
            emoji = "⚡"
        elif avg_speed > 5:
            emoji = "🔥"
        else:
            emoji = "📶"

        text = (
            f"{emoji} **{self.action}** • **{avg_speed:.1f} MB/s**\n"
            f"`{bar}` **{percent:.1f}%** • ETA: `{format_time(eta)}`\n"
            f"`{self.filename[:40]}`"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception as e:
            logger.debug(f"Progress update failed: {e}")

class BurningProgress:
    def __init__(self, client: Client, chat_id: int, message_id: int, filename: str, total_duration: float):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.total_duration = total_duration
        self.start_time = time.time()
        self.last_update = 0

    async def update(self, percent: float, speed_x: float):
        now = time.time()
        if now - self.last_update < 1 and percent < 100:
            return
        self.last_update = now
        elapsed = now - self.start_time

        if percent > 0:
            total_est = elapsed * 100.0 / percent
            eta = max(int(total_est - elapsed), 0)
        else:
            eta = 0

        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        bar = "🔥" * filled_len + "░" * (bar_len - filled_len)

        if speed_x > 3.0:
            status = "ULTRA BURN"
        elif speed_x > 2.0:
            status = "TURBO BURN"
        elif speed_x > 1.0:
            status = "FAST BURN"
        else:
            status = "BURNING"

        text = (
            f"⚙️ **{status}** • **{speed_x:.1f}x**\n"
            f"`{bar}` **{percent:.1f}%** • ETA: `{format_time(eta)}`\n"
            f"**Burning subtitles into video...**"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception as e:
            logger.debug(f"Burn progress update failed: {e}")

# ---------- BOT COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "🚀 **ULTRA FAST SUBTITLE BOT** 🚀\n\n"
        "⚡ **Features:**\n"
        "• **High download speed** (depends on host)\n"
        "• **Real-time burning** progress\n"
        "• **Any format** to MP4\n"
        "• **Permanent** subtitle burning\n"
        "• **2GB** max file size (configurable)\n"
        "• **SRT & ASS** subtitle support\n\n"
        "📋 **How to use:**\n"
        "1. Send video file\n"
        "2. Send subtitle file (.srt or .ass)\n"
        "3. Receive video with burned subtitles!\n\n"
        "🔥 **Ready for ultra speed!**"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Help", callback_data="help"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **ULTRA FAST GUIDE**\n\n"
        "**Format:** Any → MP4\n"
        "**Subtitles:** SRT, ASS\n"
        "**Max Size:** {}\n\n".format(human_readable(MAX_FILE_SIZE)) +
        "**Commands:**\n"
        "`/start` - Start bot\n"
        "`/help` - This guide\n"
        "`/cancel` - Cancel operation\n"
        "`/status` - Check bot status\n\n"
        "🚀 **Send a video to experience ultra speed!**"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("status"))
async def status_command(client: Client, message: Message):
    status_text = (
        "🤖 **Bot Status**\n\n"
        f"**Active Sessions:** {len(user_data)}\n"
        f"**Max File Size:** {human_readable(MAX_FILE_SIZE)}\n"
        f"**Workers:** {WORKERS}\n"
        f"**Health Port:** {HEALTH_PORT}\n\n"
        "✅ **Bot is running smoothly!**"
    )
    await message.reply_text(status_text)

@app.on_message(filters.command("cancel"))
async def cancel_operation(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id in user_data:
        # Cleanup files
        for key in ["video_path", "subtitle_path", "output_path"]:
            file_path = user_data[chat_id].get(key)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup {file_path}: {e}")
        del user_data[chat_id]
        await message.reply_text("✅ **Cancelled and cleaned up!**")
    else:
        await message.reply_text("❌ **No active operation!**")

@app.on_callback_query()
async def handle_callbacks(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    
    if data == "help":
        await help_command(client, callback_query.message)
    elif data == "cancel":
        await cancel_operation(client, callback_query.message)
    
    await callback_query.answer()

# ---------- FILE HANDLERS ----------
@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    chat_id = message.chat.id

    # Check if user already has an active session
    if chat_id in user_data and user_data[chat_id].get("processing"):
        await message.reply_text("⚠️ **Please wait for current operation to complete!**")
        return

    # document could be srt, ass, or video
    file_obj = None
    if message.video:
        file_obj = message.video
    elif message.document:
        file_obj = message.document
        # If it's a subtitle file and we already have video, call subtitle handler
        if (file_obj.file_name and 
            file_obj.file_name.lower().endswith(('.srt', '.ass')) and
            chat_id in user_data and "video_path" in user_data[chat_id]):
            await handle_subtitle(client, message)
            return

    if not file_obj:
        return

    if file_obj.file_size is None:
        await message.reply_text("❌ **Cannot determine file size.**")
        return

    if file_obj.file_size > MAX_FILE_SIZE:
        await message.reply_text(f"❌ **Too large!** Max: {human_readable(MAX_FILE_SIZE)}")
        return

    # If already have a video for this chat, ask for subtitle
    if chat_id in user_data and "video_path" in user_data[chat_id]:
        await message.reply_text("⚠️ **Video already received** — send the subtitle file (.srt or .ass) now.")
        return

    unique_id = secrets.token_hex(6)
    original_filename = file_obj.file_name or "video.mp4"
    safe_filename = sanitize_filename(original_filename)
    ext = os.path.splitext(safe_filename)[1] or ".mp4"
    download_path = os.path.join(CACHE_DIR, f"v_{unique_id}{ext}")

    status_msg = await message.reply_text("🚀 **ULTRA DOWNLOAD STARTED**")
    progress = UltraProgress(client, chat_id, status_msg.id, safe_filename, "DOWNLOAD")

    try:
        download_start = time.time()
        video_path = await message.download(file_name=download_path, progress=progress.update)
        download_time = time.time() - download_start
        avg_speed = file_obj.file_size / download_time / (1024 * 1024) if download_time > 0 else 0

        # Get video info
        duration = await asyncio.get_event_loop().run_in_executor(executor, get_video_duration, video_path)
        width, height = await asyncio.get_event_loop().run_in_executor(executor, get_video_resolution, video_path)

        user_data[chat_id] = {
            "video_path": video_path,
            "original_filename": safe_filename,
            "file_size": file_obj.file_size,
            "duration": duration,
            "resolution": f"{width}x{height}",
            "start_time": time.time(),
            "processing": False
        }

        await status_msg.edit_text(
            f"✅ **DOWNLOAD COMPLETE!**\n\n"
            f"📊 **Video Info:**\n"
            f"• Duration: `{format_time(duration)}`\n"
            f"• Resolution: `{width}x{height}`\n"
            f"• Size: `{human_readable(file_obj.file_size)}`\n\n"
            f"🚀 **Speed:** {avg_speed:.1f} MB/s\n"
            f"⏱️ **Time:** {format_time(download_time)}\n\n"
            f"🔥 **Send subtitle file (.srt or .ass)**"
        )

    except Exception as e:
        logger.exception("Download failed")
        try:
            await status_msg.edit_text(f"❌ **Download failed:** `{html.escape(str(e))}`")
        except Exception:
            pass
        # Cleanup on failure
        if os.path.exists(download_path):
            try:
                os.remove(download_path)
            except Exception:
                pass
        if chat_id in user_data:
            del user_data[chat_id]

async def handle_subtitle(client: Client, message: Message):
    chat_id = message.chat.id

    if chat_id not in user_data or "video_path" not in user_data[chat_id]:
        await message.reply_text("⚠️ **Send video first!**")
        return

    if user_data[chat_id].get("processing"):
        await message.reply_text("⚠️ **Already processing! Please wait...**")
        return

    sub_obj = message.document
    if not sub_obj or not sub_obj.file_name:
        await message.reply_text("❌ **Invalid file!**")
        return

    sub_ext = sub_obj.file_name.lower()
    if not (sub_ext.endswith('.srt') or sub_ext.endswith('.ass')):
        await message.reply_text("❌ **Invalid subtitle format!** Send .srt or .ass file.")
        return

    status_msg = await message.reply_text("🚀 **DOWNLOADING SUBTITLE**")
    unique_id = secrets.token_hex(6)
    sub_ext = os.path.splitext(sub_obj.file_name)[1].lower()
    sub_filename = os.path.join(CACHE_DIR, f"s_{unique_id}{sub_ext}")

    progress = UltraProgress(client, chat_id, status_msg.id, sub_obj.file_name, "DOWNLOAD")

    try:
        sub_path = await message.download(file_name=sub_filename, progress=progress.update)

        video_path = user_data[chat_id]["video_path"]
        original_filename = user_data[chat_id]["original_filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"{base_name}_burned_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)

        # Mark as processing
        user_data[chat_id]["processing"] = True
        user_data[chat_id]["subtitle_path"] = sub_path
        user_data[chat_id]["output_path"] = output_file

        await status_msg.edit_text("🔍 **Analyzing video...**")
        duration = user_data[chat_id]["duration"]

        burn_progress = BurningProgress(client, chat_id, status_msg.id, base_name, duration)
        await status_msg.edit_text("🔥 **STARTING ULTRA BURN**\n`░░░░░░░░░░` **0%**")

        burn_start = time.time()

        # Determine subtitle type and prepare filter
        if sub_ext == '.ass':
            # Use ass filter for ASS subtitles
            vf_filter = f"ass={shlex.quote(sub_path)}"
        else:
            # Use subtitles filter for SRT
            vf_filter = f"subtitles={shlex.quote(sub_path)}:force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF&,OutlineColour=&H00000000&'"

        # Build optimized FFmpeg command
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-i', video_path,
            '-vf', vf_filter,
            '-c:v', 'libx264',
            '-preset', 'medium',  # Better balance between speed and quality
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-movflags', '+faststart',
            '-threads', '0',
            '-y',
            output_file
        ]

        logger.info("Starting ffmpeg: %s", ' '.join(shlex.quote(p) for p in cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Improved progress simulation
        async def simulate_burn_progress():
            start = time.time()
            estimated = max(10.0, duration * 0.5)  # More accurate estimation
            
            while process.returncode is None:
                elapsed = time.time() - start
                percent = min((elapsed / estimated) * 100, 95)  # Cap at 95% until done
                
                # Dynamic speed calculation
                speed_x = 1.0 + (percent / 100) * 3.0
                await burn_progress.update(percent, speed_x)
                
                # Check if process is still running
                if process.returncode is not None:
                    break
                    
                await asyncio.sleep(1)
            
            # Final update to 100%
            await burn_progress.update(100, 4.0)

        progress_task = asyncio.create_task(simulate_burn_progress())

        try:
            await process.wait()
        except Exception as e:
            logger.error(f"FFmpeg process error: {e}")
            process.kill()
            raise

        # Cancel progress task
        progress_task.cancel()

        burn_time = time.time() - burn_start

        # Check for errors
        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            error_text = stderr_output.decode('utf-8', errors='ignore')
            logger.error(f"FFmpeg error: {error_text}")
            raise Exception(f"Burn failed: {error_text[:200]}")

        if not os.path.exists(output_file):
            raise Exception("Output file not created by ffmpeg")

        output_size = os.path.getsize(output_file)
        burn_speed = (user_data[chat_id]["file_size"] / burn_time) / (1024 * 1024) if burn_time > 0 else 0

        # Upload with progress
        await status_msg.edit_text("🚀 **ULTRA UPLOAD STARTED**")
        upload_progress = UltraProgress(client, chat_id, status_msg.id, output_filename, "UPLOAD")

        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **ULTRA BURN COMPLETE!**\n\n"
                f"📊 **Results:**\n"
                f"• Burn Speed: `{burn_speed:.1f} MB/s`\n"
                f"• Burn Time: `{format_time(burn_time)}`\n"
                f"• Output Size: `{human_readable(output_size)}`\n"
                f"• Subtitle Type: `{sub_ext.upper()}`\n\n"
                f"🔥 **Subtitles permanently burned!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True,
            thumb=user_data[chat_id].get("video_path")  # Use original video for thumbnail
        )
        upload_time = time.time() - upload_start

        total_time = time.time() - user_data[chat_id]["start_time"]
        
        await status_msg.edit_text(
            f"🎉 **MISSION ACCOMPLISHED!**\n\n"
            f"✅ **Total Time:** {format_time(total_time)}\n"
            f"📊 **Upload Speed:** {output_size / upload_time / (1024 * 1024):.1f} MB/s\n"
            f"🚀 **Ready for next file!**"
        )

        # Cleanup
        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except Exception:
            pass

        # Remove processed files
        for file_path in [video_path, sub_path, output_file]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.warning(f"Failed to remove {file_path}: {e}")

        # Clear user data but keep session info
        user_data[chat_id] = {"processing": False}

    except Exception as e:
        logger.exception("Ultra burn error")
        error_msg = str(e)
        
        # Reset processing flag
        if chat_id in user_data:
            user_data[chat_id]["processing"] = False
        
        try:
            await status_msg.edit_text(
                f"❌ **ULTRA BURN FAILED!**\n\n"
                f"`{html.escape(error_msg)}`\n\n"
                f"💡 **Tips for success:**\n"
                f"• Use MP4 files when possible\n"
                f"• Keep files under 1GB for best speed\n"
                f"• Ensure subtitle file is properly formatted\n"
                f"• Use /cancel to restart"
            )
        except Exception:
            pass

        # Emergency cleanup
        if chat_id in user_data:
            for key in ["video_path", "subtitle_path", "output_path"]:
                file_path = user_data[chat_id].get(key)
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

# ---------- BOT STARTUP ----------
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 ULTRA FAST SUBTITLE BURNER - ENHANCED")
    print("=" * 50)
    print(f"⚡ Configured Max Size: {human_readable(MAX_FILE_SIZE)}")
    print(f"🔥 Workers: {WORKERS}")
    print(f"🏥 Health Port: {HEALTH_PORT}")
    print("📦 Supported: MP4, SRT, ASS")
    print("=" * 50)

    try:
        app.run()
    except KeyboardInterrupt:
        print("\n🛑 Stopping bot...")
        # Cleanup on exit
        for chat_id, data in user_data.items():
            for key in ["video_path", "subtitle_path", "output_path"]:
                file_path = data.get(key)
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
        print("✅ Cleanup complete!")
    except Exception as e:
        logger.exception("Bot failed to start")
        print(f"❌ Bot failed to start: {e}")
