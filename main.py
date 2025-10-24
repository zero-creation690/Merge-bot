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

# 4GB support and all file types
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", "4294967296"))  # 4GB
WORKERS = int(os.environ.get("WORKERS", "50"))
CACHE_DIR = "/tmp/bot_cache"

os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "UniversalSubtitleBot",
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

# ---------- PROGRESS HELPERS ----------
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
        return 0

def get_video_codec(file_path):
    """Get video codec to determine best output format"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip().lower()
    except Exception as e:
        logger.error(f"Error getting video codec: {e}")
        return 'h264'

class DownloadProgress:
    def __init__(self, client, chat_id, message_id, filename):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.start_time = time.time()
        self.last_update = 0
        
    async def update(self, current, total):
        now = time.time()
        if now - self.last_update < 2 and current < total:
            return
            
        self.last_update = now
        elapsed = now - self.start_time
        
        percent = (current * 100 / total) if total > 0 else 0
        speed_mbs = (current / elapsed) / (1024 * 1024) if elapsed > 0 else 0
        eta = (total - current) / (speed_mbs * 1024 * 1024) if speed_mbs > 0 else 0
        
        bar_len = 12
        filled_len = int(bar_len * current // total)
        bar = "█" * filled_len + "░" * (bar_len - filled_len)
        
        text = (
            f"📥 **DOWNLOADING**\n"
            f"`{bar}` **{percent:.1f}%**\n"
            f"**Speed:** `{speed_mbs:.1f} MB/s`\n"
            f"**ETA:** `{format_time(eta)}`\n"
            f"`{human_readable(current)} / {human_readable(total)}`"
        )
        
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except:
            pass

class FFmpegProgress:
    def __init__(self, client, chat_id, message_id, filename, total_duration):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.total_duration = total_duration
        self.start_time = time.time()
        self.last_update = 0
        self.last_time = 0
        
    async def update_from_output(self, line):
        """Parse FFmpeg output and update progress in real-time"""
        now = time.time()
        if now - self.last_update < 1.5:  # Update every 1.5 seconds
            return
            
        # Parse time from FFmpeg output
        time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
        if time_match:
            hours = int(time_match.group(1))
            minutes = int(time_match.group(2))
            seconds = float(time_match.group(3))
            current_time = hours * 3600 + minutes * 60 + seconds
            
            if self.total_duration > 0:
                percent = min((current_time / self.total_duration) * 100, 99)
            else:
                percent = 0
                
            elapsed = now - self.start_time
            
            # Calculate processing speed
            time_diff = current_time - self.last_time
            real_time_diff = now - self.last_update if self.last_update > 0 else 1
            speed_factor = time_diff / real_time_diff if real_time_diff > 0 else 1
            
            # Calculate ETA
            if current_time > 0 and speed_factor > 0:
                remaining_time = (self.total_duration - current_time) / speed_factor
            else:
                remaining_time = 0
                
            self.last_time = current_time
            
            # Get encoding speed
            speed_match = re.search(r'speed=\s*([\d.]+)x', line)
            speed_text = speed_match.group(1) + "x" if speed_match else f"{speed_factor:.1f}x"
            
            bar_len = 12
            filled_len = int(bar_len * percent / 100)
            bar = "🔥" * filled_len + "░" * (bar_len - filled_len)
            
            text = (
                f"⚙️ **PROCESSING**\n"
                f"`{bar}` **{percent:.1f}%**\n"
                f"**Speed:** `{speed_text}`\n"
                f"**ETA:** `{format_time(remaining_time)}`\n"
                f"**Burning subtitles...**"
            )
            
            try:
                await self.client.edit_message_text(self.chat_id, self.message_id, text)
                self.last_update = now
            except:
                pass

# ---------- COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "🎬 **UNIVERSAL SUBTITLE BOT**\n\n"
        "**Supports ALL video formats:**\n"
        "• MP4, MKV, AVI, MOV, FLV, WMV\n"
        "• WebM, 3GP, M4V, TS, MTS\n"
        "• And many more!\n\n"
        "**Features:**\n"
        "• Up to 4GB files\n"
        "• Real FFmpeg progress\n"
        "• All video formats\n"
        "• Fast processing\n\n"
        "**How to use:**\n"
        "1. Send any video file\n"
        "2. Send .srt subtitle\n"
        "3. Get merged MP4!\n\n"
        "🚀 **Send any video to start!**"
    )
    await message.reply_text(welcome_text)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "📖 **UNIVERSAL SUBTITLE BOT**\n\n"
        "**Supported Formats:**\n"
        "**Videos:** MP4, MKV, AVI, MOV, FLV, WMV, WebM, 3GP, M4V, TS, MTS\n"
        "**Subtitles:** SRT only\n\n"
        "**Max File Size:** 4GB\n"
        "**Output Format:** MP4 (universal)\n\n"
        "**Real-time Features:**\n"
        "• Actual FFmpeg progress %\n"
        "• Live encoding speed\n"
        "• Accurate ETA\n"
        "• Burning status\n\n"
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

# ---------- UNIVERSAL FILE HANDLER ----------
@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    chat_id = message.chat.id
    
    if message.video:
        file_obj = message.video
        file_type = "video"
    elif message.document:
        file_obj = message.document
        # Check if it's a subtitle file
        if file_obj.file_name and file_obj.file_name.lower().endswith('.srt'):
            await handle_subtitle(client, message)
            return
        file_type = "document"
    else:
        return
    
    # Check if user already sent a video
    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text("⚠️ **Video received!** Send .srt subtitle now.\nUse /cancel to start over.")
        return
    
    file_size = file_obj.file_size
    if file_size > MAX_FILE_SIZE:
        await message.reply_text(
            f"❌ **File too large!**\n\n"
            f"Your file: `{human_readable(file_size)}`\n"
            f"Maximum: `{human_readable(MAX_FILE_SIZE)}`\n\n"
            f"💡 Please use a smaller file."
        )
        return
    
    # Get original filename or generate one
    original_filename = file_obj.file_name or f"video_{secrets.token_hex(4)}.mp4"
    file_ext = os.path.splitext(original_filename)[1].lower()
    
    # Generate unique filename
    unique_id = secrets.token_hex(8)
    filename = f"video_{unique_id}{file_ext}"
    
    status_msg = await message.reply_text("📥 **Starting download...**")
    
    progress = DownloadProgress(client, chat_id, status_msg.id, original_filename)
    
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
            "filename": original_filename,
            "file_size": file_size,
            "file_ext": file_ext,
            "start_time": time.time()
        }
        
        await status_msg.edit_text(
            f"✅ **Download complete!**\n\n"
            f"**File:** `{original_filename}`\n"
            f"**Format:** `{file_ext.upper().replace('.', '')}`\n"
            f"**Size:** `{human_readable(file_size)}`\n"
            f"**Speed:** `{avg_speed:.1f} MB/s`\n"
            f"**Time:** `{format_time(download_time)}`\n\n"
            f"📝 **Now send your .srt subtitle file**"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ **Download failed:** `{str(e)}`")
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
    
    unique_id = secrets.token_hex(8)
    sub_filename = f"sub_{unique_id}.srt"
    
    progress = DownloadProgress(client, chat_id, status_msg.id, sub_obj.file_name)
    
    try:
        sub_path = await message.download(
            file_name=os.path.join(CACHE_DIR, sub_filename),
            progress=progress.update
        )
        
        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        original_ext = user_data[chat_id]["file_ext"]
        base_name = os.path.splitext(original_filename)[0]
        
        # Output will always be MP4 for universal compatibility
        output_filename = f"merged_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)
        
        # Get video duration for progress tracking
        await status_msg.edit_text("🔍 **Analyzing video format...**")
        duration = await asyncio.get_event_loop().run_in_executor(
            executor, get_video_duration, video_path
        )
        
        # Get video codec for optimal settings
        video_codec = await asyncio.get_event_loop().run_in_executor(
            executor, get_video_codec, video_path
        )
        
        # Initialize FFmpeg progress tracker
        ffmpeg_progress = FFmpegProgress(client, chat_id, status_msg.id, original_filename, duration)
        
        # Show initial processing state with file info
        await status_msg.edit_text(
            f"⚙️ **Starting processing...**\n"
            f"**Input:** `{original_ext.upper().replace('.', '')}` → **Output:** `MP4`\n"
            f"`░░░░░░░░░░░░` **0%**"
        )
        
        merge_start = time.time()
        
        # UNIVERSAL FFMPEG COMMAND - WORKS WITH ALL FORMATS
        cmd = [
            'ffmpeg',
            '-i', video_path,  # Input video (any format)
            '-vf', f"subtitles={sub_path}:force_style='FontSize=24,PrimaryColour=&HFFFFFF&'",
            '-c:v', 'libx264',      # Universal video codec
            '-preset', 'medium',    # Balanced speed/quality
            '-crf', '23',           # Good quality
            '-c:a', 'aac',          # Universal audio codec
            '-b:a', '192k',         # Good audio quality
            '-movflags', '+faststart',  # Web optimization
            '-max_muxing_queue_size', '9999',  # Handle complex files
            '-progress', 'pipe:1',  # Progress output
            '-y',                   # Overwrite output
            output_file
        ]
        
        logger.info(f"Processing {original_ext} file with command: {' '.join(cmd)}")
        
        # Run FFmpeg and capture progress in real-time
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Read progress output in real-time
        async def read_progress():
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore').strip()
                await ffmpeg_progress.update_from_output(line_str)
        
        # Start reading progress
        progress_task = asyncio.create_task(read_progress())
        
        # Wait for process to complete with timeout
        try:
            await asyncio.wait_for(process.wait(), timeout=1200)  # 20 minutes for 4GB files
        except asyncio.TimeoutError:
            progress_task.cancel()
            process.kill()
            raise Exception("Processing timeout - file too large or complex")
        
        progress_task.cancel()
        
        # Show 100% completion
        await status_msg.edit_text("⚙️ **Finalizing...**\n`🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥` **100%**")
        
        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            error_text = stderr_output.decode('utf-8', errors='ignore')
            logger.error(f"FFmpeg error: {error_text}")
            
            # Provide specific error messages
            if "Invalid data found" in error_text:
                raise Exception("Unsupported video format or corrupted file")
            elif "subtitle" in error_text.lower():
                raise Exception("Subtitle format error - check .srt file")
            elif "No such file" in error_text:
                raise Exception("File missing - please try again")
            else:
                raise Exception(f"Video processing failed: {error_text[:150]}")
        
        merge_time = time.time() - merge_start
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
        
        output_size = os.path.getsize(output_file)
        processing_speed = (user_data[chat_id]["file_size"] / merge_time) / (1024 * 1024) if merge_time > 0 else 0
        
        # Upload video
        await status_msg.edit_text("📤 **Uploading merged video...**")
        
        upload_progress = DownloadProgress(
            client, chat_id, status_msg.id, 
            f"{base_name}_with_subs.mp4"
        )
        
        upload_start = time.time()
        await client.send_document(
            chat_id,
            output_file,
            caption=(
                f"✅ **Subtitle merge successful!**\n\n"
                f"**Original:** `{original_filename}`\n"
                f"**Output:** `{base_name}_with_subs.mp4`\n"
                f"**Size:** `{human_readable(output_size)}`\n"
                f"**Process speed:** `{processing_speed:.1f} MB/s`\n"
                f"**Process time:** `{format_time(merge_time)}`\n\n"
                f"🎬 **Subtitles permanently burned into video!**"
            ),
            progress=upload_progress.update,
            force_document=True
        )
        upload_time = time.time() - upload_start
        
        # Success message
        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **Success!**\n\n"
            f"**Total time:** `{format_time(total_time)}`\n"
            f"**Upload speed:** `{output_size/upload_time/(1024*1024):.1f} MB/s`\n"
            f"**Video ready for download!**\n\n"
            f"🚀 **Send another video to continue!**"
        )
        
        # Cleanup
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
            except:
                pass
        
        del user_data[chat_id]
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Processing error: {error_msg}")
        
        await status_msg.edit_text(
            f"❌ **Processing failed**\n\n"
            f"**Error:** `{error_msg}`\n\n"
            f"💡 **Solutions:**\n"
            f"• Try a different video file\n"
            f"• Check subtitle format is proper .srt\n"
            f"• For large files, wait and try again\n"
            f"• Use MP4/MKV for best results\n"
            f"• Use /cancel to restart"
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
    print("=" * 60)
    print("🎬 UNIVERSAL SUBTITLE BOT - 4GB SUPPORT")
    print("=" * 60)
    print("✅ Max file size: 4GB")
    print("✅ All formats: MP4, MKV, AVI, MOV, FLV, WMV, WebM, etc.")
    print("✅ Real FFmpeg progress bar")
    print("✅ Health server: Port 8000")
    print("✅ Output: Universal MP4 format")
    print("=" * 60)
    print("🚀 Bot is LIVE and READY!")
    print("=" * 60)
    
    try:
        app.run()
    except Exception as e:
        print(f"❌ Bot failed to start: {e}")
