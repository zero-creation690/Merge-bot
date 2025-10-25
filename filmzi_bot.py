#!/usr/bin/env python3
"""
ULTIMATE SPEED Subtitle Burner - AGGRESSIVE OPTIMIZATIONS
Works on any system with maximum possible speed
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
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", "2147483648"))  # 2GB
WORKERS = int(os.environ.get("WORKERS", "100"))
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/ultimate_bot")
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "8000"))

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
    "UltimateSpeedBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=CACHE_DIR,
    workers=WORKERS,
    in_memory=True,
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
                "service": "ultimate-speed-bot",
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

def sanitize_filename(filename: str) -> str:
    return re.sub(r'[^\w\-_. ]', '', filename)

# ---------- ULTIMATE SPEED FFMPEG COMMANDS ----------
def get_ultimate_speed_command(video_path: str, subtitle_path: str, output_path: str, sub_ext: str):
    """ULTIMATE SPEED - Most aggressive optimizations possible"""
    
    # FIX FOR SINHALA/UNICODE SUBTITLES - Force UTF-8 encoding and use subtitles filter
    if sub_ext == '.ass':
        vf_filter = f"ass={shlex.quote(subtitle_path)}:fontsdir=/tmp"
    else:
        # CRITICAL FIX: Force UTF-8 encoding for SRT files and use subtitles filter
        vf_filter = f"subtitles={shlex.quote(subtitle_path)}:charenc=UTF-8"
    
    # ULTIMATE SPEED encoding settings - FASTEST POSSIBLE
    return [
        'ffmpeg', '-hide_banner', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',          # FASTEST POSSIBLE PRESET
        '-tune', 'zerolatency',          # Zero latency - fastest
        '-crf', '32',                    # Balanced CRF for speed and quality
        '-x264-params', 
        'keyint=15:min-keyint=15:scenecut=0:bframes=0:ref=1:threads=auto',
        '-c:a', 'copy',                  # COPY AUDIO - CRITICAL
        '-movflags', '+faststart',
        '-threads', '0',                 # Use all threads
        '-max_muxing_queue_size', '9999',
        output_path
    ]

def get_extreme_speed_command(video_path: str, subtitle_path: str, output_path: str, sub_ext: str):
    """EVEN FASTER - Extreme optimizations"""
    if sub_ext == '.ass':
        vf_filter = f"ass={shlex.quote(subtitle_path)}:fontsdir=/tmp"
    else:
        vf_filter = f"subtitles={shlex.quote(subtitle_path)}:charenc=UTF-8"
    
    return [
        'ffmpeg', '-hide_banner', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-crf', '35',                    # Higher CRF for speed
        '-x264-params', 'scenecut=0:bframes=0:ref=1:threads=auto',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        '-threads', '0',
        output_path
    ]

def get_lightning_command(video_path: str, subtitle_path: str, output_path: str, sub_ext: str):
    """LIGHTNING FAST - Minimal viable encoding"""
    if sub_ext == '.ass':
        vf_filter = f"ass={shlex.quote(subtitle_path)}:fontsdir=/tmp"
    else:
        vf_filter = f"subtitles={shlex.quote(subtitle_path)}:charenc=UTF-8"
    
    return [
        'ffmpeg', '-hide_banner', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '38',                    # Maximum speed, lower quality
        '-c:a', 'copy',
        '-threads', '0',
        output_path
    ]

# ---------- DUAL PROGRESS TRACKING ----------
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

    async def update_from_ffmpeg(self, stderr_line: str):
        now = time.time()
        
        time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', stderr_line)
        if time_match:
            hours, minutes, seconds = map(float, time_match.groups())
            current_time = hours * 3600 + minutes * 60 + seconds
            
            if self.total_duration > 0:
                percent = min((current_time / self.total_duration) * 100, 99)
            else:
                percent = self.last_percent + 2.0  # Fast updates

            # Update frequently for better feedback
            if (percent - self.last_percent >= 1) or (now - self.last_update >= 2):
                await self.update_display(percent, current_time)
                self.last_percent = percent
                self.last_update = now

    async def update_display(self, percent: float, current_time: float):
        elapsed = time.time() - self.start_time
        
        if current_time > 0 and elapsed > 0:
            speed_x = current_time / elapsed
            if speed_x > 0:
                remaining_time = (self.total_duration - current_time) / speed_x
                eta = format_time(max(0, remaining_time))
            else:
                eta = "calculating..."
        else:
            speed_x = 0.1
            eta = "calculating..."

        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        bar = "🔥" * filled_len + "░" * (bar_len - filled_len)

        # Realistic speed display
        if speed_x > 10.0:
            status = "LIGHTNING"
        elif speed_x > 5.0:
            status = "ULTRA FAST"
        elif speed_x > 2.0:
            status = "VERY FAST"
        elif speed_x > 1.0:
            status = "FAST"
        elif speed_x > 0.5:
            status = "GOOD"
        else:
            status = "PROCESSING"

        time_info = f"({format_time(current_time)}/{format_time(self.total_duration)})"

        text = (
            f"🎬 **BURNING SUBTITLES** - {status}\n"
            f"`{bar}` **{percent:.1f}%** {time_info}\n"
            f"⚡ **Speed:** **{speed_x:.1f}x** • **ETA:** `{eta}`\n"
            f"📝 **Encoding:** `ULTRAFAST` + `AUDIO COPY`"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception as e:
            logger.debug(f"Progress update failed: {e}")

    async def complete(self):
        total_time = time.time() - self.start_time
        text = (
            f"✅ **BURNING COMPLETE!**\n"
            f"`{'🔥' * 10}` **100%**\n"
            f"⏱️ **Processing Time:** {format_time(total_time)}\n"
            f"**Starting upload...**"
        )
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception:
            pass

class UploadProgress:
    def __init__(self, client: Client, chat_id: int, message_id: int, filename: str):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.start_time = time.time()
        self.last_update = self.start_time
        self.history = []

    async def update(self, current: int, total: int):
        now = time.time()
        if now - self.last_update < 0.5 and current < total:
            return
        elapsed = now - self.start_time
        self.last_update = now
        self.history.append((now, current))
        if len(self.history) > 5:
            self.history.pop(0)

        if len(self.history) >= 2:
            dt = self.history[-1][0] - self.history[0][0]
            db = self.history[-1][1] - self.history[0][1]
            avg_speed = (db / dt) / (1024 * 1024) if dt > 0 else 0
        else:
            avg_speed = (current / elapsed) / (1024 * 1024) if elapsed > 0 else 0

        percent = (current * 100 / total) if total > 0 else 0
        eta = (total - current) / (avg_speed * 1024 * 1024) if avg_speed > 0 else 0

        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        bar = "📤" * filled_len + "░" * (bar_len - filled_len)

        if avg_speed > 20:
            emoji = "🚀"
        elif avg_speed > 10:
            emoji = "⚡"
        elif avg_speed > 5:
            emoji = "🔥"
        else:
            emoji = "📶"

        text = (
            f"📤 **UPLOADING VIDEO**\n"
            f"`{bar}` **{percent:.1f}%**\n"
            f"{emoji} **Speed:** **{avg_speed:.1f} MB/s** • **ETA:** `{format_time(eta)}`\n"
            f"`{self.filename[:35]}`"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception as e:
            logger.debug(f"Upload progress update failed: {e}")

class DownloadProgress:
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
        if now - self.last_update < 0.5 and current < total:
            return
        elapsed = now - self.start_time
        self.last_update = now
        self.history.append((now, current))
        if len(self.history) > 5:
            self.history.pop(0)

        if len(self.history) >= 2:
            dt = self.history[-1][0] - self.history[0][0]
            db = self.history[-1][1] - self.history[0][1]
            avg_speed = (db / dt) / (1024 * 1024) if dt > 0 else 0
        else:
            avg_speed = (current / elapsed) / (1024 * 1024) if elapsed > 0 else 0

        percent = (current * 100 / total) if total > 0 else 0
        eta = (total - current) / (avg_speed * 1024 * 1024) if avg_speed > 0 else 0

        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        bar = "📥" * filled_len + "░" * (bar_len - filled_len)

        if avg_speed > 20:
            emoji = "🚀"
        elif avg_speed > 10:
            emoji = "⚡"
        elif avg_speed > 5:
            emoji = "🔥"
        else:
            emoji = "📶"

        text = (
            f"📥 **{self.action}**\n"
            f"`{bar}` **{percent:.1f}%**\n"
            f"{emoji} **Speed:** **{avg_speed:.1f} MB/s** • **ETA:** `{format_time(eta)}`\n"
            f"`{self.filename[:40]}`"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception as e:
            logger.debug(f"Progress update failed: {e}")

# ---------- BOT COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "🚀 **ULTIMATE SPEED SUBTITLE BOT** ⚡\n\n"
        "⚡ **AGGRESSIVE OPTIMIZATIONS:**\n"
        "• **Ultrafast encoding** (fastest possible)\n"
        "• **Audio stream copy** (no re-encode)\n"
        "• **Unicode support** (Sinhala, Tamil, etc.)\n"
        "• **Minimal processing** (max speed)\n"
        "• **All languages** supported\n\n"
        "📋 **How to use:**\n"
        "1. Send video file\n"
        "2. Send subtitle file\n"
        "3. Get ULTIMATE SPEED results!\n\n"
        "⚡ **Fastest possible processing!**"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Help", callback_data="help"),
         InlineKeyboardButton("⚡ Speed Tips", callback_data="speedtips")]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **ULTIMATE SPEED GUIDE** ⚡\n\n"
        "**Speed:** Maximum possible\n"
        "**Quality:** Good (optimized for speed)\n"
        "**Audio:** Copy stream (no re-encode)\n"
        "**Languages:** ALL supported (including Sinhala)\n"
        "**Max Size:** {}\n\n".format(human_readable(MAX_FILE_SIZE)) +
        "**Speed Techniques:**\n"
        "• Ultrafast video encoding\n"
        "• Audio stream copy\n"
        "• Unicode subtitle support\n"
        "• Aggressive threading\n\n"
        "**Expected Speed:** 3-10x realtime\n\n"
        "**Commands:**\n"
        "`/start` - Start bot\n"
        "`/help` - This guide\n"
        "`/speedtips` - Speed optimization tips\n"
        "`/cancel` - Cancel operation\n\n"
        "⚡ **Ultimate speed optimizations active!**"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("speedtips"))
async def speedtips_command(client: Client, message: Message):
    speedtips_text = (
        "⚡ **SPEED OPTIMIZATION TIPS** 🚀\n\n"
        "**For Maximum Speed:**\n"
        "• Use MP4 videos (fastest processing)\n"
        "• Keep videos under 10 minutes\n"
        "• Use 720p instead of 1080p\n"
        "• UTF-8 encoded subtitle files\n\n"
        "**Expected Performance:**\n"
        "• 1-minute video: ~10-30 seconds\n"
        "• 5-minute video: ~1-2 minutes\n"
        "• 10-minute video: ~2-4 minutes\n\n"
        "**Current Optimizations:**\n"
        "✅ Ultrafast encoding preset\n"
        "✅ Audio stream copy\n"
        "✅ Unicode support (Sinhala)\n"
        "✅ Maximum threading\n"
        "✅ Minimal processing\n\n"
        "🚀 **Ultimate speed active!**"
    )
    await message.reply_text(speedtips_text)

@app.on_message(filters.command("cancel"))
async def cancel_operation(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id in user_data:
        for key in ["video_path", "subtitle_path", "output_path"]:
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

@app.on_callback_query()
async def handle_callbacks(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    
    if data == "help":
        await help_command(client, callback_query.message)
    elif data == "speedtips":
        await speedtips_command(client, callback_query.message)
    
    await callback_query.answer()

# ---------- ULTIMATE SPEED FILE HANDLERS ----------
@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    chat_id = message.chat.id

    if chat_id in user_data and user_data[chat_id].get("processing"):
        await message.reply_text("⚠️ **Please wait for current operation to complete!**")
        return

    file_obj = None
    if message.video:
        file_obj = message.video
    elif message.document:
        file_obj = message.document
        if (file_obj.file_name and 
            file_obj.file_name.lower().endswith(('.srt', '.ass', '.ssa')) and
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

    if chat_id in user_data and "video_path" in user_data[chat_id]:
        await message.reply_text("⚠️ **Video already received** — send subtitle file (.srt, .ass, .ssa).")
        return

    unique_id = secrets.token_hex(6)
    original_filename = file_obj.file_name or "video.mp4"
    safe_filename = sanitize_filename(original_filename)
    ext = os.path.splitext(safe_filename)[1] or ".mp4"
    download_path = os.path.join(CACHE_DIR, f"v_{unique_id}{ext}")

    status_msg = await message.reply_text("📥 **DOWNLOADING VIDEO**")
    progress = DownloadProgress(client, chat_id, status_msg.id, safe_filename, "DOWNLOAD")

    try:
        download_start = time.time()
        video_path = await message.download(file_name=download_path, progress=progress.update)
        download_time = time.time() - download_start
        avg_speed = file_obj.file_size / download_time / (1024 * 1024) if download_time > 0 else 0

        duration = await asyncio.get_event_loop().run_in_executor(executor, get_video_duration, video_path)

        user_data[chat_id] = {
            "video_path": video_path,
            "original_filename": safe_filename,
            "file_size": file_obj.file_size,
            "duration": duration,
            "start_time": time.time(),
            "processing": False
        }

        await status_msg.edit_text(
            f"✅ **DOWNLOAD COMPLETE!**\n\n"
            f"📊 **Video Info:**\n"
            f"• Duration: `{format_time(duration)}`\n"
            f"• Size: `{human_readable(file_obj.file_size)}`\n\n"
            f"🚀 **Speed:** {avg_speed:.1f} MB/s\n"
            f"⏱️ **Time:** {format_time(download_time)}\n\n"
            f"⚡ **Send subtitle for ULTIMATE SPEED processing!**"
        )

    except Exception as e:
        logger.exception("Download failed")
        try:
            await status_msg.edit_text(f"❌ **Download failed:** `{html.escape(str(e))}`")
        except Exception:
            pass
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
    supported_formats = ('.srt', '.ass', '.ssa')
    if not any(sub_ext.endswith(fmt) for fmt in supported_formats):
        await message.reply_text("❌ **Invalid subtitle format!** Send .srt, .ass, or .ssa file.")
        return

    status_msg = await message.reply_text("📥 **DOWNLOADING SUBTITLE**")
    unique_id = secrets.token_hex(6)
    sub_ext = os.path.splitext(sub_obj.file_name)[1].lower()
    sub_filename = os.path.join(CACHE_DIR, f"s_{unique_id}{sub_ext}")

    progress = DownloadProgress(client, chat_id, status_msg.id, sub_obj.file_name, "DOWNLOAD")

    try:
        sub_path = await message.download(file_name=sub_filename, progress=progress.update)

        video_path = user_data[chat_id]["video_path"]
        original_filename = user_data[chat_id]["original_filename"]
        duration = user_data[chat_id]["duration"]
        
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"{base_name}_ULTIMATE_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)

        user_data[chat_id]["processing"] = True
        user_data[chat_id]["subtitle_path"] = sub_path
        user_data[chat_id]["output_path"] = output_file

        # Try ULTIMATE SPEED command first - WITH SINHALA FIX
        ffmpeg_cmd = get_ultimate_speed_command(video_path, sub_path, output_file, sub_ext)
        
        await status_msg.edit_text(
            f"🎬 **STARTING ULTIMATE SPEED PROCESSING**\n"
            f"`░░░░░░░░░░` **0%**\n"
            f"⚡ **Optimizations:** ULTRAFAST + AUDIO COPY\n"
            f"🌐 **Subtitle Support:** Unicode (Sinhala OK)\n"
            f"🎯 **Target Time:** {format_time(duration / 5)}"
        )

        burn_start = time.time()
        burn_progress = BurningProgress(client, chat_id, status_msg.id, base_name, duration)

        logger.info(f"Running ULTIMATE SPEED FFmpeg with Unicode support")
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        async def read_progress():
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore')
                await burn_progress.update_from_ffmpeg(line_str)

        progress_task = asyncio.create_task(read_progress())

        try:
            await process.wait()
        except Exception as e:
            logger.error(f"FFmpeg process error: {e}")
            # Try extreme speed fallback
            logger.info("Trying EXTREME SPEED fallback...")
            ffmpeg_cmd = get_extreme_speed_command(video_path, sub_path, output_file, sub_ext)
            process = await asyncio.create_subprocess_exec(*ffmpeg_cmd)
            await process.wait()

        progress_task.cancel()

        burn_time = time.time() - burn_start
        await burn_progress.complete()

        if process.returncode != 0:
            # Try lightning speed as last resort
            logger.info("Trying LIGHTNING SPEED as last resort...")
            ffmpeg_cmd = get_lightning_command(video_path, sub_path, output_file, sub_ext)
            process = await asyncio.create_subprocess_exec(*ffmpeg_cmd)
            await process.wait()

        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            error_text = stderr_output.decode('utf-8', errors='ignore')
            raise Exception(f"Processing failed: {error_text[:200]}")

        if not os.path.exists(output_file):
            raise Exception("Output file not created")

        output_size = os.path.getsize(output_file)

        # CREATE SEPARATE UPLOAD PROGRESS
        await status_msg.edit_text("📤 **STARTING UPLOAD**")
        upload_progress = UploadProgress(client, chat_id, status_msg.id, output_filename)

        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **ULTIMATE SPEED COMPLETE!** ⚡\n\n"
                f"📊 **Performance:**\n"
                f"• Processing Time: `{format_time(burn_time)}`\n"
                f"• Speed: `{duration/burn_time:.1f}x` realtime\n"
                f"• Audio: `COPY` (no re-encode)\n"
                f"• Subtitles: `Unicode Supported`\n"
                f"• Quality: `GOOD` (speed optimized)\n\n"
                f"⚡ **Ultimate speed achieved!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )

        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **ULTIMATE SPEED SUCCESS!** ⚡\n\n"
            f"✅ **Total Time:** {format_time(total_time)}\n"
            f"⚡ **Speed Factor:** {duration/burn_time:.1f}x\n"
            f"🌐 **Unicode Support:** Sinhala ✓\n"
            f"🚀 **Ready for next file!**"
        )

        await asyncio.sleep(2)
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

        user_data[chat_id] = {"processing": False}

    except Exception as e:
        logger.exception("Ultimate speed processing error")
        error_msg = str(e)
        
        if chat_id in user_data:
            user_data[chat_id]["processing"] = False
        
        try:
            await status_msg.edit_text(
                f"❌ **PROCESSING FAILED!** ⚡\n\n"
                f"`{html.escape(error_msg)}`\n\n"
                f"💡 **For maximum speed:**\n"
                f"• Try shorter videos (1-5 minutes)\n"
                f"• Use MP4 format videos\n"
                f"• Ensure subtitles are UTF-8 encoded\n"
                f"• Use /cancel to restart"
            )
        except Exception:
            pass

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
    print("=" * 60)
    print("🚀 ULTIMATE SPEED SUBTITLE BOT - FASTEST POSSIBLE")
    print("=" * 60)
    print(f"📦 Max Size: {human_readable(MAX_FILE_SIZE)}")
    print(f"🔥 Workers: {WORKERS}")
    print(f"🏥 Health Port: {HEALTH_PORT}")
    print("🎯 Features: Ultrafast, Audio copy, Unicode support")
    print("🌐 Language Support: English, Sinhala, Tamil, etc.")
    print("⚡ Expected Speed: 3-10x realtime")
    print("=" * 60)

    try:
        app.run()
    except KeyboardInterrupt:
        print("\n🛑 Stopping bot...")
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
