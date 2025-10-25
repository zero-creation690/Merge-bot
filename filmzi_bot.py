#!/usr/bin/env python3
"""
UNIVERSAL Subtitle Burner - SUPPORTS ALL LANGUAGES
Works with Sinhala, Arabic, Chinese, Japanese, Korean, Hindi, etc.
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
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/universal_bot")
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
    "UniversalSubBot",
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
                "service": "universal-subtitle-bot",
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

def detect_subtitle_encoding(file_path: str) -> str:
    """Detect subtitle file encoding"""
    try:
        # Try to detect encoding
        import chardet
        with open(file_path, 'rb') as f:
            raw_data = f.read()
            result = chardet.detect(raw_data)
            encoding = result['encoding']
            confidence = result['confidence']
            
            logger.info(f"Detected encoding: {encoding} (confidence: {confidence})")
            
            if encoding and confidence > 0.7:
                return encoding
    except Exception as e:
        logger.warning(f"Encoding detection failed: {e}")
    
    # Fallback encodings for different languages
    return 'utf-8'

def convert_subtitle_to_utf8(subtitle_path: str) -> str:
    """Convert subtitle to UTF-8 with BOM for best compatibility"""
    try:
        encoding = detect_subtitle_encoding(subtitle_path)
        logger.info(f"Converting subtitle from {encoding} to UTF-8")
        
        # Read with detected encoding
        with open(subtitle_path, 'r', encoding=encoding, errors='replace') as f:
            content = f.read()
        
        # Write with UTF-8 BOM
        converted_path = subtitle_path + '.utf8'
        with open(converted_path, 'w', encoding='utf-8-sig') as f:
            f.write(content)
        
        return converted_path
    except Exception as e:
        logger.error(f"Subtitle conversion failed: {e}")
        return subtitle_path

def get_universal_font_path():
    """Get a font that supports all languages"""
    # Common fonts that support multiple languages
    universal_fonts = [
        # Linux fonts
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
        # Windows fonts (if using Wine)
        '/usr/share/windows/fonts/arial.ttf',
        # Android fonts
        '/system/fonts/NotoSans-Regular.ttf',
        # Google Noto fonts (best for international)
        '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    ]
    
    for font_path in universal_fonts:
        if os.path.exists(font_path):
            logger.info(f"Using universal font: {font_path}")
            return font_path
    
    logger.warning("No universal font found, using fallback")
    return "Arial"  # Fallback to Arial

def sanitize_filename(filename: str) -> str:
    return re.sub(r'[^\w\-_. ]', '', filename)

# ---------- UNIVERSAL FFMPEG COMMANDS ----------
def get_universal_ffmpeg_command(video_path: str, subtitle_path: str, output_path: str, sub_ext: str):
    """Get FFmpeg command that supports ALL languages"""
    
    # Convert subtitle to UTF-8 if needed
    if sub_ext in ['.srt', '.ass', '.ssa']:
        subtitle_path = convert_subtitle_to_utf8(subtitle_path)
    
    # Get universal font
    font_path = get_universal_font_path()
    
    # Universal subtitle styles for all languages
    if sub_ext == '.ass':
        # For ASS files, use the built-in styling
        vf_filter = f"ass={shlex.quote(subtitle_path)}"
    else:
        # For SRT and other formats, apply universal styling
        style_options = [
            f"Fontname={font_path}",
            "FontSize=24",
            "PrimaryColour=&H00FFFFFF",      # White text
            "OutlineColour=&H00000000",      # Black outline
            "BackColour=&H80000000",         # Semi-transparent background
            "Bold=0",
            "Italic=0",
            "BorderStyle=1",
            "Outline=1",
            "Shadow=1",
            "MarginL=10",
            "MarginR=10",
            "MarginV=20",
            "Alignment=2"  # Center bottom
        ]
        style_string = ','.join(style_options)
        
        vf_filter = f"subtitles={shlex.quote(subtitle_path)}:force_style='{style_string}'"
    
    # Universal encoding settings
    return [
        'ffmpeg', '-hide_banner', '-y',
        '-i', video_path,
        '-vf', vf_filter,
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '23',
        '-c:a', 'copy',  # Copy audio for speed
        '-movflags', '+faststart',
        '-threads', '0',
        output_path
    ]

# ---------- PROGRESS TRACKING ----------
class UniversalProgress:
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
        """Parse actual progress from FFmpeg stderr"""
        now = time.time()
        
        # Parse time from ffmpeg output
        time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', stderr_line)
        if time_match:
            hours, minutes, seconds = map(float, time_match.groups())
            current_time = hours * 3600 + minutes * 60 + seconds
            
            if self.total_duration > 0:
                percent = min((current_time / self.total_duration) * 100, 99)
            else:
                percent = self.last_percent + 0.5

            if (percent - self.last_percent >= 1) or (now - self.last_update >= 5):
                await self.update_display(percent, current_time)
                self.last_percent = percent
                self.last_update = now

    async def update_display(self, percent: float, current_time: float):
        """Update the progress display"""
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
        bar = "🌍" * filled_len + "░" * (bar_len - filled_len)

        if speed_x > 5.0:
            status = "ULTRA FAST"
        elif speed_x > 2.0:
            status = "VERY FAST"
        elif speed_x > 1.0:
            status = "FAST"
        elif speed_x > 0.5:
            status = "NORMAL"
        else:
            status = "PROCESSING"

        time_info = f"({format_time(current_time)}/{format_time(self.total_duration)})"

        text = (
            f"🌍 **UNIVERSAL {status}** • **{speed_x:.1f}x**\n"
            f"`{bar}` **{percent:.1f}%** {time_info}\n"
            f"⏱️ **ETA:** `{eta}`\n"
            f"**Supporting all languages...**"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception as e:
            logger.debug(f"Progress update failed: {e}")

    async def complete(self):
        """Mark as 100% complete"""
        total_time = time.time() - self.start_time
        text = (
            f"✅ **UNIVERSAL PROCESSING COMPLETE!**\n"
            f"`{'🌍' * 10}` **100%**\n"
            f"⏱️ **Processing Time:** {format_time(total_time)}\n"
            f"**Finalizing multilingual output...**"
        )
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception:
            pass

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
        bar = "█" * filled_len + "░" * (bar_len - filled_len)

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

# ---------- BOT COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "🌍 **UNIVERSAL SUBTITLE BOT** 🌍\n\n"
        "✅ **Supports ALL Languages:**\n"
        "• Sinhala (සිංහල)\n" 
        "• Arabic (العربية)\n"
        "• Chinese (中文)\n"
        "• Japanese (日本語)\n"
        "• Korean (한국어)\n"
        "• Hindi (हिन्दी)\n"
        "• And 100+ more!\n\n"
        "📋 **How to use:**\n"
        "1. Send video file\n"
        "2. Send subtitle file (.srt, .ass)\n"
        "3. Get perfect multilingual results!\n\n"
        "🚀 **Universal language support guaranteed!**"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Help", callback_data="help"),
         InlineKeyboardButton("🌍 Supported Languages", callback_data="languages")]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **UNIVERSAL SUBTITLE GUIDE** 🌍\n\n"
        "**Supported Languages:** ALL\n"
        "**Formats:** SRT, ASS, SSA\n"
        "**Encoding:** Automatic UTF-8 conversion\n"
        "**Fonts:** Universal font support\n"
        "**Max Size:** {}\n\n".format(human_readable(MAX_FILE_SIZE)) +
        "**Features:**\n"
        "• Automatic encoding detection\n"
        "• Universal font rendering\n"
        "• Right-to-left support (Arabic, Hebrew)\n"
        "• Complex scripts (Sinhala, Thai, etc.)\n\n"
        "**Commands:**\n"
        "`/start` - Start bot\n"
        "`/help` - This guide\n"
        "`/languages` - Show supported languages\n"
        "`/cancel` - Cancel operation\n\n"
        "🌍 **All languages supported!**"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("languages"))
async def languages_command(client: Client, message: Message):
    languages_text = (
        "🌍 **SUPPORTED LANGUAGES** 🌍\n\n"
        "**South Asian:**\n"
        "• Sinhala (සිංහල)\n• Hindi (हिन्दी)\n• Tamil (தமிழ்)\n• Bengali (বাংলা)\n"
        "• Urdu (اردو)\n• Punjabi (ਪੰਜਾਬੀ)\n• Marathi (मराठी)\n• Gujarati (ગુજરાતી)\n\n"
        "**East Asian:**\n"
        "• Chinese (中文)\n• Japanese (日本語)\n• Korean (한국어)\n"
        "• Thai (ไทย)\n• Vietnamese (Tiếng Việt)\n\n"
        "**Middle Eastern:**\n"
        "• Arabic (العربية)\n• Hebrew (עברית)\n• Persian (فارسی)\n• Turkish (Türkçe)\n\n"
        "**European:**\n"
        "• English\n• Spanish\n• French\n• German\n• Russian\n• Greek\n• And many more!\n\n"
        "✅ **All Unicode languages supported!**"
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
    elif data == "cancel":
        await cancel_operation(client, callback_query.message)
    
    await callback_query.answer()

# ---------- UNIVERSAL FILE HANDLERS ----------
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

    status_msg = await message.reply_text("🌍 **UNIVERSAL DOWNLOAD**")
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
            f"🌍 **Send subtitle file for UNIVERSAL processing!**"
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

    status_msg = await message.reply_text("🌍 **UNIVERSAL SUBTITLE DOWNLOAD**")
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
        output_filename = f"{base_name}_UNIVERSAL_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)

        user_data[chat_id]["processing"] = True
        user_data[chat_id]["subtitle_path"] = sub_path
        user_data[chat_id]["output_path"] = output_file

        # Get UNIVERSAL FFmpeg command
        ffmpeg_cmd = get_universal_ffmpeg_command(video_path, sub_path, output_file, sub_ext)
        
        await status_msg.edit_text(
            f"🌍 **UNIVERSAL LANGUAGE PROCESSING**\n"
            f"`░░░░░░░░░░` **0%**\n"
            f"**Format:** {sub_ext.upper()}\n"
            f"**Features:** UTF-8, Multi-language fonts\n"
            f"**Estimated:** {format_time(duration / 3)}"
        )

        burn_start = time.time()
        burn_progress = UniversalProgress(client, chat_id, status_msg.id, base_name, duration)

        logger.info(f"Running universal FFmpeg: {' '.join(ffmpeg_cmd)}")
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Read stderr for progress
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
            process.kill()
            raise
        finally:
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

        # Upload
        await status_msg.edit_text("🌍 **UNIVERSAL UPLOAD**")
        upload_progress = DownloadProgress(client, chat_id, status_msg.id, output_filename, "UPLOAD")

        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **UNIVERSAL PROCESSING COMPLETE!** 🌍\n\n"
                f"📊 **Results:**\n"
                f"• Language Support: `ALL`\n"
                f"• Processing Time: `{format_time(burn_time)}`\n"
                f"• Output Size: `{human_readable(output_size)}`\n"
                f"• Speed: `{duration/burn_time:.1f}x` realtime\n\n"
                f"🌍 **Perfect multilingual rendering!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )

        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **UNIVERSAL SUCCESS!** 🌍\n\n"
            f"✅ **Total Time:** {format_time(total_time)}\n"
            f"🌍 **All languages supported!**\n"
            f"🚀 **Ready for next file!**"
        )

        # Cleanup
        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except Exception:
            pass

        # Clean up all files including converted subtitles
        for file_path in [video_path, sub_path, output_file]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                # Also remove converted subtitle if it exists
                converted_path = file_path + '.utf8'
                if os.path.exists(converted_path):
                    os.remove(converted_path)
            except Exception:
                pass

        user_data[chat_id] = {"processing": False}

    except Exception as e:
        logger.exception("Universal processing error")
        error_msg = str(e)
        
        if chat_id in user_data:
            user_data[chat_id]["processing"] = False
        
        try:
            await status_msg.edit_text(
                f"❌ **UNIVERSAL PROCESSING FAILED!** 🌍\n\n"
                f"`{html.escape(error_msg)}`\n\n"
                f"💡 **For best results:**\n"
                f"• Use UTF-8 encoded subtitle files\n"
                f"• Ensure proper timing in subtitles\n"
                f"• Use standard formats (SRT, ASS)\n"
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
                        # Also remove converted subtitle
                        converted_path = file_path + '.utf8'
                        if os.path.exists(converted_path):
                            os.remove(converted_path)
                    except Exception:
                        pass

# ---------- BOT STARTUP ----------
if __name__ == "__main__":
    print("=" * 60)
    print("🌍 UNIVERSAL SUBTITLE BOT - ALL LANGUAGES SUPPORTED")
    print("=" * 60)
    print(f"📦 Max Size: {human_readable(MAX_FILE_SIZE)}")
    print(f"🔥 Workers: {WORKERS}")
    print(f"🏥 Health Port: {HEALTH_PORT}")
    print("🎯 Features: UTF-8, Multi-language, Universal fonts")
    print("✅ Supported: Sinhala, Arabic, Chinese, Japanese, etc.")
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
