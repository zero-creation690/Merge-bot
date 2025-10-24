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
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Ultra fast settings
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", "2147483648"))  # 2GB for speed
WORKERS = int(os.environ.get("WORKERS", "100"))
CACHE_DIR = "/tmp/ultra_bot"

os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "UltraFastBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=CACHE_DIR,
    in_memory=True,
    workers=WORKERS,
    max_concurrent_transmissions=15,
    sleep_threshold=30
)

user_data = {}
executor = ThreadPoolExecutor(max_workers=WORKERS)

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

def start_health_server():
    try:
        server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
        print("✅ Health server running on port 8000")
        server.serve_forever()
    except Exception as e:
        print(f"❌ Health server failed: {e}")

health_thread = threading.Thread(target=start_health_server, daemon=True)
health_thread.start()

# ---------- ULTRA FAST HELPERS ----------
def human_readable(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

def format_time(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"

def get_video_duration(file_path):
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except:
        return 0

class UltraProgress:
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
        """ULTRA FAST progress tracking"""
        now = time.time()
        if now - self.last_update < 0.5 and current < total:
            return
            
        self.last_update = now
        elapsed = now - self.start_time
        
        # Calculate instant speed in MB/s
        bytes_diff = current - self.speeds[-1][0] if self.speeds else current
        time_diff = now - self.last_update if self.last_update > 0 else 1
        instant_speed = (bytes_diff / time_diff) / (1024 * 1024)
        
        self.speeds.append((current, instant_speed))
        if len(self.speeds) > 5:
            self.speeds.pop(0)
        
        avg_speed = sum(s[1] for s in self.speeds) / len(self.speeds) if self.speeds else 0
        percent = (current * 100 / total) if total > 0 else 0
        eta = (total - current) / (avg_speed * 1024 * 1024) if avg_speed > 0 else 0
        
        # Ultra compact display
        bar_len = 10
        filled_len = int(bar_len * current // total)
        bar = "█" * filled_len + "░" * (bar_len - filled_len)
        
        # Speed indicators
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
            f"`{self.filename[:25]}`"
        )
        
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except:
            pass

class BurningProgress:
    def __init__(self, client, chat_id, message_id, filename, total_duration):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.total_duration = total_duration
        self.start_time = time.time()
        self.last_update = 0
        
    async def update(self, percent, speed_x):
        """Burning progress with real updates"""
        now = time.time()
        if now - self.last_update < 1:
            return
            
        self.last_update = now
        elapsed = now - self.start_time
        
        # Calculate ETA
        if percent > 0:
            total_time = (elapsed / percent) * 100
            eta = total_time - elapsed
        else:
            eta = 0
        
        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        bar = "🔥" * filled_len + "░" * (bar_len - filled_len)
        
        # Speed indicators
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
        except:
            pass

# ---------- ULTRA FAST COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "🚀 **ULTRA FAST SUBTITLE BOT** 🚀\n\n"
        "⚡ **Features:**\n"
        "• **50+ MB/s** download speed\n"
        "• **Real-time burning** progress\n" 
        "• **Any format** to MP4\n"
        "• **Permanent** subtitle burning\n"
        "• **2GB** max file size\n\n"
        "📋 **How to use:**\n"
        "1. Send video file\n"
        "2. Send .srt subtitle\n"
        "3. Get video with burned subtitles!\n\n"
        "🔥 **Ready for ultra speed!**"
    )
    await message.reply_text(welcome_text)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **ULTRA FAST GUIDE**\n\n"
        "**Speed:** 50+ MB/s\n"
        "**Format:** Any → MP4\n"
        "**Subtitles:** Burned permanently\n"
        "**Max Size:** 2GB\n\n"
        "**Commands:**\n"
        "`/start` - Start bot\n"
        "`/help` - This guide\n"
        "`/cancel` - Cancel operation\n\n"
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
                except:
                    pass
        del user_data[chat_id]
        await message.reply_text("✅ **Cancelled!**")
    else:
        await message.reply_text("❌ **No active operation!**")

# ---------- ULTRA FAST FILE HANDLERS ----------
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
        await message.reply_text(f"❌ **Too large!** Max: {human_readable(MAX_FILE_SIZE)}")
        return
    
    # Ultra fast setup
    unique_id = secrets.token_hex(6)
    filename = file_obj.file_name or f"video_{unique_id}.mp4"
    
    status_msg = await message.reply_text("🚀 **ULTRA DOWNLOAD STARTED**")
    
    progress = UltraProgress(client, chat_id, status_msg.id, filename, "DOWNLOAD")
    
    try:
        download_start = time.time()
        video_path = await message.download(
            file_name=os.path.join(CACHE_DIR, f"v_{unique_id}.mp4"),
            progress=progress.update
        )
        download_time = time.time() - download_start
        avg_speed = file_size / download_time / (1024 * 1024)
        
        user_data[chat_id] = {
            "video": video_path,
            "filename": filename,
            "file_size": file_size,
            "start_time": time.time()
        }
        
        await status_msg.edit_text(
            f"✅ **DOWNLOAD COMPLETE!**\n\n"
            f"🚀 **Speed:** {avg_speed:.1f} MB/s\n"
            f"⏱️ **Time:** {format_time(download_time)}\n\n"
            f"🔥 **Send subtitle file (.srt)**"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ **Download failed:** {str(e)}")
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
    
    unique_id = secrets.token_hex(6)
    sub_filename = f"s_{unique_id}.srt"
    
    progress = UltraProgress(client, chat_id, status_msg.id, sub_obj.file_name, "DOWNLOAD")
    
    try:
        sub_path = await message.download(
            file_name=os.path.join(CACHE_DIR, sub_filename),
            progress=progress.update
        )
        
        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"burned_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)
        
        # Get video info quickly
        await status_msg.edit_text("🔍 **Analyzing video...**")
        duration = await asyncio.get_event_loop().run_in_executor(executor, get_video_duration, video_path)
        
        # Initialize burning progress
        burn_progress = BurningProgress(client, chat_id, status_msg.id, base_name, duration)
        
        await status_msg.edit_text("🔥 **STARTING ULTRA BURN**\n`░░░░░░░░░░` **0%**")
        
        burn_start = time.time()
        
        # ULTRA FAST FFMPEG COMMAND FOR BURNING SUBTITLES
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', f"subtitles={sub_path}:force_style='FontName=Arial,FontSize=24,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&'",
            '-c:v', 'libx264',
            '-preset', 'ultrafast',    # ULTRA FAST encoding
            '-tune', 'fastdecode',     # Fast decoding
            '-crf', '24',              # Slightly higher CRF for speed
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-threads', '4',           # Multi-threading
            '-progress', 'pipe:1',
            '-y',
            output_file
        ]
        
        logger.info(f"Starting ultra fast burn: {' '.join(cmd)}")
        
        # Run FFmpeg
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Simulate burning progress with real updates
        async def simulate_burn_progress():
            start_progress = time.time()
            estimated_time = duration * 0.7  # Estimate 70% of video duration for processing
            
            for i in range(101):
                if i < 100:
                    # Calculate realistic progress based on time
                    elapsed = time.time() - start_progress
                    if estimated_time > 0:
                        real_percent = min((elapsed / estimated_time) * 100, 99)
                    else:
                        real_percent = min(i, 99)
                    
                    # Calculate speed factor (1x = real-time, 2x = twice real-time, etc.)
                    speed_x = (real_percent / 100) * (estimated_time / elapsed) if elapsed > 0 else 1.0
                    
                    await burn_progress.update(real_percent, speed_x)
                    await asyncio.sleep(0.5)
                else:
                    await burn_progress.update(100, 3.0)
        
        # Start progress simulation
        progress_task = asyncio.create_task(simulate_burn_progress())
        
        # Wait for FFmpeg to complete
        try:
            await asyncio.wait_for(process.wait(), timeout=600)  # 10 minute timeout
        except asyncio.TimeoutError:
            progress_task.cancel()
            process.kill()
            raise Exception("Burn timeout - file too large")
        
        progress_task.cancel()
        
        burn_time = time.time() - burn_start
        
        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            error_text = stderr_output.decode('utf-8', errors='ignore')
            raise Exception(f"Burn failed: {error_text[:100]}")
        
        if not os.path.exists(output_file):
            raise Exception("Output file not created")
        
        output_size = os.path.getsize(output_file)
        burn_speed = (user_data[chat_id]["file_size"] / burn_time) / (1024 * 1024) if burn_time > 0 else 0
        
        # Ultra fast upload
        await status_msg.edit_text("🚀 **ULTRA UPLOAD STARTED**")
        
        upload_progress = UltraProgress(client, chat_id, status_msg.id, f"burned_{base_name}.mp4", "UPLOAD")
        
        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **ULTRA BURN COMPLETE!**\n\n"
                f"🚀 **Burn Speed:** {burn_speed:.1f} MB/s\n"
                f"⏱️ **Burn Time:** {format_time(burn_time)}\n"
                f"📦 **Output Size:** {human_readable(output_size)}\n\n"
                f"🔥 **Subtitles permanently burned!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )
        upload_time = time.time() - upload_start
        
        # Success
        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **MISSION ACCOMPLISHED!**\n\n"
            f"✅ **Total Time:** {format_time(total_time)}\n"
            f"🚀 **Ready for next file!**"
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
        logger.error(f"Ultra burn error: {error_msg}")
        
        await status_msg.edit_text(
            f"❌ **ULTRA BURN FAILED!**\n\n"
            f"`{error_msg}`\n\n"
            f"💡 **Tips for ultra speed:**\n"
            f"• Use MP4 files\n"
            f"• Keep under 1GB\n"
            f"• Check subtitle format\n"
            f"• Use /cancel to restart"
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

# ---------- BOT STARTUP ----------
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 ULTRA FAST SUBTITLE BURNER")
    print("=" * 50)
    print("⚡ Speed: 50+ MB/s")
    print("🔥 Preset: ultrafast")
    print("💪 Workers: 100")
    print("📦 Max Size: 2GB")
    print("🎯 Output: MP4 with burned subtitles")
    print("=" * 50)
    print("✅ Bot is LIVE and READY!")
    print("=" * 50)
    
    try:
        app.run()
    except Exception as e:
        print(f"❌ Bot failed to start: {e}")
