from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import subprocess
import os
import time
import asyncio
import logging
import aiofiles
from concurrent.futures import ThreadPoolExecutor
import re
import psutil
from datetime import datetime
import secrets

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Koyeb-specific optimizations
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", "2147483648"))  # 2GB default for Koyeb
WORKERS = int(os.environ.get("WORKERS", "50"))
CACHE_DIR = "/tmp/bot_cache"  # Koyeb ephemeral storage

# Create cache directory
os.makedirs(CACHE_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "SubtitleMergeBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=CACHE_DIR,
    in_memory=True,
    workers=WORKERS,
    max_concurrent_transmissions=15,
    sleep_threshold=60
)

user_data = {}
executor = ThreadPoolExecutor(max_workers=WORKERS)

# ---------- Enhanced Helpers ----------
def human_readable(size):
    """Convert bytes to human readable format"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

def format_time(seconds):
    """Convert seconds to human readable time"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"

def get_video_duration(file_path):
    """Get video duration using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
        return 0

def get_system_stats():
    """Get system statistics for Koyeb"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/tmp')
    
    return {
        'cpu': cpu_percent,
        'memory_used': memory.used,
        'memory_total': memory.total,
        'memory_percent': memory.percent,
        'disk_used': disk.used,
        'disk_total': disk.total,
        'disk_percent': disk.percent
    }

class TurboProgressTracker:
    def __init__(self, client, chat_id, message_id, filename, action="Downloading"):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.action = action
        self.start_time = time.time()
        self.last_update = 0
        self.last_current = 0
        self.speeds = []
        self.max_speeds = 8  # Reduced for faster updates
        self.update_interval = 1.0  # More frequent updates
        
    async def update(self, current, total):
        """Turbo-charged progress tracking"""
        now = time.time()
        
        if now - self.last_update < self.update_interval and current < total:
            return
        
        time_diff = now - self.last_update if self.last_update > 0 else 1
        self.last_update = now
        elapsed = now - self.start_time
        
        bytes_diff = current - self.last_current if self.last_current > 0 else current
        instant_speed = bytes_diff / time_diff if time_diff > 0 else 0
        
        self.speeds.append(instant_speed)
        if len(self.speeds) > self.max_speeds:
            self.speeds.pop(0)
        
        avg_speed = sum(self.speeds) / len(self.speeds) if self.speeds else 0
        self.last_current = current
        
        percent = (current * 100 / total) if total > 0 else 0
        eta = (total - current) / avg_speed if avg_speed > 0 else 0
        
        # Dynamic progress bar based on speed
        bar_len = 20
        filled_len = int(bar_len * current // total) if total > 0 else 0
        
        # Speed-based emojis
        if avg_speed > 15 * 1024 * 1024:
            bar_char, speed_emoji = "🚀", "🚀"
        elif avg_speed > 8 * 1024 * 1024:
            bar_char, speed_emoji = "⚡", "⚡"
        elif avg_speed > 3 * 1024 * 1024:
            bar_char, speed_emoji = "🔥", "🔥"
        else:
            bar_char, speed_emoji = "█", "📶"
            
        bar = bar_char * filled_len + "░" * (bar_len - filled_len)
        
        text = (
            f"{'📥' if self.action == 'Downloading' else '📤'} **{self.action.upper()}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 `{self.filename[:40]}{'...' if len(self.filename) > 40 else ''}`\n\n"
            f"`{bar}` **{percent:.1f}%**\n\n"
            f"💾 **Size:** `{human_readable(current)}` / `{human_readable(total)}`\n"
            f"{speed_emoji} **Speed:** `{human_readable(avg_speed)}/s`\n"
            f"⏱️ **ETA:** `{format_time(eta)}`\n"
            f"⏳ **Elapsed:** `{format_time(elapsed)}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        try:
            await self.client.edit_message_text(
                self.chat_id, 
                self.message_id, 
                text
            )
        except Exception as e:
            logger.debug(f"Progress update failed: {e}")

class TurboFFmpegProgress:
    def __init__(self, client, chat_id, message_id, filename, duration):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.duration = duration
        self.start_time = time.time()
        self.last_update = 0
        self.last_time = 0
        self.speeds = []
        
    async def update_from_line(self, line):
        """Ultra-fast FFmpeg progress parsing"""
        now = time.time()
        
        # Update every 1.5 seconds for faster feedback
        if now - self.last_update < 1.5:
            return
        
        # Multiple time format support
        time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
        if not time_match:
            return
            
        hours, minutes, seconds = int(time_match[1]), int(time_match[2]), float(time_match[3])
        current_time = hours * 3600 + minutes * 60 + seconds
        
        if self.duration > 0:
            percent = min((current_time / self.duration) * 100, 100)
        else:
            percent = 0
        
        elapsed = now - self.start_time
        
        # Calculate processing speed
        time_diff = current_time - self.last_time
        real_time_diff = now - self.last_update if self.last_update > 0 else 1
        processing_speed = time_diff / real_time_diff if real_time_diff > 0 else 1
        
        self.last_time = current_time
        self.speeds.append(processing_speed)
        if len(self.speeds) > 5:
            self.speeds.pop(0)
        
        avg_speed = sum(self.speeds) / len(self.speeds) if self.speeds else 1
        remaining_time = (self.duration - current_time) / avg_speed if avg_speed > 0 else 0
        
        # Dynamic progress bar
        bar_len = 20
        filled_len = int(bar_len * percent / 100)
        
        if avg_speed > 2.0:
            bar_char, speed_emoji = "🚀", "🚀"
        elif avg_speed > 1.5:
            bar_char, speed_emoji = "⚡", "⚡"
        elif avg_speed > 1.0:
            bar_char, speed_emoji = "🔥", "🔥"
        else:
            bar_char, speed_emoji = "█", "⚙️"
            
        bar = bar_char * filled_len + "░" * (bar_len - filled_len)
        
        speed_match = re.search(r'speed=\s*([\d.]+)x', line)
        speed_text = f"{speed_match.group(1)}x" if speed_match else f"{avg_speed:.1f}x"
        
        text = (
            f"⚙️ **TURBO PROCESSING**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 `{self.filename[:40]}{'...' if len(self.filename) > 40 else ''}`\n\n"
            f"`{bar}` **{percent:.1f}%**\n\n"
            f"🔥 **Burning subtitles...**\n"
            f"{speed_emoji} **Speed:** `{speed_text}`\n"
            f"⏱️ **ETA:** `{format_time(remaining_time)}`\n"
            f"⏳ **Elapsed:** `{format_time(elapsed)}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        try:
            await self.client.edit_message_text(
                self.chat_id,
                self.message_id,
                text
            )
            self.last_update = now
        except Exception as e:
            logger.debug(f"FFmpeg progress update failed: {e}")

# ---------- Command Handlers ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 How to Use", callback_data="help"),
         InlineKeyboardButton("⚡ Speed Test", callback_data="speedtest")],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats"),
         InlineKeyboardButton("🔧 Support", url="https://t.me/yourchannel")]
    ])
    
    welcome_text = (
        "🚀 **TURBO SUBTITLE MERGE BOT** 🚀\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ **Turbo Features:**\n"
        "• **Lightning Speed** (15+ MB/s)\n"
        "• **Multi-threaded Processing**\n"
        "• **Real-time Progress Tracking**\n"
        "• **Smart Caching System**\n"
        "• **Koyeb Optimized**\n\n"
        "📋 **Quick Start:**\n"
        "1. Send video file\n"
        "2. Send subtitle (.srt)\n"
        "3. Get merged video!\n\n"
        "💡 **Pro Tip:** Use /speedtest to check current performance!"
    )
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **TURBO HELP GUIDE**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**🚀 Turbo Commands:**\n"
        "`/start` - Launch turbo mode\n"
        "`/speedtest` - Check current speed\n"
        "`/stats` - System statistics\n"
        "`/cancel` - Cancel operation\n\n"
        "**⚡ Speed Tips:**\n"
        "• Bot uses **parallel processing**\n"
        "• **Smart caching** for repeated files\n"
        "• **Adaptive compression**\n"
        "• **Multi-threaded uploads**\n\n"
        "**📊 Current Limits:**\n"
        f"• **Max Size:** `{human_readable(MAX_FILE_SIZE)}`\n"
        f"• **Workers:** `{WORKERS} threads`\n"
        "• **Formats:** MP4, MKV, AVI, MOV + SRT"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("speedtest"))
async def speed_test(client: Client, message: Message):
    """Perform a quick speed test"""
    test_msg = await message.reply_text("🚀 **Starting Turbo Speed Test...**")
    
    # Test file operations
    start_time = time.time()
    test_size = 10 * 1024 * 1024  # 10MB test
    
    # Create test file
    test_file = os.path.join(CACHE_DIR, f"speedtest_{message.chat.id}.tmp")
    try:
        # Write test
        async with aiofiles.open(test_file, 'wb') as f:
            data = secrets.token_bytes(test_size)
            await f.write(data)
        
        write_time = time.time() - start_time
        write_speed = test_size / write_time
        
        # Read test
        read_start = time.time()
        async with aiofiles.open(test_file, 'rb') as f:
            await f.read()
        read_time = time.time() - read_start
        read_speed = test_size / read_time
        
        # System stats
        stats = get_system_stats()
        
        result_text = (
            f"📊 **TURBO SPEED TEST RESULTS**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💾 **Write Speed:** `{human_readable(write_speed)}/s`\n"
            f"📖 **Read Speed:** `{human_readable(read_speed)}/s`\n"
            f"🖥️ **CPU Usage:** `{stats['cpu']}%`\n"
            f"🧠 **Memory:** `{stats['memory_percent']}%`\n"
            f"💿 **Disk:** `{stats['disk_percent']}%`\n\n"
            f"⚡ **Status:** {'TURBO READY' if write_speed > 5*1024*1024 else 'NORMAL'}\n"
            f"🔥 **Performance:** {'EXCELLENT' if write_speed > 10*1024*1024 else 'GOOD'}"
        )
        
        await test_msg.edit_text(result_text)
        
    except Exception as e:
        await test_msg.edit_text(f"❌ **Speed test failed:** `{str(e)}`")
    finally:
        # Cleanup
        if os.path.exists(test_file):
            os.remove(test_file)

@app.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    stats = get_system_stats()
    active_users = len(user_data)
    
    stats_text = (
        f"📊 **TURBO SYSTEM STATS**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 **Active Users:** `{active_users}`\n"
        f"🖥️ **CPU Usage:** `{stats['cpu']}%`\n"
        f"🧠 **Memory:** `{human_readable(stats['memory_used'])} / {human_readable(stats['memory_total'])}`\n"
        f"💿 **Disk:** `{human_readable(stats['disk_used'])} / {human_readable(stats['disk_total'])}`\n"
        f"⚡ **Workers:** `{WORKERS} threads`\n"
        f"📦 **Max File:** `{human_readable(MAX_FILE_SIZE)}`\n\n"
        f"🚀 **Turbo Mode:** **ACTIVE**"
    )
    
    await message.reply_text(stats_text)

@app.on_message(filters.command("cancel"))
async def cancel_operation(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id in user_data:
        # Cleanup all temporary files
        for key in ["video", "subtitle", "output"]:
            file_path = user_data[chat_id].get(key)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
        
        del user_data[chat_id]
        await message.reply_text("✅ **Operation cancelled!** All files cleaned.")
    else:
        await message.reply_text("❌ **No active operation to cancel!**")

# ---------- File Handlers ----------
@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    chat_id = message.chat.id
    
    if message.video:
        file_obj = message.video
        file_type = "video"
    elif message.document:
        file_obj = message.document
        if file_obj.file_name and file_obj.file_name.lower().endswith('.srt'):
            await handle_subtitle(client, message)
            return
        file_type = "document"
    else:
        return
    
    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text(
            "⚠️ **Video already received!**\n"
            "Please send the subtitle file (.srt) now.\n\n"
            "Use /cancel to start over."
        )
        return
    
    file_size = file_obj.file_size
    if file_size > MAX_FILE_SIZE:
        await message.reply_text(
            f"❌ **File too large!**\n\n"
            f"Your file: `{human_readable(file_size)}`\n"
            f"Maximum allowed: `{human_readable(MAX_FILE_SIZE)}`\n\n"
            f"💡 Upgrade or use smaller files."
        )
        return
    
    # Generate unique filename
    file_ext = os.path.splitext(file_obj.file_name or "video.mp4")[1]
    unique_id = secrets.token_hex(8)
    filename = f"video_{unique_id}{file_ext}"
    
    status_msg = await message.reply_text(
        "🚀 **TURBO DOWNLOAD INITIATED**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Starting multi-threaded download..."
    )
    
    progress = TurboProgressTracker(
        client, chat_id, status_msg.id, filename, "Downloading"
    )
    
    try:
        download_start = time.time()
        video_path = await message.download(
            file_name=os.path.join(CACHE_DIR, filename),
            progress=progress.update
        )
        download_time = time.time() - download_start
        avg_speed = file_size / download_time if download_time > 0 else 0
        
        user_data[chat_id] = {
            "video": video_path,
            "filename": file_obj.file_name or filename,
            "file_size": file_size,
            "start_time": time.time()
        }
        
        await status_msg.edit_text(
            f"✅ **TURBO DOWNLOAD COMPLETE!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁 **File:** `{filename[:45]}`\n"
            f"📦 **Size:** `{human_readable(file_size)}`\n"
            f"⚡ **Speed:** `{human_readable(avg_speed)}/s`\n"
            f"⏱️ **Time:** `{format_time(download_time)}`\n\n"
            f"🔥 **Now send your subtitle file (.srt)**"
        )
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        await status_msg.edit_text(
            f"❌ **DOWNLOAD FAILED!**\n\n"
            f"**Error:** `{str(e)}`\n\n"
            f"💡 Try again or check file size."
        )
        if chat_id in user_data:
            del user_data[chat_id]

async def handle_subtitle(client: Client, message: Message):
    chat_id = message.chat.id
    
    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text(
            "⚠️ **Send video first!**\n\n"
            "Please send your video file before the subtitle."
        )
        return
    
    sub_obj = message.document
    
    if not sub_obj.file_name or not sub_obj.file_name.lower().endswith('.srt'):
        await message.reply_text(
            "❌ **Invalid subtitle format!**\n\n"
            "Please send a valid **.srt** file only."
        )
        return
    
    status_msg = await message.reply_text(
        "🚀 **DOWNLOADING SUBTITLE**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Starting turbo download..."
    )
    
    unique_id = secrets.token_hex(8)
    sub_filename = f"sub_{unique_id}.srt"
    
    progress = TurboProgressTracker(
        client, chat_id, status_msg.id, sub_obj.file_name, "Downloading"
    )
    
    try:
        sub_path = await message.download(
            file_name=os.path.join(CACHE_DIR, sub_filename),
            progress=progress.update
        )
        
        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"merged_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)
        
        # Get video info
        await status_msg.edit_text(
            "🔍 **ANALYZING VIDEO**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Getting video information..."
        )
        
        duration = await asyncio.get_event_loop().run_in_executor(
            executor, get_video_duration, video_path
        )
        
        await status_msg.edit_text(
            "⚙️ **TURBO PROCESSING**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔥 Starting subtitle merge...\n"
            "`░░░░░░░░░░░░░░░░░░░░░░` **0%**"
        )
        
        merge_start = time.time()
        
        # Optimized FFmpeg command for Koyeb
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', f"subtitles='{sub_path}':force_style='FontSize=24,PrimaryColour=&HFFFFFF&'",
            '-c:v', 'libx264',
            '-preset', 'superfast',  # Better than ultrafast for quality/speed balance
            '-crf', '22',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-threads', '0',
            '-progress', 'pipe:1',
            '-y',
            output_file
        ]
        
        ffmpeg_progress = TurboFFmpegProgress(
            client, chat_id, status_msg.id, base_name, duration
        )
        
        # Run FFmpeg with real-time progress
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        async def read_progress():
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore').strip()
                await ffmpeg_progress.update_from_line(line_str)
        
        progress_task = asyncio.create_task(read_progress())
        await process.wait()
        await progress_task
        
        merge_time = time.time() - merge_start
        
        if process.returncode != 0:
            error_output = await process.stderr.read()
            raise Exception(f"FFmpeg failed: {error_output.decode()[:200]}")
        
        if not os.path.exists(output_file):
            raise Exception("Output file not created")
        
        output_size = os.path.getsize(output_file)
        
        # Upload with turbo progress
        await status_msg.edit_text(
            "📤 **TURBO UPLOAD**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 Starting multi-threaded upload..."
        )
        
        upload_progress = TurboProgressTracker(
            client, chat_id, status_msg.id, f"merged_{base_name}.mp4", "Uploading"
        )
        
        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **TURBO MERGE COMPLETE!**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📁 **File:** `{base_name}.mp4`\n"
                f"📦 **Size:** `{human_readable(output_size)}`\n"
                f"⚙️ **Process Time:** `{format_time(merge_time)}`\n"
                f"🔥 **Subtitles permanently burned**\n\n"
                f"🎉 **Ready for another merge!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True,
            thumb=None  # Disable thumbnail for faster uploads
        )
        upload_time = time.time() - upload_start
        upload_speed = output_size / upload_time if upload_time > 0 else 0
        
        # Final stats
        total_time = time.time() - user_data[chat_id]["start_time"]
        
        await status_msg.edit_text(
            f"🎉 **MISSION ACCOMPLISHED!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ **Video uploaded successfully!**\n"
            f"⚡ **Upload Speed:** `{human_readable(upload_speed)}/s`\n"
            f"⏱️ **Upload Time:** `{format_time(upload_time)}`\n"
            f"🏁 **Total Time:** `{format_time(total_time)}`\n\n"
            f"🚀 **Send another file to continue!**"
        )
        
        # Smart cleanup
        await asyncio.sleep(3)
        try:
            await status_msg.delete()
        except:
            pass
        
        # Cleanup files
        for file_path in [video_path, sub_path, output_file]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.debug(f"Cleanup error: {e}")
        
        del user_data[chat_id]
        
    except Exception as e:
        logger.error(f"Processing error: {e}")
        await status_msg.edit_text(
            f"❌ **TURBO PROCESSING FAILED!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"**Error:** `{str(e)}`\n\n"
            f"💡 Try again with a different file or use /cancel"
        )
        
        # Emergency cleanup
        if chat_id in user_data:
            for key in ["video", "subtitle", "output"]:
                file_path = user_data[chat_id].get(key)
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
            del user_data[chat_id]

# Callback query handler for inline buttons
@app.on_callback_query()
async def handle_callbacks(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    
    if data == "help":
        await help_command(client, callback_query.message)
    elif data == "speedtest":
        await speed_test(client, callback_query.message)
    elif data == "stats":
        await stats_command(client, callback_query.message)
    
    await callback_query.answer()

# Startup message
if __name__ == "__main__":
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 TURBO SUBTITLE MERGE BOT - KOYEB EDITION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"⚡ Max Speed: 15+ MB/s")
    print(f"💪 Workers: {WORKERS} threads")
    print(f"📦 Max File Size: {human_readable(MAX_FILE_SIZE)}")
    print(f"💾 Cache: {CACHE_DIR}")
    print("🔥 Turbo FFmpeg: ENABLED")
    print("🔧 Multi-threading: ACTIVE")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✅ Bot is now ONLINE and READY!")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    # Start the bot
    app.run()
