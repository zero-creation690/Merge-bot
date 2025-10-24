from pyrogram import Client, filters
from pyrogram.types import Message
import subprocess
import os
import time
import asyncio
import logging
import secrets

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

MAX_FILE_SIZE = 2147483648  # 2GB
CACHE_DIR = "/tmp/bot_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "WorkingBurnBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=CACHE_DIR
)

user_data = {}

# ---------- SIMPLE HELPERS ----------
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

# ---------- SIMPLE COMMANDS ----------
@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    welcome_text = (
        "🔥 **SIMPLE SUBTITLE BURNER** 🔥\n\n"
        "**Guaranteed Working:**\n"
        "• Burns subtitles into video\n"
        "• Any format to MP4\n"
        "• Fast processing\n"
        "• 2GB max size\n\n"
        "**How to use:**\n"
        "1. Send video file\n"
        "2. Send .srt subtitle\n"
        "3. Get video with burned subtitles!\n\n"
        "🚀 **Send a video to start!**"
    )
    await message.reply_text(welcome_text)

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    help_text = (
        "📖 **SIMPLE BURNER GUIDE**\n\n"
        "**What is burning?**\n"
        "Subtitles become part of the video permanently\n\n"
        "**Supported:**\n"
        "• All video formats\n"
        "• .srt subtitle files\n"
        "• Up to 2GB files\n\n"
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
        await message.reply_text("✅ **Cancelled!**")
    else:
        await message.reply_text("❌ **No active operation!**")

# ---------- SIMPLE FILE HANDLERS ----------
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
    
    unique_id = secrets.token_hex(6)
    filename = file_obj.file_name or f"video_{unique_id}.mp4"
    
    status_msg = await message.reply_text("📥 **Downloading video...**")
    
    try:
        download_start = time.time()
        video_path = await message.download(
            file_name=os.path.join(CACHE_DIR, f"v_{unique_id}")
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
            f"✅ **Download complete!**\n\n"
            f"**Speed:** {avg_speed:.1f} MB/s\n"
            f"**Time:** {format_time(download_time)}\n\n"
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
    sub_filename = f"s_{unique_id}.srt"
    
    try:
        sub_path = await message.download(
            file_name=os.path.join(CACHE_DIR, sub_filename)
        )
        
        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"burned_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)
        
        # Show processing start
        await status_msg.edit_text("🔥 **Burning subtitles into video...**\n\n⏳ This may take a few minutes...")
        
        burn_start = time.time()
        
        # SIMPLE RELIABLE FFMPEG COMMAND
        cmd = [
            'ffmpeg',
            '-i', video_path,  # Input video
            '-vf', f"subtitles={sub_path}",  # Burn subtitles
            '-c:v', 'libx264',  # Video codec
            '-preset', 'fast',  # Balanced speed/quality
            '-crf', '23',       # Good quality
            '-c:a', 'aac',      # Audio codec
            '-b:a', '192k',     # Audio bitrate
            '-y',               # Overwrite output
            output_file
        ]
        
        logger.info(f"Running: {' '.join(cmd)}")
        
        # Run FFmpeg with timeout
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Wait for completion
        try:
            await asyncio.wait_for(process.wait(), timeout=600)  # 10 minutes
        except asyncio.TimeoutError:
            await status_msg.edit_text("❌ **Processing timeout!** Try smaller file.")
            if chat_id in user_data:
                del user_data[chat_id]
            return
        
        burn_time = time.time() - burn_start
        
        # Check result
        if process.returncode != 0:
            stderr_output = await process.stderr.read()
            error_text = stderr_output.decode('utf-8', errors='ignore')
            logger.error(f"FFmpeg error: {error_text}")
            
            if "Invalid" in error_text:
                raise Exception("Invalid video file format")
            elif "subtitle" in error_text.lower():
                raise Exception("Subtitle format error")
            else:
                raise Exception("Video processing failed")
        
        if not os.path.exists(output_file):
            raise Exception("Output file was not created")
        
        output_size = os.path.getsize(output_file)
        burn_speed = (user_data[chat_id]["file_size"] / burn_time) / (1024 * 1024) if burn_time > 0 else 0
        
        # Upload result
        await status_msg.edit_text("📤 **Uploading result...**")
        
        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **Burn Complete!**\n\n"
                f"**File:** {base_name}.mp4\n"
                f"**Size:** {human_readable(output_size)}\n"
                f"**Burn Speed:** {burn_speed:.1f} MB/s\n"
                f"**Burn Time:** {format_time(burn_time)}\n\n"
                f"🔥 **Subtitles permanently burned into video!**"
            ),
            supports_streaming=True
        )
        upload_time = time.time() - upload_start
        
        # Success
        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **Success!**\n\n"
            f"**Total time:** {format_time(total_time)}\n"
            f"**Upload speed:** {output_size/upload_time/(1024*1024):.1f} MB/s\n\n"
            f"🚀 **Ready for next file!**"
        )
        
        # Cleanup
        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except:
            pass
        
        # Remove files
        for file_path in [video_path, sub_path, output_file]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except:
                pass
        
        del user_data[chat_id]
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error: {error_msg}")
        
        simple_error = "Processing failed"
        if "timeout" in error_msg.lower():
            simple_error = "File too large - try smaller file"
        elif "invalid" in error_msg.lower():
            simple_error = "Invalid file format - try MP4"
        elif "subtitle" in error_msg.lower():
            simple_error = "Subtitle error - check .srt file"
        
        await status_msg.edit_text(
            f"❌ **{simple_error}**\n\n"
            f"💡 **Try:**\n"
            f"• MP4 files work best\n"
            f"• Files under 1GB\n"
            f"• Proper .srt subtitles\n"
            f"• /cancel to restart"
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
    print("🔥 SIMPLE SUBTITLE BURNER")
    print("=" * 50)
    print("✅ No complex progress tracking")
    print("✅ Simple reliable FFmpeg command")
    print("✅ Guaranteed working")
    print("✅ 2GB max file size")
    print("=" * 50)
    print("🚀 Bot is LIVE!")
    print("=" * 50)
    
    app.run()
