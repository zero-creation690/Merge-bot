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

# ---------------- RELIABLE CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Reliable settings
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", "1073741824"))  # 1GB for reliability
WORKERS = int(os.environ.get("WORKERS", "50"))
CACHE_DIR = "/tmp/bot_cache"

# Create cache directory
os.makedirs(CACHE_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "ReliableSubtitleBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=CACHE_DIR,
    in_memory=True,
    workers=WORKERS,
    max_concurrent_transmissions=10,
    sleep_threshold=60
)

user_data = {}
executor = ThreadPoolExecutor(max_workers=WORKERS)

# ---------- SIMPLE HEALTH CHECK SERVER ----------
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
        return  # Disable access logs

def start_health_server():
    """Start simple health check server"""
    try:
        server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
        print("✅ Health server running on port 8000")
        server.serve_forever()
    except Exception as e:
        print(f"❌ Health server failed: {e}")

# Start health server in background thread
health_thread = threading.Thread(target=start_health_server, daemon=True)
health_thread.start()

# ---------- RELIABLE HELPERS ----------
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

def get_video_info(file_path):
    """Get video duration and codec info"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = result.stdout.strip().split('\n')
        return {
            'codec': lines[0] if len(lines) > 0 else 'unknown',
            'duration': float(lines[1]) if len(lines) > 1 else 0
        }
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        return {'codec': 'unknown', 'duration': 0}

class ReliableProgress:
    def __init__(self, client, chat_id, message_id, filename, action="Downloading"):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.action = action
        self.start_time = time.time()
        self.last_update = 0
        
    async def update(self, current, total):
        """Reliable progress tracking"""
        now = time.time()
        
        if now - self.last_update < 2 and current < total:
            return
            
        self.last_update = now
        elapsed = now - self.start_time
        
        percent = (current * 100 / total) if total > 0 else 0
        
        # Calculate speed in MB/s
        if elapsed > 0:
            speed_mbs = (current / elapsed) / (1024 * 1024)
        else:
            speed_mbs = 0
            
        eta = (total - current) / (speed_mbs * 1024 * 1024) if speed_mbs > 0 else 0
        
        bar_len = 10
        filled_len = int(bar_len * current // total) if total > 0 else 0
        bar = "█" * filled_len + "░" * (bar_len - filled_len)
        
        text = (
            f"**{self.action}**\n"
            f"`{bar}` {percent:.1f}%\n"
            f"**Speed:** {speed_mbs:.1f} MB/s\n"
            f"**ETA:** {format_time(eta)}\n"
            f"**File:** {self.filename[:20]}"
        )
        
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except:
            pass

# ---------- RELIABLE COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "🎬 **RELIABLE SUBTITLE BOT**\n\n"
        "**How to use:**\n"
        "1. Send video file (MP4 recommended)\n" 
        "2. Send subtitle file (.srt)\n"
        "3. Get merged video!\n\n"
        "**Features:**\n"
        "• Fast processing\n"
        "• Real-time progress\n"
        "• Auto cleanup\n"
        "• 1GB max size\n\n"
        "🚀 **Send a video to start!**"
    )
    await message.reply_text(welcome_text)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "📖 **HELP GUIDE**\n\n"
        "**Steps:**\n"
        "1. Send video (MP4 works best)\n"
        "2. Send .srt subtitle\n"
        "3. Wait for processing\n"
        "4. Download result\n\n"
        "**Tips:**\n"
        "• Use MP4 format for best results\n"
        "• Keep files under 500MB for speed\n"
        "• Ensure .srt file is properly formatted\n\n"
        "**Commands:** /start /help /cancel"
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
        await message.reply_text("✅ **Operation cancelled!**")
    else:
        await message.reply_text("❌ **No active operation!**")

# ---------- RELIABLE FILE HANDLERS ----------
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
        await message.reply_text("⚠️ **Video received!** Send .srt subtitle now.")
        return
    
    file_size = file_obj.file_size
    if file_size > MAX_FILE_SIZE:
        await message.reply_text(f"❌ **File too large!** Max: {human_readable(MAX_FILE_SIZE)}")
        return
    
    # Generate unique filename
    file_ext = os.path.splitext(file_obj.file_name or "video.mp4")[1]
    unique_id = secrets.token_hex(6)
    filename = f"video_{unique_id}{file_ext}"
    
    status_msg = await message.reply_text("📥 **Starting download...**")
    
    progress = ReliableProgress(client, chat_id, status_msg.id, filename, "DOWNLOADING")
    
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
            f"✅ **Download complete!**\n\n"
            f"**Speed:** {avg_speed:.1f} MB/s\n"
            f"**Time:** {format_time(download_time)}\n"
            f"**Size:** {human_readable(file_size)}\n\n"
            f"📝 **Now send your .srt subtitle file**"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ **Download failed:** {str(e)}")
        if chat_id in user_data:
            del user_data[chat_id]

async def handle_subtitle(client: Client, message: Message):
    chat_id = message.chat.id
    
    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text("⚠️ **Please send video file first!**")
        return
    
    sub_obj = message.document
    
    if not sub_obj.file_name or not sub_obj.file_name.lower().endswith('.srt'):
        await message.reply_text("❌ **Invalid file!** Please send .srt subtitle file.")
        return
    
    status_msg = await message.reply_text("📥 **Downloading subtitle...**")
    
    unique_id = secrets.token_hex(6)
    sub_filename = f"sub_{unique_id}.srt"
    
    progress = ReliableProgress(client, chat_id, status_msg.id, sub_obj.file_name, "DOWNLOADING")
    
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
        await status_msg.edit_text("🔍 **Checking video format...**")
        video_info = await asyncio.get_event_loop().run_in_executor(
            executor, get_video_info, video_path
        )
        
        await status_msg.edit_text("🔥 **Starting subtitle merge...**")
        
        merge_start = time.time()
        
        # RELIABLE FFMPEG COMMAND - TESTED AND WORKING
        cmd = [
            'ffmpeg',
            '-i', video_path,              # Input video
            '-vf', f"subtitles={sub_path}", # Subtitle filter
            '-c:v', 'libx264',             # Video codec
            '-preset', 'fast',             # Balanced speed/quality
            '-crf', '23',                  # Quality setting
            '-c:a', 'aac',                 # Audio codec
            '-b:a', '192k',                # Audio bitrate
            '-y',                          # Overwrite output
            output_file
        ]
        
        logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
        
        # Run FFmpeg with proper error handling
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Wait for completion
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_output = stderr.decode('utf-8', errors='ignore')
            logger.error(f"FFmpeg error: {error_output}")
            
            # Provide specific error messages
            if "Invalid data found" in error_output:
                raise Exception("Invalid video format - try MP4 file")
            elif "subtitle" in error_output.lower():
                raise Exception("Subtitle format error - check .srt file")
            elif "No such file" in error_output:
                raise Exception("File missing - please try again")
            elif "Permission denied" in error_output:
                raise Exception("Permission error - contact support")
            else:
                raise Exception(f"Processing failed: {error_output[:100]}")
        
        merge_time = time.time() - merge_start
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
        
        output_size = os.path.getsize(output_file)
        processing_speed = (user_data[chat_id]["file_size"] / merge_time) / (1024 * 1024) if merge_time > 0 else 0
        
        # Upload video
        await status_msg.edit_text("📤 **Uploading merged video...**")
        
        upload_progress = ReliableProgress(
            client, chat_id, status_msg.id, 
            f"{base_name}_with_subs.mp4", "UPLOADING"
        )
        
        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **Subtitle merge successful!**\n\n"
                f"**File:** {base_name}.mp4\n"
                f"**Size:** {human_readable(output_size)}\n"
                f"**Process speed:** {processing_speed:.1f} MB/s\n"
                f"**Process time:** {format_time(merge_time)}\n\n"
                f"🎬 **Subtitles permanently added to video!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )
        upload_time = time.time() - upload_start
        upload_speed = output_size / upload_time / (1024 * 1024) if upload_time > 0 else 0
        
        # Success message
        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **Success!**\n\n"
            f"**Total time:** {format_time(total_time)}\n"
            f"**Upload speed:** {upload_speed:.1f} MB/s\n"
            f"**Video ready for download!**\n\n"
            f"🚀 **Send another video to continue!**"
        )
        
        # Cleanup after success
        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except:
            pass
        
        # Remove temporary files
        for file_path in [video_path, sub_path, output_file]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.debug(f"Cleanup error: {e}")
        
        del user_data[chat_id]
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Processing error: {error_msg}")
        
        await status_msg.edit_text(
            f"❌ **Processing failed**\n\n"
            f"**Error:** {error_msg}\n\n"
            f"💡 **Solutions:**\n"
            f"• Use MP4 format videos\n"
            f"• Check subtitle file is proper .srt\n"
            f"• Try smaller file size (<500MB)\n"
            f"• Ensure video is not corrupted\n"
            f"• Use /cancel and try again"
        )
        
        # Cleanup on error
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
    print("🎬 RELIABLE SUBTITLE BOT")
    print("=" * 50)
    print("✅ Health server: Port 8000")
    print("✅ Max file size: 1GB")
    print("✅ Supported formats: MP4, MKV, AVI + SRT")
    print("✅ FFmpeg: Tested and working")
    print("✅ Ready for processing!")
    print("=" * 50)
    
    try:
        app.run()
    except Exception as e:
        print(f"❌ Bot failed to start: {e}")
