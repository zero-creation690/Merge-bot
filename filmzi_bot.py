#!/usr/bin/env python3
"""
Ultra Fast Subtitle Burner - production-ready single-file bot
FIXED VERSION - Supports Sinhala, Tamil, and English subtitles
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

user_data = {}
executor = ThreadPoolExecutor(max_workers=max(2, WORKERS // 2))

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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0

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
        except Exception:
            pass

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
        "• **Unicode Support** (Sinhala, Tamil, English)\n"
        "• **2GB** max file size (configurable)\n\n"
        "📋 **How to use:**\n"
        "1. Send video file\n"
        "2. Send .srt subtitle file\n"
        "3. Receive video with burned subtitles!\n\n"
        "🔥 **Ready for ultra speed!**"
    )
    await message.reply_text(welcome_text)


@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **ULTRA FAST GUIDE**\n\n"
        "**Format:** Any → MP4\n"
        "**Subtitles:** Burned permanently\n"
        "**Languages:** Sinhala, Tamil, English (Unicode)\n"
        "**Max Size:** {}\n\n".format(human_readable(MAX_FILE_SIZE)) +
        "**Commands:**\n"
        "`/start` - Start bot\n"
        "`/help` - This guide\n"
        "`/cancel` - Cancel operation and cleanup\n\n"
        "🚀 **Send a video to experience ultra speed!**"
    )
    await message.reply_text(help_text)


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
        await message.reply_text("✅ **Cancelled and cleaned up!**")
    else:
        await message.reply_text("❌ **No active operation!**")

# ---------- FILE HANDLERS ----------
@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    chat_id = message.chat.id

    # document could be srt or video
    file_obj = None
    if message.video:
        file_obj = message.video
    elif message.document:
        file_obj = message.document
        # If it's an srt and we already have video, call subtitle handler
        if file_obj.file_name and file_obj.file_name.lower().endswith('.srt'):
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
    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text("⚠️ **Video already received** — send the .srt file now.")
        return

    unique_id = secrets.token_hex(6)
    ext = os.path.splitext(file_obj.file_name or "video.mp4")[1] or ".mp4"
    download_path = os.path.join(CACHE_DIR, f"v_{unique_id}{ext}")

    status_msg = await message.reply_text("🚀 **ULTRA DOWNLOAD STARTED**")
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
            "start_time": time.time()
        }

        await status_msg.edit_text(
            f"✅ **DOWNLOAD COMPLETE!**\n\n"
            f"🚀 **Speed:** {avg_speed:.1f} MB/s\n"
            f"⏱️ **Time:** {format_time(download_time)}\n\n"
            f"🔥 **Send subtitle file (.srt)**\n"
            f"🌍 **Supports:** Sinhala, Tamil, English"
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
        await message.reply_text("⚠️ **Send video first!**")
        return

    sub_obj = message.document
    if not sub_obj or not sub_obj.file_name or not sub_obj.file_name.lower().endswith('.srt'):
        await message.reply_text("❌ **Invalid!** Send a .srt subtitle file.")
        return

    status_msg = await message.reply_text("🚀 **DOWNLOADING SUBTITLE**")
    unique_id = secrets.token_hex(6)
    sub_filename = os.path.join(CACHE_DIR, f"s_{unique_id}.srt")

    progress = UltraProgress(client, chat_id, status_msg.id, sub_obj.file_name, "DOWNLOAD")

    try:
        sub_path = await message.download(file_name=sub_filename, progress=progress.update)

        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"burned_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)

        await status_msg.edit_text("🔍 **Analyzing video...**")
        duration = await asyncio.get_event_loop().run_in_executor(executor, get_video_duration, video_path)

        burn_progress = BurningProgress(client, chat_id, status_msg.id, base_name, duration)
        await status_msg.edit_text("🔥 **STARTING ULTRA BURN**\n`░░░░░░░░░░` **0%**\n🌍 **Unicode Support: Enabled**")

        burn_start = time.time()

        # FIXED: Use proper Unicode support for Sinhala/Tamil subtitles
        # Use filename= parameter and force UTF-8 encoding
        safe_sub_path = sub_path.replace("'", "'\\''")
        vf_filter = f"subtitles=filename='{safe_sub_path}':charenc=UTF-8:force_style='FontName=DejaVu Sans,FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000'"

        # Build FFmpeg command with Unicode support
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-i', video_path,
            '-vf', vf_filter,
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '24',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-threads', '0',
            '-y',
            output_file
        ]

        logger.info("Starting ffmpeg with Unicode support: %s", ' '.join(shlex.quote(p) for p in cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Simulate progress based on time & ffmpeg running status
        async def simulate_burn_progress():
            start = time.time()
            estimated = max(10.0, duration * 0.7)  # fallback if duration unknown
            while True:
                elapsed = time.time() - start
                percent = min((elapsed / estimated) * 100, 99)
                # speed_x is a heuristic
                speed_x = 1.0 + (percent / 100) * 2.0
                await burn_progress.update(percent, speed_x)
                await asyncio.sleep(1)
                if process.returncode is not None:
                    break
            # finalize to 100%
            await burn_progress.update(100, 3.0)

        progress_task = asyncio.create_task(simulate_burn_progress())

        try:
            await process.wait()
        except Exception:
            process.kill()
            raise

        progress_task.cancel()

        burn_time = time.time() - burn_start

        # Check for errors
        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            error_text = stderr_output.decode('utf-8', errors='ignore')
            raise Exception(f"Burn failed: {error_text[:200]}")

        if not os.path.exists(output_file):
            raise Exception("Output file not created by ffmpeg")

        output_size = os.path.getsize(output_file)
        burn_speed = (user_data[chat_id]["file_size"] / burn_time) / (1024 * 1024) if burn_time > 0 else 0

        # Upload
        await status_msg.edit_text("🚀 **ULTRA UPLOAD STARTED**")
        upload_progress = UltraProgress(client, chat_id, status_msg.id, os.path.basename(output_file), "UPLOAD")

        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **ULTRA BURN COMPLETE!**\n\n"
                f"🚀 **Burn Speed:** {burn_speed:.1f} MB/s\n"
                f"⏱️ **Burn Time:** {format_time(burn_time)}\n"
                f"📦 **Output Size:** {human_readable(output_size)}\n"
                f"🌍 **Unicode Support:** Sinhala/Tamil/English ✓\n\n"
                f"🔥 **Subtitles permanently burned!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )
        upload_time = time.time() - upload_start

        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **MISSION ACCOMPLISHED!**\n\n"
            f"✅ **Total Time:** {format_time(total_time)}\n"
            f"🌍 **Unicode Support:** Active ✓\n"
            f"🚀 **Ready for next file!**"
        )

        # cleanup
        await asyncio.sleep(1)
        try:
            await status_msg.delete()
        except Exception:
            pass

        for file_path in [video_path, sub_path, output_file]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

        del user_data[chat_id]

    except Exception as e:
        logger.exception("Ultra burn error")
        error_msg = str(e)
        try:
            await status_msg.edit_text(
                f"❌ **ULTRA BURN FAILED!**\n\n"
                f"`{html.escape(error_msg)}`\n\n"
                f"💡 **Tips for Sinhala/Tamil subtitles:**\n"
                f"• Ensure subtitle file is UTF-8 encoded\n"
                f"• Use MP4 files for best compatibility\n"
                f"• Keep files under 1GB\n"
                f"• Use /cancel to restart"
            )
        except Exception:
            pass

        # emergency cleanup
        if chat_id in user_data:
            for key in ["video", "subtitle", "output"]:
                file_path = user_data[chat_id].get(key)
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
            del user_data[chat_id]

# ---------- BOT STARTUP ----------
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 ULTRA FAST SUBTITLE BURNER")
    print("=" * 50)
    print(f"⚡ Configured Max Size: {human_readable(MAX_FILE_SIZE)}")
    print(f"🔥 Workers: {WORKERS}")
    print("🌍 Unicode Support: Sinhala, Tamil, English")
    print("📦 Output: MP4 with burned subtitles")
    print("=" * 50)

    try:
        app.run()
    except KeyboardInterrupt:
        print("Stopping...")
    except Exception as e:
        logger.exception("Bot failed to start")
        print(f"❌ Bot failed to start: {e}")
