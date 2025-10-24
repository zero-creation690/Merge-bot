from pyrogram import Client, filters
from pyrogram.types import Message
import subprocess
import os
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
import re

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

app = Client(
    "SubtitleMergeBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="./",
    in_memory=True,
    workers=100,
    max_concurrent_transmissions=10
)

user_data = {}
executor = ThreadPoolExecutor(max_workers=50)

# ---------- Helpers ----------
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
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except:
        return 0

class UltraFastProgressTracker:
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
        self.max_speeds = 10
        
    async def update(self, current, total):
        """Ultra-fast progress tracking with speed averaging"""
        now = time.time()
        
        if now - self.last_update < 1.5 and current < total:
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
        
        bar_len = 22
        filled_len = int(bar_len * current // total) if total > 0 else 0
        bar = "█" * filled_len + "░" * (bar_len - filled_len)
        
        if avg_speed > 10 * 1024 * 1024:
            speed_emoji = "🚀"
        elif avg_speed > 5 * 1024 * 1024:
            speed_emoji = "⚡"
        elif avg_speed > 1 * 1024 * 1024:
            speed_emoji = "🔥"
        else:
            speed_emoji = "📶"
        
        text = (
            f"{'📥' if self.action == 'Downloading' else '📤'} **{self.action.upper()}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 `{self.filename[:35]}{'...' if len(self.filename) > 35 else ''}`\n\n"
            f"`{bar}` **{percent:.1f}%**\n\n"
            f"💾 **Size:** `{human_readable(current)}` / `{human_readable(total)}`\n"
            f"{speed_emoji} **Speed:** `{human_readable(avg_speed)}/s`\n"
            f"⏱️ **ETA:** `{format_time(eta)}`\n"
            f"⏳ **Time:** `{format_time(elapsed)}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        try:
            await self.client.edit_message_text(
                self.chat_id, 
                self.message_id, 
                text
            )
        except Exception as e:
            pass

class FFmpegProgressTracker:
    def __init__(self, client, chat_id, message_id, filename, duration):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.duration = duration
        self.start_time = time.time()
        self.last_update = 0
        
    async def update_from_line(self, line):
        """Parse FFmpeg output and update progress"""
        now = time.time()
        
        # Update every 2 seconds
        if now - self.last_update < 2:
            return
        
        # Parse time from FFmpeg output (format: time=00:01:23.45)
        time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
        if not time_match:
            return
            
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        seconds = float(time_match.group(3))
        
        current_time = hours * 3600 + minutes * 60 + seconds
        
        if self.duration > 0:
            percent = min((current_time / self.duration) * 100, 100)
        else:
            percent = 0
        
        elapsed = now - self.start_time
        
        # Calculate ETA
        if current_time > 0:
            rate = current_time / elapsed
            remaining_time = (self.duration - current_time) / rate if rate > 0 else 0
        else:
            remaining_time = 0
        
        # Create progress bar
        bar_len = 22
        filled_len = int(bar_len * percent / 100)
        bar = "█" * filled_len + "░" * (bar_len - filled_len)
        
        # Parse speed from FFmpeg output
        speed_match = re.search(r'speed=\s*([\d.]+)x', line)
        speed_text = f"{speed_match.group(1)}x" if speed_match else "1.0x"
        
        text = (
            f"⚙️ **PROCESSING VIDEO**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 `{self.filename[:35]}{'...' if len(self.filename) > 35 else ''}`\n\n"
            f"`{bar}` **{percent:.1f}%**\n\n"
            f"🔥 **Burning subtitles...**\n"
            f"⚡ **Speed:** `{speed_text}`\n"
            f"⏱️ **ETA:** `{format_time(remaining_time)}`\n"
            f"⏳ **Time:** `{format_time(elapsed)}`\n"
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
            pass

# ---------- /start ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "⚡ **ULTRA FAST SUBTITLE MERGE BOT** ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 **Features:**\n"
        "• Lightning fast downloads (up to **10+ MB/s**)\n"
        "• Support videos up to **4GB**\n"
        "• Real-time speed tracking\n"
        "• Permanent subtitle burning\n"
        "• Multi-threaded processing\n\n"
        "📋 **How to use:**\n"
        "**1️⃣** Send your video file\n"
        "**2️⃣** Send your subtitle file (.srt)\n"
        "**3️⃣** Get your merged video in seconds!\n\n"
        "💡 **Supported formats:**\n"
        "Video: MP4, MKV, AVI, MOV, FLV, WMV\n"
        "Subtitle: SRT only\n\n"
        "🔥 **Ready to merge at ultra speed!**"
    )
    await message.reply_text(welcome_text)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "🆘 **HELP & INFORMATION**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**Commands:**\n"
        "`/start` - Start the bot\n"
        "`/help` - Show this help message\n"
        "`/cancel` - Cancel current operation\n"
        "`/stats` - View bot statistics\n\n"
        "**Speed Tips:**\n"
        "• Bot uses multi-threaded downloads\n"
        "• Average speed: 5-10 MB/s\n"
        "• Peak speed can reach 15+ MB/s\n"
        "• Speed depends on your connection\n\n"
        "**Limits:**\n"
        "• Max file size: 4GB\n"
        "• Supported video formats: All major formats\n"
        "• Subtitle format: .srt only"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("cancel"))
async def cancel_operation(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id in user_data:
        video_path = user_data[chat_id].get("video")
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except:
                pass
        del user_data[chat_id]
        await message.reply_text("✅ **Operation cancelled!** All files removed.")
    else:
        await message.reply_text("❌ **No active operation to cancel!**")

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
        await message.reply_text("⚠️ **You already sent a video!** Please send the subtitle file (.srt) now.\n\nUse /cancel to start over.")
        return
    
    file_size = file_obj.file_size
    if file_size > 4 * 1024 * 1024 * 1024:
        await message.reply_text(
            f"❌ **File too large!**\n\n"
            f"Your file: `{human_readable(file_size)}`\n"
            f"Maximum: `4.00 GB`"
        )
        return
    
    status_msg = await message.reply_text(
        "🚀 **ULTRA FAST DOWNLOAD INITIATED**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Preparing download at maximum speed..."
    )
    
    filename = file_obj.file_name or f"video_{chat_id}.mp4"
    progress = UltraFastProgressTracker(
        client, 
        chat_id, 
        status_msg.id, 
        filename,
        "Downloading"
    )
    
    try:
        download_start = time.time()
        video_path = await message.download(
            file_name=f"video_{chat_id}_{filename}",
            progress=progress.update
        )
        download_time = time.time() - download_start
        avg_speed = file_size / download_time if download_time > 0 else 0
        
        user_data[chat_id] = {
            "video": video_path,
            "filename": filename
        }
        
        await status_msg.edit_text(
            f"✅ **DOWNLOAD COMPLETE!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁 **File:** `{filename[:40]}`\n"
            f"📦 **Size:** `{human_readable(file_size)}`\n"
            f"⚡ **Avg Speed:** `{human_readable(avg_speed)}/s`\n"
            f"⏱️ **Time:** `{format_time(download_time)}`\n\n"
            f"🔥 **Now send your subtitle file (.srt)**"
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ **DOWNLOAD FAILED!**\n\n**Error:** `{str(e)}`")
        if chat_id in user_data:
            del user_data[chat_id]

async def handle_subtitle(client: Client, message: Message):
    chat_id = message.chat.id
    
    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text("⚠️ **Please send your video file first!**")
        return
    
    sub_obj = message.document
    
    if not sub_obj.file_name or not sub_obj.file_name.lower().endswith('.srt'):
        await message.reply_text("❌ **Invalid subtitle file!**\n\nPlease send a valid **.srt** file")
        return
    
    status_msg = await message.reply_text(
        "🚀 **DOWNLOADING SUBTITLE**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Starting ultra-fast download..."
    )
    
    progress = UltraFastProgressTracker(
        client,
        chat_id,
        status_msg.id,
        sub_obj.file_name,
        "Downloading"
    )
    
    try:
        sub_path = await message.download(
            file_name=f"subtitle_{chat_id}_{sub_obj.file_name}",
            progress=progress.update
        )
        
        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_file = f"merged_{chat_id}_{base_name}.mp4"
        
        # Get video duration for progress tracking
        await status_msg.edit_text(
            "🔍 **ANALYZING VIDEO**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Getting video information..."
        )
        
        duration = get_video_duration(video_path)
        
        await status_msg.edit_text(
            "⚙️ **PROCESSING VIDEO**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔥 Starting subtitle merge...\n"
            "`░░░░░░░░░░░░░░░░░░░░░░` **0%**"
        )
        
        merge_start = time.time()
        
        # FFmpeg command with progress output
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', f"subtitles='{sub_path}'",
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '23',
            '-c:a', 'copy',
            '-threads', '0',
            '-progress', 'pipe:1',
            '-y',
            output_file
        ]
        
        # Create progress tracker
        ffmpeg_progress = FFmpegProgressTracker(
            client,
            chat_id,
            status_msg.id,
            base_name,
            duration
        )
        
        # Run FFmpeg with real-time progress
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Read output line by line for progress updates
        async def read_progress():
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                line_str = line.decode().strip()
                await ffmpeg_progress.update_from_line(line_str)
        
        # Start reading progress
        progress_task = asyncio.create_task(read_progress())
        
        # Wait for process to complete
        await process.wait()
        await progress_task
        
        merge_time = time.time() - merge_start
        
        if process.returncode != 0:
            raise Exception("FFmpeg processing failed")
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
        
        output_size = os.path.getsize(output_file)
        
        # Upload merged video with ultra-fast progress
        await status_msg.edit_text(
            "📤 **UPLOADING VIDEO**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚀 Starting ultra-fast upload...\n"
            "⚡ Maximum speed mode activated"
        )
        
        upload_progress = UltraFastProgressTracker(
            client,
            chat_id,
            status_msg.id,
            f"merged_{base_name}.mp4",
            "Uploading"
        )
        
        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **SUBTITLES MERGED SUCCESSFULLY!**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📁 **File:** `{base_name}.mp4`\n"
                f"📦 **Size:** `{human_readable(output_size)}`\n"
                f"⚙️ **Processing Time:** `{format_time(merge_time)}`\n\n"
                f"🔥 **Subtitles are permanently burned!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )
        upload_time = time.time() - upload_start
        upload_speed = output_size / upload_time if upload_time > 0 else 0
        
        # Send completion message
        await status_msg.edit_text(
            f"🎉 **MISSION COMPLETE!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ Video uploaded successfully!\n"
            f"⚡ **Upload Speed:** `{human_readable(upload_speed)}/s`\n"
            f"⏱️ **Upload Time:** `{format_time(upload_time)}`\n\n"
            f"💡 Send another video to merge more!"
        )
        
        # Cleanup
        await asyncio.sleep(2)
        await status_msg.delete()
        
        for f in [video_path, sub_path, output_file]:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except:
                pass
        
        del user_data[chat_id]
        
    except Exception as e:
        await status_msg.edit_text(
            f"❌ **PROCESSING FAILED!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"**Error:** `{str(e)}`\n\n"
            f"💡 Try again or use /cancel to start over"
        )
        
        # Cleanup on error
        if chat_id in user_data:
            video_path = user_data[chat_id].get("video")
            if video_path and os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except:
                    pass
            del user_data[chat_id]

@app.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    active_users = len(user_data)
    stats_text = (
        f"📊 **BOT STATISTICS**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 **Active Users:** `{active_users}`\n"
        f"⚡ **Max Speed:** `10+ MB/s`\n"
        f"🔄 **Workers:** `100 threads`\n"
        f"📦 **Max File Size:** `4 GB`\n\n"
        f"🚀 **Ultra Fast Engine: ONLINE**"
    )
    await message.reply_text(stats_text)

if __name__ == "__main__":
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 ULTRA FAST SUBTITLE MERGE BOT")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("⚡ Speed: Up to 10+ MB/s")
    print("💪 Workers: 100 threads")
    print("📦 Max Size: 4 GB")
    print("🔥 FFmpeg Progress: ENABLED")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✅ Bot is now ONLINE!")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    app.run()
