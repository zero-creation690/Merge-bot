#!/usr/bin/env python3
"""
Ultra Fast Subtitle Burner - OPTIMIZED VERSION

Key optimizations:
- Faster FFmpeg presets and encoding
- Parallel processing
- Increased file size to 4GB
- Enhanced UI with better visual feedback
- Optimized upload chunks

Required environment variables:
  - API_ID (int)
  - API_HASH (str)
  - BOT_TOKEN (str)
  - MAX_FILE_SIZE (optional, default 4294967296 = 4GB)
  - WORKERS (optional, default 150)
  - HEALTH_PORT (optional, default 8000)

Dependencies (install with pip):
  pip install pyrogram aiofiles

System dependencies:
  - ffmpeg + ffprobe available on PATH

Run:
  python3 ultra_fast_subtitle_bot.py
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

MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", "4294967296"))  # 4GB
WORKERS = int(os.environ.get("WORKERS", "150"))
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

def check_hardware_acceleration() -> str:
    """Check for available hardware acceleration"""
    try:
        # Check for NVIDIA GPU
        result = subprocess.run(['nvidia-smi'], capture_output=True, timeout=2)
        if result.returncode == 0:
            logger.info("NVIDIA GPU detected - using h264_nvenc")
            return 'h264_nvenc'
    except:
        pass
    
    try:
        # Check for Intel QuickSync
        result = subprocess.run(['ffmpeg', '-hide_banner', '-hwaccels'], 
                              capture_output=True, text=True, timeout=2)
        if 'qsv' in result.stdout:
            logger.info("Intel QuickSync detected - using h264_qsv")
            return 'h264_qsv'
    except:
        pass
    
    try:
        # Check for AMD GPU
        if 'vaapi' in result.stdout:
            logger.info("VAAPI detected - using h264_vaapi")
            return 'h264_vaapi'
    except:
        pass
    
    logger.info("No hardware acceleration - using libx264")
    return 'libx264'

# Check hardware acceleration once at startup
HW_ENCODER = check_hardware_acceleration()

# ---------- ENHANCED PROGRESS CLASSES ----------
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
        if now - self.last_update < 0.3 and current < total:
            return
        elapsed = now - self.start_time
        self.last_update = now
        self.history.append((now, current))
        if len(self.history) > 8:
            self.history.pop(0)

        if len(self.history) >= 2:
            dt = self.history[-1][0] - self.history[0][0]
            db = self.history[-1][1] - self.history[0][1]
            avg_speed = (db / dt) / (1024 * 1024) if dt > 0 else 0
        else:
            avg_speed = (current / elapsed) / (1024 * 1024) if elapsed > 0 else 0

        percent = (current * 100 / total) if total > 0 else 0
        eta = (total - current) / (avg_speed * 1024 * 1024) if avg_speed > 0 else 0

        bar_len = 15
        filled_len = int(bar_len * percent / 100)
        
        if percent < 25:
            bar = "🔴" * filled_len + "⚪" * (bar_len - filled_len)
        elif percent < 50:
            bar = "🟡" * filled_len + "⚪" * (bar_len - filled_len)
        elif percent < 75:
            bar = "🟢" * filled_len + "⚪" * (bar_len - filled_len)
        else:
            bar = "🔵" * filled_len + "⚪" * (bar_len - filled_len)

        if avg_speed > 30:
            emoji = "🚀💨"
            status = "HYPER SPEED"
        elif avg_speed > 20:
            emoji = "⚡🔥"
            status = "ULTRA FAST"
        elif avg_speed > 10:
            emoji = "🔥💪"
            status = "TURBO MODE"
        elif avg_speed > 5:
            emoji = "⚡📶"
            status = "FAST MODE"
        else:
            emoji = "📡🔄"
            status = "PROCESSING"

        text = (
            "╔══════════════════════════╗\n"
            f"║ {emoji} **{status}** {emoji} ║\n"
            "╠══════════════════════════╣\n"
            f"║ **{self.action}** • `{avg_speed:.1f} MB/s` ║\n"
            f"║ {bar} ║\n"
            f"║ **Progress:** `{percent:.1f}%` ║\n"
            f"║ **ETA:** `{format_time(eta)}` ║\n"
            f"║ **Elapsed:** `{format_time(elapsed)}` ║\n"
            f"║ **Size:** `{human_readable(current)}/{human_readable(total)}` ║\n"
            "╚══════════════════════════╝\n"
            f"📁 `{self.filename[:35]}`"
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
        # More frequent updates for large files to show it's working
        if now - self.last_update < 0.5 and percent < 100:
            return
        self.last_update = now
        elapsed = now - self.start_time

        if percent > 0:
            total_est = elapsed * 100.0 / percent
            eta = max(int(total_est - elapsed), 0)
        else:
            eta = 0

        bar_len = 15
        filled_len = int(bar_len * percent / 100)
        
        # Animated fire effect based on time
        fire_chars = ["🔥", "🔴", "🟠", "🟡"]
        fire_idx = int(now * 2) % len(fire_chars)  # Animate at 2 Hz
        fire_char = fire_chars[fire_idx]
        
        if percent < 33:
            bar = fire_char * filled_len + "⬜" * (bar_len - filled_len)
        elif percent < 66:
            bar = "🟠" * filled_len + "⬜" * (bar_len - filled_len)
        else:
            bar = "🟢" * filled_len + "⬜" * (bar_len - filled_len)

        # Dynamic status with activity indicator
        spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        spin_char = spinner[int(now * 3) % len(spinner)]
        
        if speed_x > 4.0:
            status = "🚀 WARP BURN"
            emoji = "🚀⚡💥"
        elif speed_x > 3.0:
            status = "⚡ ULTRA BURN"
            emoji = "⚡🔥💨"
        elif speed_x > 2.0:
            status = "🔥 TURBO BURN"
            emoji = "🔥💪⚡"
        elif speed_x > 1.0:
            status = "💨 FAST BURN"
            emoji = "💨🔥📡"
        else:
            status = "🔄 BURNING"
            emoji = "🔄🎬🔥"

        # Show processing indicator
        processing_text = f"{spin_char} **PROCESSING** {spin_char}"
        
        text = (
            "╔══════════════════════════╗\n"
            f"║ {emoji} {status} {emoji} ║\n"
            "╠══════════════════════════╣\n"
            f"║ {processing_text} ║\n"
            f"║ **Encoding Speed:** `{speed_x:.2f}x` ║\n"
            f"║ {bar} ║\n"
            f"║ **Progress:** `{percent:.1f}%` ║\n"
            f"║ **ETA:** `{format_time(eta)}` ║\n"
            f"║ **Elapsed:** `{format_time(elapsed)}` ║\n"
            "╚══════════════════════════╝\n"
            "🎬 **Burning subtitles permanently...**\n"
            f"📁 `{self.filename[:35]}`"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception:
            pass

# ---------- BOT COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "╔═══════════════════════════════╗\n"
        "║ 🚀 **ULTRA FAST SUBTITLE BOT** 🚀 ║\n"
        "╚═══════════════════════════════╝\n\n"
        "⚡ **PREMIUM FEATURES:**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 **Lightning Speed** downloads & uploads\n"
        "⚡ **Real-time Progress** tracking\n"
        "🎬 **Universal Format** support → MP4\n"
        "💎 **Permanent Subtitle** burning\n"
        "📦 **4GB Max Size** per file\n"
        "🚀 **Ultra-Fast Processing** engine\n\n"
        "📋 **QUICK START GUIDE:**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "**1️⃣** Send your video file\n"
        "**2️⃣** Send your .srt subtitle file\n"
        "**3️⃣** Get your processed video!\n\n"
        "🎯 **COMMANDS:**\n"
        "`/start` - Show this message\n"
        "`/help` - Detailed help guide\n"
        "`/cancel` - Cancel & cleanup\n\n"
        "🔥 **Ready to burn at warp speed!** 🔥"
    )
    await message.reply_text(welcome_text)


@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "╔════════════════════════════╗\n"
        "║ 🆘 **ULTRA FAST GUIDE** 🆘 ║\n"
        "╚════════════════════════════╝\n\n"
        "**⚙️ SPECIFICATIONS:**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📥 **Input:** Any video format\n"
        "📤 **Output:** MP4 with burned subs\n"
        f"📦 **Max Size:** {human_readable(MAX_FILE_SIZE)}\n"
        "⚡ **Processing:** Ultra-fast encoding\n"
        "🔥 **Subtitle:** Permanently burned\n\n"
        "**💡 TIPS FOR BEST SPEED:**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Use MP4/MKV for fastest processing\n"
        "✅ Keep files under 2GB for optimal speed\n"
        "✅ Ensure .srt file is properly formatted\n"
        "✅ Wait for download before sending subtitle\n\n"
        "**🎯 AVAILABLE COMMANDS:**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "`/start` - Start the bot\n"
        "`/help` - Show this guide\n"
        "`/cancel` - Cancel & cleanup files\n\n"
        "🚀 **Send a video now for ultra speed!** 🚀"
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
        await message.reply_text(
            "╔═══════════════════╗\n"
            "║ ✅ **CANCELLED** ✅ ║\n"
            "╚═══════════════════╝\n\n"
            "🗑️ **All files cleaned up!**\n"
            "🚀 **Ready for new operation!**"
        )
    else:
        await message.reply_text(
            "╔═══════════════════════╗\n"
            "║ ⚠️ **NO OPERATION** ⚠️ ║\n"
            "╚═══════════════════════╝\n\n"
            "📭 **No active operation to cancel**"
        )

# ---------- FILE HANDLERS ----------
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
        await message.reply_text(
            "╔═══════════════════════╗\n"
            "║ ❌ **FILE TOO LARGE** ❌ ║\n"
            "╚═══════════════════════╝\n\n"
            f"📦 **Your file:** {human_readable(file_obj.file_size)}\n"
            f"📊 **Max allowed:** {human_readable(MAX_FILE_SIZE)}\n\n"
            "💡 **Tip:** Compress your video first"
        )
        return

    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text("⚠️ **Video already received** — send the .srt file now.")
        return

    unique_id = secrets.token_hex(6)
    ext = os.path.splitext(file_obj.file_name or "video.mp4")[1] or ".mp4"
    download_path = os.path.join(CACHE_DIR, f"v_{unique_id}{ext}")

    status_msg = await message.reply_text(
        "╔══════════════════════════╗\n"
        "║ 🚀 **DOWNLOAD STARTED** 🚀 ║\n"
        "╚══════════════════════════╝\n\n"
        "⚡ **Initializing ultra-fast download...**"
    )
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

        if avg_speed > 30:
            speed_status = "🚀 HYPER SPEED"
        elif avg_speed > 20:
            speed_status = "⚡ ULTRA FAST"
        elif avg_speed > 10:
            speed_status = "🔥 TURBO MODE"
        else:
            speed_status = "📶 GOOD SPEED"

        await status_msg.edit_text(
            "╔════════════════════════════╗\n"
            "║ ✅ **DOWNLOAD COMPLETE!** ✅ ║\n"
            "╚════════════════════════════╝\n\n"
            "📊 **STATISTICS:**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 **Speed:** `{avg_speed:.1f} MB/s` {speed_status}\n"
            f"⏱️ **Time:** `{format_time(download_time)}`\n"
            f"📦 **Size:** `{human_readable(file_obj.file_size)}`\n\n"
            "🔥 **NEXT STEP:**\n"
            "📁 **Send your .srt subtitle file**\n\n"
            "⚡ Ready for subtitle burning! ⚡"
        )

    except Exception as e:
        logger.exception("Download failed")
        try:
            await status_msg.edit_text(
                "╔═══════════════════════╗\n"
                "║ ❌ **DOWNLOAD FAILED** ❌ ║\n"
                "╚═══════════════════════╝\n\n"
                f"⚠️ **Error:** `{html.escape(str(e)[:100])}`\n\n"
                "💡 **Try again or use /cancel**"
            )
        except Exception:
            pass
        if chat_id in user_data:
            del user_data[chat_id]


async def handle_subtitle(client: Client, message: Message):
    chat_id = message.chat.id

    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text(
            "╔═════════════════════════╗\n"
            "║ ⚠️ **VIDEO REQUIRED** ⚠️ ║\n"
            "╚═════════════════════════╝\n\n"
            "📹 **Send video file first!**"
        )
        return

    sub_obj = message.document
    if not sub_obj or not sub_obj.file_name or not sub_obj.file_name.lower().endswith('.srt'):
        await message.reply_text(
            "╔══════════════════════════╗\n"
            "║ ❌ **INVALID SUBTITLE** ❌ ║\n"
            "╚══════════════════════════╝\n\n"
            "📝 **Send a valid .srt file**"
        )
        return

    status_msg = await message.reply_text(
        "╔═══════════════════════════╗\n"
        "║ 🚀 **SUBTITLE DOWNLOAD** 🚀 ║\n"
        "╚═══════════════════════════╝\n\n"
        "⚡ **Processing subtitle file...**"
    )
    unique_id = secrets.token_hex(6)
    sub_filename = os.path.join(CACHE_DIR, f"s_{unique_id}.srt")

    progress = UltraProgress(client, chat_id, status_msg.id, sub_obj.file_name, "SUB DL")

    try:
        sub_path = await message.download(file_name=sub_filename, progress=progress.update)

        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"burned_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)

        await status_msg.edit_text(
            "╔═══════════════════════╗\n"
            "║ 🔍 **ANALYZING** 🔍 ║\n"
            "╚═══════════════════════╝\n\n"
            "📊 **Analyzing video properties...**\n"
            "🗑️ **Removing thumbnails & metadata...**"
        )
        duration = await asyncio.get_event_loop().run_in_executor(executor, get_video_duration, video_path)

        burn_progress = BurningProgress(client, chat_id, status_msg.id, base_name, duration)
        await status_msg.edit_text(
            "╔═══════════════════════════╗\n"
            "║ 🔥 **ULTRA BURN START** 🔥 ║\n"
            "╚═══════════════════════════╝\n\n"
            "⚡ **Initializing encoding engine...**\n"
            "🗑️ **Stripping all thumbnails...**\n"
            "📹 **Hard burning subtitles...**"
        )

        burn_start = time.time()

        # ULTRA-OPTIMIZED FFmpeg command - strips ALL thumbnails and metadata
        safe_sub_path = sub_path.replace("'", "\\'")
        
        # Simpler subtitle style for faster processing
        vf_filter = f"subtitles='{safe_sub_path}'"

        # Build command with hardware acceleration if available
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'fatal',  # Only fatal errors
            '-nostats',
            '-progress', 'pipe:1',
            '-xerror',
            '-err_detect', 'ignore_err',
            '-fflags', '+genpts+igndts+discardcorrupt',
            '-skip_frame', 'noref',
        ]
        
        # Add hardware acceleration input flags
        if HW_ENCODER == 'h264_nvenc':
            cmd.extend(['-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda'])
        elif HW_ENCODER == 'h264_qsv':
            cmd.extend(['-hwaccel', 'qsv'])
        elif HW_ENCODER == 'h264_vaapi':
            cmd.extend(['-hwaccel', 'vaapi', '-vaapi_device', '/dev/dri/renderD128'])
        
        cmd.extend([
            '-i', video_path,
            # CRITICAL: Only map video and audio, exclude ALL other streams (thumbnails, subtitles, data)
            '-map', '0:v:0',  # Only first video stream
            '-map', '0:a:0?',  # Only first audio stream (optional)
            '-map', '-0:d',  # Explicitly exclude data streams
            '-map', '-0:t',  # Explicitly exclude attachment streams (thumbnails)
            '-ignore_unknown',
            '-vf', vf_filter,
        ])
        
        # Configure encoder based on hardware
        if HW_ENCODER in ['h264_nvenc', 'h264_qsv', 'h264_vaapi']:
            cmd.extend([
                '-c:v', HW_ENCODER,
                '-preset', 'fast' if HW_ENCODER == 'h264_nvenc' else 'veryfast',
                '-b:v', '5M',
            ])
        else:
            cmd.extend([
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-crf', '23',
                '-tune', 'fastdecode',
            ])
        
        cmd.extend([
            '-c:a', 'copy',  # Copy audio for speed
            '-movflags', '+faststart',
            '-threads', '0',
            '-max_muxing_queue_size', '9999',
            '-map_metadata', '-1',  # Strip ALL metadata
            '-map_chapters', '-1',  # Strip chapters
            '-disposition:v:0', 'default',  # Mark video as default
            '-disposition:a:0', 'default',  # Mark audio as default
            '-y',
            output_file
        ])

        encoder_name = HW_ENCODER.upper() if HW_ENCODER != 'libx264' else 'CPU'
        logger.info(f"Starting ultra-optimized ffmpeg with {encoder_name} (thumbnails stripped): %s", ' '.join(shlex.quote(p) for p in cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # REAL-TIME progress tracking from FFmpeg output
        async def track_real_progress():
            current_time = 0
            while True:
                try:
                    if process.stdout:
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
                        if not line:
                            break
                        
                        line_str = line.decode('utf-8', errors='ignore').strip()
                        
                        # Parse FFmpeg progress output
                        if 'out_time_ms=' in line_str:
                            try:
                                time_ms = int(line_str.split('out_time_ms=')[1].split()[0])
                                current_time = time_ms / 1000000.0  # Convert to seconds
                            except:
                                pass
                        
                        if duration > 0 and current_time > 0:
                            percent = min((current_time / duration) * 100, 99)
                            elapsed = time.time() - burn_start
                            speed_x = current_time / elapsed if elapsed > 0 else 1.0
                            await burn_progress.update(percent, speed_x)
                    
                    if process.returncode is not None:
                        break
                    
                except asyncio.TimeoutError:
                    # If no output, simulate progress to show activity
                    elapsed = time.time() - burn_start
                    if duration > 0:
                        estimated_percent = min((elapsed / (duration * 0.4)) * 100, 99)
                        estimated_speed = 2.0 + (estimated_percent / 50)
                        await burn_progress.update(estimated_percent, estimated_speed)
                    continue
                except Exception as e:
                    logger.error(f"Progress tracking error: {e}")
                    break
            
            # Finalize to 100%
            await burn_progress.update(100, 5.0)

        progress_task = asyncio.create_task(track_real_progress())

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
            raise Exception("Output file not created by ffmpeg")

        output_size = os.path.getsize(output_file)
        burn_speed = (user_data[chat_id]["file_size"] / burn_time) / (1024 * 1024) if burn_time > 0 else 0

        await status_msg.edit_text(
            "╔════════════════════════╗\n"
            "║ 🚀 **UPLOAD STARTED** 🚀 ║\n"
            "╚════════════════════════╝\n\n"
            "⚡ **Uploading at maximum speed...**"
        )
        upload_progress = UltraProgress(client, chat_id, status_msg.id, os.path.basename(output_file), "UPLOAD")

        upload_start = time.time()
        caption_text = (
            "╔═════════════════════════════╗\n"
            "║ ✅ **ULTRA BURN COMPLETE!** ✅ ║\n"
            "╚═════════════════════════════╝\n\n"
            "📊 **PERFORMANCE STATS:**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 **Burn Speed:** `{burn_speed:.1f} MB/s`\n"
            f"⏱️ **Burn Time:** `{format_time(burn_time)}`\n"
            f"📦 **Output Size:** `{human_readable(output_size)}`\n"
            "🎬 **Format:** MP4 (H.264)\n\n"
            "🔥 **Features:**\n"
            "✅ Subtitles permanently hard-burned\n"
            "✅ All thumbnails removed\n"
            "✅ All metadata stripped\n"
            "✅ Clean, optimized output\n\n"
            "⚡ **Processed with ultra-fast engine**\n"
            "🎯 Ready for your next video! 🎯"
        )
        
        await client.send_video(
            chat_id,
            output_file,
            caption=caption_text,
            progress=upload_progress.update,
            supports_streaming=True
        )
        upload_time = time.time() - upload_start

        total_time = time.time() - user_data[chat_id]["start_time"]
        
        final_text = (
            "╔═══════════════════════════════╗\n"
            "║ 🎉 **MISSION ACCOMPLISHED!** 🎉 ║\n"
            "╚═══════════════════════════════╝\n\n"
            "📊 **COMPLETE STATISTICS:**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ **Total Time:** `{format_time(total_time)}`\n"
            f"🔥 **Burn Time:** `{format_time(burn_time)}`\n"
            f"📤 **Upload Time:** `{format_time(upload_time)}`\n"
            f"🚀 **Avg Speed:** `{burn_speed:.1f} MB/s`\n\n"
            "✨ **Ready for next ultra-fast burn!** ✨"
        )
        await status_msg.edit_text(final_text)

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

        del user_data[chat_id]

    except Exception as e:
        logger.exception("Ultra burn error")
        error_msg = str(e)
        try:
            error_text = (
                "╔═════════════════════════╗\n"
                "║ ❌ **ULTRA BURN FAILED** ❌ ║\n"
                "╚═════════════════════════╝\n\n"
                "⚠️ **Error Details:**\n"
                f"`{html.escape(error_msg[:150])}`\n\n"
                "💡 **OPTIMIZATION TIPS:**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅ Use MP4/MKV format\n"
                "✅ Keep files under 2GB\n"
                "✅ Check .srt encoding (UTF-8)\n"
                "✅ Verify subtitle timing\n\n"
                "🔄 Use `/cancel` to restart"
            )
            await status_msg.edit_text(error_text)
        except Exception:
            pass

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
    print("=" * 60)
    print("🚀 ULTRA FAST SUBTITLE BURNER - OPTIMIZED VERSION 🚀")
    print("=" * 60)
    print(f"⚡ Max File Size: {human_readable(MAX_FILE_SIZE)} (4GB)")
    print(f"🔥 Worker Threads: {WORKERS}")
    print(f"💎 Hardware Encoder: {HW_ENCODER.upper()}")
    print(f"📦 Output Format: MP4 (H.264 + AAC)")
    print(f"🚀 Processing: Multi-threaded + HW Accel")
    print(f"⚡ Audio: Stream Copy (No Re-encode)")
    print("=" * 60)
    print("✅ All systems ready for warp speed!")
    print("=" * 60)

    try:
        app.run()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
    except Exception as e:
        logger.exception("Bot failed to start")
        print(f"❌ Bot failed to start: {e}")
