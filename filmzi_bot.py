#!/usr/bin/env python3
"""
ULTIMATE SPEED Subtitle Burner - ENGLISH, TAMIL, SINHALA
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

# ---------- LANGUAGE SPECIFIC FFMPEG COMMANDS ----------
def get_english_command(video_path: str, subtitle_path: str, output_path: str, sub_ext: str):
    """English - Standard processing"""
    if sub_ext == '.ass':
        vf_filter = f"ass={shlex.quote(subtitle_path)}"
    else:
        vf_filter = f"subtitles=filename={shlex.quote(subtitle_path)}"
    
    return [
        'ffmpeg', '-hide_banner', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '28',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        '-threads', '0',
        output_path
    ]

def get_tamil_command(video_path: str, subtitle_path: str, output_path: str, sub_ext: str):
    """Tamil - Unicode support with proper font handling"""
    if sub_ext == '.ass':
        vf_filter = f"ass={shlex.quote(subtitle_path)}:fontsdir=/usr/share/fonts"
    else:
        vf_filter = f"subtitles=filename={shlex.quote(subtitle_path)}:charenc=UTF-8"
    
    return [
        'ffmpeg', '-hide_banner', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '28',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        '-threads', '0',
        output_path
    ]

def get_sinhala_command(video_path: str, subtitle_path: str, output_path: str, sub_ext: str):
    """Sinhala - Enhanced Unicode support"""
    if sub_ext == '.ass':
        vf_filter = f"ass={shlex.quote(subtitle_path)}:fontsdir=/usr/share/fonts"
    else:
        vf_filter = f"subtitles=filename={shlex.quote(subtitle_path)}:charenc=UTF-8:force_style='FontName=Noto Sans Sinhala'"
    
    return [
        'ffmpeg', '-hide_banner', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '28',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        '-threads', '0',
        output_path
    ]

def get_fallback_command(video_path: str, subtitle_path: str, output_path: str, sub_ext: str):
    """Fallback - Maximum compatibility"""
    if sub_ext == '.ass':
        vf_filter = f"ass={shlex.quote(subtitle_path)}"
    else:
        vf_filter = f"subtitles=filename={shlex.quote(subtitle_path)}:charenc=UTF-8"
    
    return [
        'ffmpeg', '-hide_banner', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '30',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        '-threads', '0',
        output_path
    ]

# ---------- PROGRESS TRACKING ----------
class BurningProgress:
    def __init__(self, client: Client, chat_id: int, message_id: int, filename: str, total_duration: float, language: str):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.total_duration = total_duration
        self.language = language
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
                percent = self.last_percent + 2.0

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

        # Language emoji mapping
        lang_emoji = {
            "english": "🇺🇸",
            "tamil": "🇮🇳", 
            "sinhala": "🇱🇰"
        }
        emoji = lang_emoji.get(self.language, "🌐")

        text = (
            f"{emoji} **BURNING {self.language.upper()} SUBTITLES**\n"
            f"`{bar}` **{percent:.1f}%**\n"
            f"⚡ **Speed:** **{speed_x:.1f}x** • **ETA:** `{eta}`\n"
            f"🎯 **Language:** `{self.language.upper()}`"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception as e:
            logger.debug(f"Progress update failed: {e}")

    async def complete(self):
        total_time = time.time() - self.start_time
        text = (
            f"✅ **{self.language.upper()} BURNING COMPLETE!**\n"
            f"`{'🔥' * 10}` **100%**\n"
            f"⏱️ **Processing Time:** {format_time(total_time)}\n"
            f"**Starting upload...**"
        )
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception:
            pass

class UploadProgress:
    def __init__(self, client: Client, chat_id: int, message_id: int, filename: str, language: str):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.language = language
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
            f"📤 **UPLOADING {self.language.upper()} VIDEO**\n"
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
        "**🌍 SUPPORTED LANGUAGES:**\n"
        "• 🇺🇸 **English** - Standard processing\n"
        "• 🇮🇳 **Tamil** - Unicode support\n"
        "• 🇱🇰 **Sinhala** - Enhanced Unicode\n\n"
        "**⚡ FEATURES:**\n"
        "• Ultrafast encoding\n"
        "• Audio stream copy\n"
        "• Language-specific optimization\n"
        "• Dual progress tracking\n\n"
        "**📋 HOW TO USE:**\n"
        "1. Send video file\n"
        "2. Select language\n"
        "3. Send subtitle file\n"
        "4. Get optimized results!"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Help", callback_data="help"),
         InlineKeyboardButton("🌍 Languages", callback_data="languages")]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **ULTIMATE SPEED GUIDE** ⚡\n\n"
        "**Supported Languages:**\n"
        "🇺🇸 **English** - Standard processing\n"
        "🇮🇳 **Tamil** - Unicode character support\n"
        "🇱🇰 **Sinhala** - Enhanced Unicode rendering\n\n"
        "**Features:**\n"
        "• Maximum speed encoding\n"
        "• Audio stream copy (no re-encode)\n"
        "• Language-specific optimizations\n"
        "• Dual progress tracking\n"
        "**Max Size:** {}\n\n".format(human_readable(MAX_FILE_SIZE)) +
        "**Commands:**\n"
        "`/start` - Start bot\n"
        "`/help` - This guide\n"
        "`/languages` - Language info\n"
        "`/cancel` - Cancel operation\n\n"
        "**Workflow:**\n"
        "1. Send video → 2. Select language → 3. Send subtitle → 4. Get result!"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("languages"))
async def languages_command(client: Client, message: Message):
    languages_text = (
        "🌍 **SUPPORTED LANGUAGES**\n\n"
        "🇺🇸 **ENGLISH**\n"
        "• Standard subtitle processing\n"
        "• Fastest encoding\n"
        "• Best for .srt and .ass files\n\n"
        "🇮🇳 **TAMIL**\n"
        "• Unicode character support\n"
        "• UTF-8 encoding\n"
        "• Proper Tamil font rendering\n\n"
        "🇱🇰 **SINHALA**\n"
        "• Enhanced Unicode support\n"
        "• Complex script handling\n"
        "• Special font optimization\n\n"
        "⚡ **All languages use ultrafast encoding with audio copy!**"
    )
    await message.reply_text(languages_text)

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
    elif data == "languages":
        await languages_command(client, callback_query.message)
    elif data in ["english", "tamil", "sinhala"]:
        if chat_id in user_data and "video_path" in user_data[chat_id]:
            user_data[chat_id]["language"] = data
            await callback_query.message.edit_text(
                f"✅ **Language Selected:** {data.upper()}\n\n"
                f"🌍 **Now send your subtitle file** (.srt or .ass)\n"
                f"**Selected:** `{data.upper()}`\n\n"
                f"⚡ **Optimizations activated for {data}!**"
            )
        else:
            await callback_query.answer("❌ Please send video first!", show_alert=True)
    
    await callback_query.answer()

# ---------- FILE HANDLERS ----------
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
        # If subtitle file received but no language selected
        if (file_obj.file_name and 
            file_obj.file_name.lower().endswith(('.srt', '.ass', '.ssa')) and
            chat_id in user_data and "video_path" in user_data[chat_id]):
            # If language not selected, ask for language
            if "language" not in user_data[chat_id]:
                await message.reply_text("❌ **Please select language first!** Use /start")
                return
            else:
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
        await message.reply_text("⚠️ **Video already received** — please select language first.")
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

        # Ask user to select language
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇺🇸 English", callback_data="english"),
             InlineKeyboardButton("🇮🇳 Tamil", callback_data="tamil")],
            [InlineKeyboardButton("🇱🇰 Sinhala", callback_data="sinhala")]
        ])

        await status_msg.edit_text(
            f"✅ **VIDEO DOWNLOADED!**\n\n"
            f"📊 **Video Info:**\n"
            f"• Duration: `{format_time(duration)}`\n"
            f"• Size: `{human_readable(file_obj.file_size)}`\n"
            f"• Speed: `{avg_speed:.1f} MB/s`\n\n"
            f"🌍 **Please select subtitle language:**",
            reply_markup=keyboard
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

    if "language" not in user_data[chat_id]:
        await message.reply_text("❌ **Please select language first!**")
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
        language = user_data[chat_id]["language"]
        
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"{base_name}_{language.upper()}_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)

        user_data[chat_id]["processing"] = True
        user_data[chat_id]["subtitle_path"] = sub_path
        user_data[chat_id]["output_path"] = output_file

        # Select command based on language
        language_commands = {
            "english": get_english_command,
            "tamil": get_tamil_command, 
            "sinhala": get_sinhala_command
        }
        
        ffmpeg_cmd_func = language_commands.get(language, get_fallback_command)
        ffmpeg_cmd = ffmpeg_cmd_func(video_path, sub_path, output_file, sub_ext)
        
        # Language emoji mapping
        lang_emoji = {
            "english": "🇺🇸",
            "tamil": "🇮🇳",
            "sinhala": "🇱🇰"
        }
        emoji = lang_emoji.get(language, "🌐")

        await status_msg.edit_text(
            f"{emoji} **STARTING {language.upper()} PROCESSING**\n"
            f"`░░░░░░░░░░` **0%**\n"
            f"⚡ **Language:** `{language.upper()}`\n"
            f"🎯 **Optimizations:** Language-specific encoding\n"
            f"⏱️ **Target Time:** {format_time(duration / 5)}"
        )

        burn_start = time.time()
        burn_progress = BurningProgress(client, chat_id, status_msg.id, base_name, duration, language)

        logger.info(f"Running {language.upper()} FFmpeg processing")
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
            # Try fallback command
            logger.info("Trying fallback command...")
            ffmpeg_cmd = get_fallback_command(video_path, sub_path, output_file, sub_ext)
            process = await asyncio.create_subprocess_exec(*ffmpeg_cmd)
            await process.wait()

        progress_task.cancel()

        burn_time = time.time() - burn_start
        await burn_progress.complete()

        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            error_text = stderr_output.decode('utf-8', errors='ignore')
            raise Exception(f"Processing failed: {error_text[:200]}")

        if not os.path.exists(output_file):
            raise Exception("Output file not created")

        output_size = os.path.getsize(output_file)

        # UPLOAD PHASE
        await status_msg.edit_text("📤 **STARTING UPLOAD**")
        upload_progress = UploadProgress(client, chat_id, status_msg.id, output_filename, language)

        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **{language.upper()} PROCESSING COMPLETE!** ⚡\n\n"
                f"📊 **Performance:**\n"
                f"• Language: `{language.upper()}`\n"
                f"• Processing Time: `{format_time(burn_time)}`\n"
                f"• Speed: `{duration/burn_time:.1f}x` realtime\n"
                f"• Audio: `COPY` (no re-encode)\n"
                f"• Quality: `OPTIMIZED`\n\n"
                f"🌍 **Language-specific encoding successful!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )

        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **{language.upper()} SUCCESS!** ⚡\n\n"
            f"✅ **Total Time:** {format_time(total_time)}\n"
            f"⚡ **Speed Factor:** {duration/burn_time:.1f}x\n"
            f"🌍 **Language:** {language.upper()} ✓\n"
            f"🚀 **Ready for next file!**"
        )

        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except Exception:
            pass

        # Cleanup
        for file_path in [video_path, sub_path, output_file]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

        user_data[chat_id] = {"processing": False}

    except Exception as e:
        logger.exception(f"{language.upper()} processing error")
        error_msg = str(e)
        
        if chat_id in user_data:
            user_data[chat_id]["processing"] = False
        
        try:
            await status_msg.edit_text(
                f"❌ **{language.upper()} PROCESSING FAILED!** ⚡\n\n"
                f"`{html.escape(error_msg)}`\n\n"
                f"💡 **Tips for {language.upper()}:**\n"
                f"• Ensure subtitle is UTF-8 encoded\n"
                f"• Try shorter videos (1-5 minutes)\n"
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
    print("🚀 ULTIMATE SPEED SUBTITLE BOT - 3 LANGUAGES")
    print("=" * 60)
    print(f"📦 Max Size: {human_readable(MAX_FILE_SIZE)}")
    print(f"🔥 Workers: {WORKERS}")
    print(f"🏥 Health Port: {HEALTH_PORT}")
    print("🌍 Supported Languages: English, Tamil, Sinhala")
    print("⚡ Features: Language-specific optimization")
    print("🎯 Audio: Copy stream (no re-encode)")
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
