#!/usr/bin/env python3
"""
Ultra Fast Subtitle Burner - SPEED OPTIMIZED
Uses hardware acceleration and optimized settings for maximum speed
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
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/ultra_bot")
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
    "UltraFastBot",
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

def get_video_codec(file_path: str) -> str:
    """Get video codec to determine if we can use copy"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Could not get video codec: {e}")
    return "h264"

def check_hardware_acceleration():
    """Check available hardware acceleration"""
    try:
        # Check for NVIDIA
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            return "nvidia"
        
        # Check for VAAPI
        result = subprocess.run(['vainfo'], capture_output=True, text=True)
        if result.returncode == 0:
            return "vaapi"
            
        # Check for QSV
        result = subprocess.run(['ls', '/dev/dri'], capture_output=True, text=True)
        if 'render' in result.stdout:
            return "qsv"
            
    except Exception:
        pass
    return "software"

def sanitize_filename(filename: str) -> str:
    return re.sub(r'[^\w\-_. ]', '', filename)

# ---------- OPTIMIZED FFMPEG COMMANDS ----------
def get_optimized_ffmpeg_command(video_path: str, subtitle_path: str, output_path: str, sub_ext: str, duration: float):
    """Get optimized FFmpeg command based on available hardware"""
    hw_accel = check_hardware_acceleration()
    logger.info(f"Using hardware acceleration: {hw_accel}")
    
    base_cmd = ['ffmpeg', '-hide_banner', '-y']
    
    # Input options for speed
    base_cmd.extend(['-i', video_path])
    
    # Subtitle filter
    if sub_ext == '.ass':
        vf_filter = f"ass={shlex.quote(subtitle_path)}"
    else:
        vf_filter = f"subtitles={shlex.quote(subtitle_path)}"
    
    # VIDEO ENCODING OPTIMIZATIONS
    if hw_accel == "nvidia":
        # NVIDIA NVENC - fastest hardware encoding
        base_cmd.extend([
            '-vf', vf_filter,
            '-c:v', 'h264_nvenc',
            '-preset', 'p1',  # fastest nvenc preset
            '-rc', 'constqp',
            '-qp', '23',
            '-b:v', '0',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart'
        ])
    elif hw_accel == "vaapi":
        # VAAPI hardware encoding
        base_cmd.extend([
            '-vaapi_device', '/dev/dri/renderD128',
            '-vf', f'format=nv12,hwupload,{vf_filter}',
            '-c:v', 'h264_vaapi',
            '-global_quality', '23',
            '-c:a', 'aac',
            '-b:a', '128k'
        ])
    elif hw_accel == "qsv":
        # Intel Quick Sync
        base_cmd.extend([
            '-vf', f'format=nv12,hwupload=extra_hw_frames=64,{vf_filter}',
            '-c:v', 'h264_qsv',
            '-preset', 'veryfast',
            '-global_quality', '23',
            '-c:a', 'aac',
            '-b:a', '128k'
        ])
    else:
        # SOFTWARE ENCODING - ULTRA FAST SETTINGS
        base_cmd.extend([
            '-vf', vf_filter,
            '-c:v', 'libx264',
            '-preset', 'ultrafast',  # Fastest software preset
            '-crf', '28',  # Slightly higher CRF for speed
            '-tune', 'fastdecode',  # Optimize for decoding speed
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-threads', '0'  # Use all available threads
        ])
    
    # For very long videos, use faster settings
    if duration > 600:  # Longer than 10 minutes
        if hw_accel == "software":
            base_cmd.extend(['-preset', 'ultrafast', '-crf', '30'])
        logger.info("Using ultra-fast settings for long video")
    
    base_cmd.append(output_path)
    return base_cmd

# ---------- PROGRESS TRACKING ----------
class RealBurningProgress:
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
                percent = self.last_percent + 0.1  # Incremental fallback

            # Only update if significant change or every 10 seconds
            if (percent - self.last_percent >= 2) or (now - self.last_update >= 10):
                await self.update_display(percent, current_time)
                self.last_percent = percent
                self.last_update = now

    async def update_display(self, percent: float, current_time: float):
        """Update the progress display"""
        elapsed = time.time() - self.start_time
        
        # Calculate real speed and ETA
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

        # Speed status with realistic expectations
        if speed_x > 5.0:
            status = "ULTRA BURN"
        elif speed_x > 2.0:
            status = "TURBO BURN"
        elif speed_x > 1.0:
            status = "FAST BURN"
        elif speed_x > 0.5:
            status = "NORMAL"
        elif speed_x > 0.2:
            status = "SLOW"
        else:
            status = "VERY SLOW"

        time_info = f"({format_time(current_time)}/{format_time(self.total_duration)})"

        text = (
            f"⚙️ **{status}** • **{speed_x:.1f}x**\n"
            f"`{bar}` **{percent:.1f}%** {time_info}\n"
            f"⏱️ **ETA:** `{eta}`\n"
            f"**Optimized encoding active...**"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception as e:
            logger.debug(f"Progress update failed: {e}")

    async def complete(self):
        """Mark as 100% complete"""
        total_time = time.time() - self.start_time
        text = (
            f"✅ **PROCESSING COMPLETE!**\n"
            f"`{'🔥' * 10}` **100%**\n"
            f"⏱️ **Encoding Time:** {format_time(total_time)}\n"
            f"**Finalizing output...**"
        )
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception:
            pass

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
    hw_accel = check_hardware_acceleration()
    welcome_text = (
        f"🚀 **ULTRA FAST SUBTITLE BOT** 🚀\n\n"
        f"⚡ **Hardware Acceleration:** `{hw_accel.upper()}`\n"
        f"• **Optimized for maximum speed**\n"
        f"• **Hardware encoding when available**\n"
        f"• **Real progress tracking**\n"
        f"• **SRT & ASS support**\n\n"
        f"📋 **How to use:**\n"
        f"1. Send video file\n"
        f"2. Send subtitle file\n"
        f"3. Get fast results!\n\n"
        f"🔥 **Optimized for speed!**"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Help", callback_data="help"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    hw_accel = check_hardware_acceleration()
    help_text = (
        "🆘 **SPEED OPTIMIZED GUIDE**\n\n"
        f"**Hardware:** {hw_accel.upper()}\n"
        "**Format:** Any → MP4\n"
        "**Subtitles:** SRT, ASS\n"
        "**Max Size:** {}\n\n".format(human_readable(MAX_FILE_SIZE)) +
        "**Speed Optimizations:**\n"
        "• Hardware encoding (NVENC/VAAPI/QSV)\n"
        "• Ultrafast software presets\n"
        "• Multi-threaded processing\n\n"
        "**Commands:**\n"
        "`/start` - Start bot\n"
        "`/help` - This guide\n"
        "`/cancel` - Cancel operation\n"
        "`/status` - Check bot status\n\n"
        "🚀 **Maximum speed optimization active!**"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("status"))
async def status_command(client: Client, message: Message):
    hw_accel = check_hardware_acceleration()
    active_with_progress = sum(1 for data in user_data.values() if data.get("processing"))
    status_text = (
        "🤖 **Bot Status**\n\n"
        f"**Hardware:** {hw_accel.upper()}\n"
        f"**Active Sessions:** {len(user_data)}\n"
        f"**Processing Now:** {active_with_progress}\n"
        f"**Max File Size:** {human_readable(MAX_FILE_SIZE)}\n"
        f"**Workers:** {WORKERS}\n\n"
        "✅ **Speed-optimized encoding active!**"
    )
    await message.reply_text(status_text)

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
    elif data == "cancel":
        await cancel_operation(client, callback_query.message)
    
    await callback_query.answer()

# ---------- OPTIMIZED FILE HANDLERS ----------
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

    if chat_id in user_data and "video_path" in user_data[chat_id]:
        await message.reply_text("⚠️ **Video already received** — send subtitle file (.srt or .ass).")
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

        duration = await asyncio.get_event_loop().run_in_executor(executor, get_video_duration, video_path)
        codec = await asyncio.get_event_loop().run_in_executor(executor, get_video_codec, video_path)

        user_data[chat_id] = {
            "video_path": video_path,
            "original_filename": safe_filename,
            "file_size": file_obj.file_size,
            "duration": duration,
            "codec": codec,
            "start_time": time.time(),
            "processing": False
        }

        await status_msg.edit_text(
            f"✅ **DOWNLOAD COMPLETE!**\n\n"
            f"📊 **Video Info:**\n"
            f"• Duration: `{format_time(duration)}`\n"
            f"• Codec: `{codec}`\n"
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
        duration = user_data[chat_id]["duration"]
        
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"{base_name}_burned_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)

        user_data[chat_id]["processing"] = True
        user_data[chat_id]["subtitle_path"] = sub_path
        user_data[chat_id]["output_path"] = output_file

        # Get optimized FFmpeg command
        ffmpeg_cmd = get_optimized_ffmpeg_command(video_path, sub_path, output_file, sub_ext, duration)
        
        hw_accel = check_hardware_acceleration()
        await status_msg.edit_text(
            f"🔥 **STARTING OPTIMIZED BURN**\n"
            f"`░░░░░░░░░░` **0%**\n"
            f"**Hardware:** {hw_accel.upper()}\n"
            f"**Estimated:** {format_time(duration / 2)}"
        )

        burn_start = time.time()
        burn_progress = RealBurningProgress(client, chat_id, status_msg.id, base_name, duration)

        logger.info(f"Running optimized FFmpeg: {' '.join(ffmpeg_cmd)}")
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
            raise Exception(f"Burn failed: {error_text[:200]}")

        if not os.path.exists(output_file):
            raise Exception("Output file not created")

        output_size = os.path.getsize(output_file)

        # Upload
        await status_msg.edit_text("🚀 **ULTRA UPLOAD STARTED**")
        upload_progress = UltraProgress(client, chat_id, status_msg.id, output_filename, "UPLOAD")

        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **OPTIMIZED PROCESSING COMPLETE!**\n\n"
                f"📊 **Results:**\n"
                f"• Encoding: `{hw_accel.upper()}`\n"
                f"• Total Time: `{format_time(burn_time)}`\n"
                f"• Output Size: `{human_readable(output_size)}`\n"
                f"• Speed: `{duration/burn_time:.1f}x` realtime\n\n"
                f"🔥 **Hardware-accelerated encoding!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )

        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **PROCESSING COMPLETE!**\n\n"
            f"✅ **Total Time:** {format_time(total_time)}\n"
            f"🚀 **Optimized encoding successful!**"
        )

        # Cleanup
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
        logger.exception("Processing error")
        error_msg = str(e)
        
        if chat_id in user_data:
            user_data[chat_id]["processing"] = False
        
        try:
            await status_msg.edit_text(
                f"❌ **PROCESSING FAILED!**\n\n"
                f"`{html.escape(error_msg)}`\n\n"
                f"💡 **Speed Tips:**\n"
                f"• Try shorter videos first\n"
                f"• Use MP4 format\n"
                f"• Lower resolution = faster\n"
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
    hw_accel = check_hardware_acceleration()
    print("=" * 60)
    print("🚀 ULTRA FAST SUBTITLE BOT - SPEED OPTIMIZED")
    print("=" * 60)
    print(f"⚡ Hardware Acceleration: {hw_accel.upper()}")
    print(f"📦 Max Size: {human_readable(MAX_FILE_SIZE)}")
    print(f"🔥 Workers: {WORKERS}")
    print(f"🏥 Health Port: {HEALTH_PORT}")
    print("🎯 Features: Hardware encoding, Speed optimization")
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
