from pyrogram import Client, filters
from pyrogram.types import Message
import subprocess
import os
import time
import asyncio
from aiohttp import web
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Validate credentials
if not API_ID or not API_HASH or not BOT_TOKEN:
    logger.error("❌ Missing environment variables: API_ID, API_HASH, BOT_TOKEN")
    exit(1)

logger.info("✅ Credentials validated successfully")

app = Client(
    "subtitle_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=3
)

user_data = {}

# ---------- Health Check Server ----------
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_health_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("✅ Health server running on port 8080")
    return runner

# ---------- Helper Functions ----------
def human_readable(size):
    if not size: return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024: return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

# ---------- Bot Commands ----------
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    logger.info(f"Start command from {message.from_user.id}")
    await message.reply_text(
        "🎬 **Subtitle Merge Bot**\n\n"
        "Send me a video file, then a .srt subtitle file, and I'll merge them for you!\n\n"
        "**Commands:**\n"
        "/start - Start bot\n"
        "/help - Show help\n"
        "/cancel - Cancel operation"
    )

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    await message.reply_text(
        "📖 **How to use:**\n\n"
        "1. Send a video file (MP4, MKV, AVI, etc)\n"
        "2. Send a .srt subtitle file\n"
        "3. Wait for processing\n"
        "4. Get your merged video!\n\n"
        "Max file size: 2GB\n"
        "Format: .srt subtitles only"
    )

@app.on_message(filters.command("cancel"))
async def cancel_command(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id in user_data:
        video_path = user_data[chat_id].get('video_path')
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except:
                pass
        del user_data[chat_id]
        await message.reply_text("✅ Operation cancelled!")
    else:
        await message.reply_text("❌ No active operation!")

@app.on_message(filters.command("ping"))
async def ping_command(client: Client, message: Message):
    await message.reply_text("🏓 Pong! Bot is working!")

# ---------- File Handling ----------
@app.on_message(filters.video | filters.document)
async def handle_files(client: Client, message: Message):
    chat_id = message.chat.id
    logger.info(f"Received file from {chat_id}")
    
    # Check if it's a subtitle file
    if (message.document and 
        message.document.file_name and 
        message.document.file_name.lower().endswith('.srt')):
        logger.info(f"Detected subtitle file from {chat_id}")
        await handle_subtitle(client, message)
        return
    
    # Handle video file
    if chat_id in user_data:
        await message.reply_text("📁 I already have your video! Now send the .srt subtitle file.")
        return
    
    file = message.video or message.document
    if not file:
        return
    
    # Check file size
    if file.file_size > 2 * 1024 * 1024 * 1024:
        await message.reply_text("❌ File too large! Max 2GB")
        return
    
    try:
        status_msg = await message.reply_text("📥 Downloading video...")
        logger.info(f"Downloading video for {chat_id}")
        
        # Download video
        video_path = await message.download(
            file_name=f"video_{chat_id}_{int(time.time())}.mp4"
        )
        
        user_data[chat_id] = {'video_path': video_path}
        
        await status_msg.edit_text(
            f"✅ **Video downloaded!**\n\n"
            f"📦 Size: {human_readable(file.file_size)}\n\n"
            f"📁 **Now send your .srt subtitle file**"
        )
        logger.info(f"Video downloaded successfully for {chat_id}")
        
    except Exception as e:
        logger.error(f"Video download error for {chat_id}: {e}")
        await message.reply_text("❌ Failed to download video")
        if chat_id in user_data:
            del user_data[chat_id]

async def handle_subtitle(client: Client, message: Message):
    chat_id = message.chat.id
    logger.info(f"Processing subtitle for {chat_id}")
    
    if chat_id not in user_data:
        await message.reply_text("❌ Please send a video file first!")
        return
    
    try:
        status_msg = await message.reply_text("📥 Downloading subtitle...")
        
        # Download subtitle
        sub_path = await message.download(
            file_name=f"sub_{chat_id}_{int(time.time())}.srt"
        )
        
        await status_msg.edit_text("🔄 Processing video with subtitles...")
        
        # Get video path
        video_path = user_data[chat_id]['video_path']
        output_path = f"merged_{chat_id}_{int(time.time())}.mp4"
        
        logger.info(f"Starting FFmpeg processing for {chat_id}")
        
        # Merge using ffmpeg
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', f"subtitles={sub_path}",
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-c:a', 'copy',
            '-y', output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0 and os.path.exists(output_path):
            await status_msg.edit_text("📤 Uploading processed video...")
            
            # Send the merged video
            await client.send_video(
                chat_id=chat_id,
                video=output_path,
                caption="✅ **Video with subtitles merged successfully!**"
            )
            
            await status_msg.delete()
            logger.info(f"Video processed successfully for {chat_id}")
            
        else:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"FFmpeg error for {chat_id}: {error_msg}")
            await status_msg.edit_text("❌ Failed to process video")
        
        # Cleanup files
        for file_path in [video_path, sub_path, output_path]:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
        
        # Clear user data
        if chat_id in user_data:
            del user_data[chat_id]
            
    except Exception as e:
        logger.error(f"Subtitle processing error for {chat_id}: {e}")
        await message.reply_text("❌ An error occurred during processing")
        
        # Cleanup on error
        if chat_id in user_data:
            video_path = user_data[chat_id].get('video_path')
            if video_path and os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except:
                    pass
            del user_data[chat_id]

# ---------- Main Application ----------
async def main():
    """Main application runner"""
    health_runner = None
    
    try:
        # Start health server
        logger.info("🚀 Starting health check server...")
        health_runner = await start_health_server()
        
        # Start the bot
        logger.info("🤖 Starting Telegram Bot...")
        await app.start()
        
        # Get bot info
        me = await app.get_me()
        logger.info(f"✅ Bot @{me.username} is now ONLINE!")
        logger.info("📱 Bot is ready to receive messages...")
        
        # Keep the application running
        await asyncio.Future()  # Run forever
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        logger.info("🔄 Shutting down...")
        try:
            await app.stop()
            if health_runner:
                await health_runner.cleanup()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

if __name__ == "__main__":
    print("=" * 50)
    print("🎬 SUBTITLE MERGE BOT")
    print("=" * 50)
    print("📦 Max Size: 2GB")
    print("🌐 Health Check: Port 8080")
    print("=" * 50)
    
    # Run the application
    asyncio.run(main())
