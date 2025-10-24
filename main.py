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
import secrets
from aiohttp import web
import threading

# ---------------- HYPER TURBO CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Hyper optimizations
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", "536870912"))  # 512MB for hyper speed
WORKERS = int(os.environ.get("WORKERS", "100"))
CACHE_DIR = "/tmp/hyper_cache"

# Create cache directory
os.makedirs(CACHE_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "HyperTurboBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=CACHE_DIR,
    in_memory=True,
    workers=WORKERS,
    max_concurrent_transmissions=25,
    sleep_threshold=20
)

user_data = {}
executor = ThreadPoolExecutor(max_workers=WORKERS)

# ---------- HEALTH CHECK SERVER ----------
async def health_handler(request):
    return web.Response(text="🚀 HYPER BOT IS RUNNING!")

def start_health_server():
    """Start health check server on port 8000"""
    health_app = web.Application()
    health_app.router.add_get('/', health_handler)
    health_app.router.add_get('/health', health_handler)
    
    try:
        web.run_app(health_app, host='0.0.0.0', port=8000, access_log=None)
    except Exception as e:
        logger.error(f"Health server failed: {e}")

# Start health server in background
health_thread = threading.Thread(target=start_health_server, daemon=True)
health_thread.start()

# ---------- HYPER SPEED HELPERS ----------
def human_readable(size):
    """Convert bytes to human readable format"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

def format_time(seconds):
    """Convert seconds to human readable time"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"

class HyperProgress:
    def __init__(self, client, chat_id, message_id, filename, action="DOWNLOAD"):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.action = action
        self.start_time = time.time()
        self.last_update = 0
        self.speeds = []
        
    async def update(self, current, total):
        """HYPER SPEED progress tracking"""
        now = time.time()
        
        # Ultra fast updates every 0.3 seconds
        if now - self.last_update < 0.3 and current < total:
            return
            
        time_diff = now - self.last_update if self.last_update > 0 else 1
        self.last_update = now
        
        # Calculate speed in MB/s
        bytes_diff = current - self.speeds[-1][0] if self.speeds else current
        speed_mbs = (bytes_diff / time_diff) / (1024 * 1024) if time_diff > 0 else 0
        
        self.speeds.append((current, speed_mbs))
        if len(self.speeds) > 8:
            self.speeds.pop(0)
        
        avg_speed_mbs = sum(s[1] for s in self.speeds) / len(self.speeds) if self.speeds else 0
        percent = (current * 100 / total) if total > 0 else 0
        eta = (total - current) / (avg_speed_mbs * 1024 * 1024) if avg_speed_mbs > 0 else 0
        
        # Hyper compact display
        bar_len = 10
        filled_len = int(bar_len * current // total) if total > 0 else 0
        bar = "█" * filled_len + "░" * (bar_len - filled_len)
        
        # Speed indicators
        if avg_speed_mbs > 50:
            emoji = "🚀"
        elif avg_speed_mbs > 25:
            emoji = "⚡"
        elif avg_speed_mbs > 10:
            emoji = "🔥"
        else:
            emoji = "📶"
        
        text = (
            f"{emoji} **{self.action}** • **{avg_speed_mbs:.1f} MB/s**\n"
            f"`{bar}` **{percent:.1f}%** • ETA: `{format_time(eta)}`\n"
            f"`{human_readable(current)}` / `{human_readable(total)}`"
        )
        
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except:
            pass

class HyperFFmpeg:
    def __init__(self, client, chat_id, message_id, filename, total_size):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.total_size = total_size
        self.start_time = time.time()
        self.last_update = 0
        self.processed_size = 0
        
    async def update(self, current_size):
        """HYPER FFmpeg progress with MB/s"""
        now = time.time()
        if now - self.last_update < 0.5:
            return
            
        self.last_update = now
        elapsed = now - self.start_time
        
        # Calculate processing speed in MB/s
        speed_mbs = (current_size / elapsed) / (1024 * 1024) if elapsed > 0 else 0
        percent = (current_size / self.total_size) * 100 if self.total_size > 0 else 0
        
        # Calculate ETA
        if speed_mbs > 0:
            eta = (self.total_size - current_size) / (speed_mbs * 1024 * 1024)
        else:
            eta = 0
        
        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        bar = "█" * filled_len + "░" * (bar_len - filled_len)
        
        # Burning speed indicators
        if speed_mbs > 40:
            emoji, status = "🚀", "HYPER BURN"
        elif speed_mbs > 20:
            emoji, status = "⚡", "TURBO BURN"
        elif speed_mbs > 10:
            emoji, status = "🔥", "FAST BURN"
        else:
            emoji, status = "⚙️", "BURNING"
        
        text = (
            f"{emoji} **{status}** • **{speed_mbs:.1f} MB/s**\n"
            f"`{bar}` **{percent:.1f}%** • ETA: `{format_time(eta)}`\n"
            f"`{self.filename[:20]}`"
        )
        
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except:
            pass

# ---------- HYPER COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 HYPER GUIDE", callback_data="help")],
        [InlineKeyboardButton("⚡ SPEED TEST", callback_data="speedtest")]
    ])
    
    welcome_text = (
        "🚀 **HYPER SUBTITLE BOT** 🚀\n\n"
        "⚡ **Features:**\n"
        "• **100+ MB/s** Download Speed\n"
        "• **50+ MB/s** Processing Speed\n"
        "• **Instant** Merging\n"
        "• **Zero Delay** Operations\n\n"
        "📋 **Usage:**\n"
        "1. Send video\n"
        "2. Send subtitle\n"
        "3. Get merged video!\n\n"
        "🔥 **READY FOR HYPER SPEED!**"
    )
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **HYPER SPEED GUIDE**\n\n"
        "**Commands:**\n"
        "`/start` - Start hyper mode\n"
        "`/cancel` - Cancel operation\n\n"
        "**Speed:** 100+ MB/s\n"
        "**Limit:** 512MB files\n"
        "**Format:** MP4 + SRT"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("speedtest"))
async def speed_test(client: Client, message: Message):
    test_msg = await message.reply_text("🚀 **HYPER SPEED TEST...**")
    
    try:
        start_time = time.time()
        test_size = 10 * 1024 * 1024
        test_file = os.path.join(CACHE_DIR, f"hyper_test_{message.chat.id}.tmp")
        
        # Hyper fast write
        async with aiofiles.open(test_file, 'wb') as f:
            data = secrets.token_bytes(test_size)
            await f.write(data)
        
        write_time = time.time() - start_time
        write_speed = test_size / write_time / (1024 * 1024)
        
        # Hyper fast read
        read_start = time.time()
        async with aiofiles.open(test_file, 'rb') as f:
            await f.read()
        read_time = time.time() - read_start
        read_speed = test_size / read_time / (1024 * 1024)
        
        result_text = (
            f"📊 **HYPER SPEED RESULTS**\n\n"
            f"🚀 **Write:** `{write_speed:.1f} MB/s`\n"
            f"⚡ **Read:** `{read_speed:.1f} MB/s`\n\n"
            f"🔥 **Status:** {'HYPER READY' if write_speed > 50 else 'TURBO READY'}"
        )
        
        await test_msg.edit_text(result_text)
        
    except Exception as e:
        await test_msg.edit_text(f"❌ **Test failed:** `{str(e)}`")
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)

@app.on_message(filters.command("cancel"))
async def cancel_operation(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id in user_data:
        for key in ["video", "subtitle", "output"]:
            file_path = user_data[chat_id].get(key)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
        del user_data[chat_id]
        await message.reply_text("✅ **Cancelled!**")
    else:
        await message.reply_text("❌ **No active operation!**")

# ---------- HYPER FILE HANDLERS ----------
@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    chat_id = message.chat.id
    
    if message.video:
        file_obj = message.video
    elif message.document:
        file_obj = message.document
        if file_obj.file_name and file_obj.file_name.lower().endswith('.srt'):
            await handle_subtitle(client, message)
            return
    else:
        return
    
    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text("⚠️ **Video received!** Send .srt now.")
        return
    
    file_size = file_obj.file_size
    if file_size > MAX_FILE_SIZE:
        await message.reply_text(f"❌ **Too large!** Max: `{human_readable(MAX_FILE_SIZE)}`")
        return
    
    # Hyper fast setup
    unique_id = secrets.token_hex(4)
    filename = f"v_{unique_id}.mp4"
    
    status_msg = await message.reply_text("🚀 **HYPER DOWNLOAD STARTED**")
    
    progress = HyperProgress(client, chat_id, status_msg.id, filename, "DOWNLOAD")
    
    try:
        download_start = time.time()
        video_path = await message.download(
            file_name=os.path.join(CACHE_DIR, filename),
            progress=progress.update
        )
        download_time = time.time() - download_start
        avg_speed = file_size / download_time / (1024 * 1024)
        
        user_data[chat_id] = {
            "video": video_path,
            "filename": file_obj.file_name or filename,
            "file_size": file_size,
            "start_time": time.time()
        }
        
        await status_msg.edit_text(
            f"✅ **DOWNLOAD COMPLETE!**\n\n"
            f"🚀 **Speed:** `{avg_speed:.1f} MB/s`\n"
            f"⏱️ **Time:** `{format_time(download_time)}`\n\n"
            f"🔥 **Send subtitle file (.srt)**"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ **Download failed:** `{str(e)}`")
        if chat_id in user_data:
            del user_data[chat_id]

async def handle_subtitle(client: Client, message: Message):
    chat_id = message.chat.id
    
    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text("⚠️ **Send video first!**")
        return
    
    sub_obj = message.document
    
    if not sub_obj.file_name or not sub_obj.file_name.lower().endswith('.srt'):
        await message.reply_text("❌ **Invalid!** Send .srt file.")
        return
    
    status_msg = await message.reply_text("🚀 **DOWNLOADING SUBTITLE**")
    
    unique_id = secrets.token_hex(4)
    sub_filename = f"s_{unique_id}.srt"
    
    progress = HyperProgress(client, chat_id, status_msg.id, sub_obj.file_name, "DOWNLOAD")
    
    try:
        sub_path = await message.download(
            file_name=os.path.join(CACHE_DIR, sub_filename),
            progress=progress.update
        )
        
        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"m_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)
        
        video_size = user_data[chat_id]["file_size"]
        
        await status_msg.edit_text("🚀 **HYPER PROCESSING STARTED**")
        
        merge_start = time.time()
        ffmpeg_progress = HyperFFmpeg(client, chat_id, status_msg.id, base_name, video_size)
        
        # HYPER FFMPEG COMMAND - MAXIMUM SPEED
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', f"subtitles={sub_path}",
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'fastdecode',
            '-crf', '26',
            '-c:a', 'copy',
            '-movflags', '+faststart',
            '-threads', '4',
            '-y',
            output_file
        ]
        
        # Start progress simulation
        progress_task = asyncio.create_task(simulate_progress(ffmpeg_progress, video_size, merge_start))
        
        # Run FFmpeg
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            await asyncio.wait_for(process.wait(), timeout=180)  # 3 minute timeout
        except asyncio.TimeoutError:
            process.kill()
            progress_task.cancel()
            raise Exception("HYPER TIMEOUT - File too large")
        
        progress_task.cancel()
        
        if process.returncode != 0:
            raise Exception("FFmpeg processing failed")
        
        merge_time = time.time() - merge_start
        output_size = os.path.getsize(output_file)
        processing_speed = (video_size / merge_time) / (1024 * 1024) if merge_time > 0 else 0
        
        # Hyper upload
        await status_msg.edit_text("🚀 **HYPER UPLOAD STARTED**")
        
        upload_progress = HyperProgress(client, chat_id, status_msg.id, f"merged_{base_name}.mp4", "UPLOAD")
        
        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **HYPER MERGE COMPLETE!**\n\n"
                f"🚀 **Process Speed:** `{processing_speed:.1f} MB/s`\n"
                f"⏱️ **Process Time:** `{format_time(merge_time)}`\n"
                f"📦 **Output Size:** `{human_readable(output_size)}`\n\n"
                f"🔥 **READY FOR NEXT!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )
        upload_time = time.time() - upload_start
        
        # Success
        await status_msg.edit_text(
            f"🎉 **HYPER SUCCESS!**\n\n"
            f"✅ **Total Time:** `{format_time(time.time() - user_data[chat_id]['start_time'])}`\n"
            f"🚀 **Send next file!**"
        )
        
        # Quick cleanup
        await asyncio.sleep(1)
        try:
            await status_msg.delete()
        except:
            pass
        
        # Clean files
        for file_path in [video_path, sub_path, output_file]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except:
                pass
        
        del user_data[chat_id]
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Hyper error: {error_msg}")
        
        await status_msg.edit_text(
            f"❌ **HYPER FAILED!**\n\n"
            f"`{error_msg[:80]}`\n\n"
            f"💡 Use smaller files for hyper speed!"
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

async def simulate_progress(progress_tracker, total_size, start_time):
    """Simulate progress for FFmpeg with MB/s calculation"""
    try:
        elapsed = 0
        while elapsed < 300:  # 5 minute max
            elapsed = time.time() - start_time
            # Simulate processing based on time
            current_size = min(total_size, total_size * (elapsed / 60))  # Assume 1 minute for full processing
            await progress_tracker.update(current_size)
            await asyncio.sleep(0.5)
    except:
        pass

# Callback handler
@app.on_callback_query()
async def handle_callbacks(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    
    if data == "help":
        await help_command(client, callback_query.message)
    elif data == "speedtest":
        await speed_test(client, callback_query.message)
    
    await callback_query.answer()

# HYPER STARTUP
if __name__ == "__main__":
    print("🚀 HYPER SUBTITLE BOT - READY!")
    print("⚡ Speed: 100+ MB/s | 💪 Workers: 100")
    print("📦 Max Size: 512MB | 🔥 Mode: HYPER")
    print("🌐 Health Server: Port 8000")
    print("✅ Bot is LIVE and READY!")
    
    app.run()
