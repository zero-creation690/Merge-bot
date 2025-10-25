#!/usr/bin/env python3
"""
🎬 Filmzi Subtitle Burner Bot
High-performance Telegram bot for burning permanent subtitles into videos
All-in-one script for Koyeb deployment
"""

import os
import asyncio
import logging
import tempfile
import aiofiles
import aiohttp
from datetime import datetime
from typing import Dict, Optional, Tuple
from pathlib import Path

# Third-party imports
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import MessageMediaType
import ffmpeg
from motor.motor_asyncio import AsyncIOMotorClient

# Environment variables for Koyeb
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/filmzi_bot")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "4294967296"))  # 4GB default
PORT = int(os.getenv("PORT", "8000"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MongoDB:
    """MongoDB database handler"""
    def __init__(self):
        self.client = None
        self.db = None
        
    async def connect(self):
        """Connect to MongoDB"""
        self.client = AsyncIOMotorClient(MONGODB_URI)
        self.db = self.client.get_database()
        await self._create_indexes()
        
    async def _create_indexes(self):
        """Create database indexes"""
        await self.db.users.create_index("user_id", unique=True)
        await self.db.videos.create_index("file_id")
        await self.db.videos.create_index("user_id")
        await self.db.thumbnails.create_index("user_id")
        
    async def close(self):
        """Close database connection"""
        if self.client:
            self.client.close()
            
    async def save_user(self, user_id: int, username: str = None):
        """Save or update user data"""
        await self.db.users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "username": username,
                    "last_active": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                },
                "$setOnInsert": {"created_at": datetime.utcnow()}
            },
            upsert=True
        )
    
    async def save_video_metadata(self, file_id: str, user_id: int, original_name: str, 
                                 processed_name: str, subtitle_file: str, thumbnail: str = None):
        """Save video processing metadata"""
        await self.db.videos.insert_one({
            "file_id": file_id,
            "user_id": user_id,
            "original_name": original_name,
            "processed_name": processed_name,
            "subtitle_file": subtitle_file,
            "thumbnail": thumbnail,
            "processed_at": datetime.utcnow()
        })
    
    async def save_thumbnail(self, user_id: int, thumbnail_data: bytes):
        """Save user's custom thumbnail"""
        await self.db.thumbnails.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "thumbnail_data": thumbnail_data,
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )
    
    async def get_thumbnail(self, user_id: int) -> Optional[bytes]:
        """Get user's custom thumbnail"""
        doc = await self.db.thumbnails.find_one({"user_id": user_id})
        return doc.get("thumbnail_data") if doc else None

class ProgressTracker:
    """Track and display progress for download, burn, and upload"""
    def __init__(self, client: Client, chat_id: int, message_id: int = None):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.download_progress = 0
        self.burn_progress = 0
        self.upload_progress = 0
        
    async def create_progress_message(self):
        """Create initial progress message"""
        text = self._format_progress_text()
        message = await self.client.send_message(self.chat_id, text)
        self.message_id = message.id
        return self.message_id
    
    async def update_progress(self, stage: str, progress: float):
        """Update progress for specific stage"""
        if stage == "download":
            self.download_progress = progress
        elif stage == "burn":
            self.burn_progress = progress
        elif stage == "upload":
            self.upload_progress = progress
            
        text = self._format_progress_text()
        try:
            await self.client.edit_message_text(
                self.chat_id, self.message_id, text
            )
        except Exception as e:
            logger.warning(f"Failed to update progress: {e}")
    
    def _format_progress_text(self) -> str:
        """Format progress text with bars"""
        def create_bar(progress, width=20):
            filled = int(width * progress / 100)
            return "█" * filled + "░" * (width - filled)
        
        return (
            "🎬 **Filmzi Subtitle Burner**\n\n"
            f"📥 Download: `{create_bar(self.download_progress)} {self.download_progress:.1f}%`\n"
            f"🔥 Burning: `{create_bar(self.burn_progress)} {self.burn_progress:.1f}%`\n"
            f"📤 Upload: `{create_bar(self.upload_progress)} {self.upload_progress:.1f}%`\n\n"
            "⏳ Processing your video..."
        )

class VideoProcessor:
    """Handle video processing with FFmpeg"""
    def __init__(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        
    async def burn_subtitles(self, video_path: Path, subtitle_path: Path, 
                           output_path: Path, progress_callback=None) -> bool:
        """Burn subtitles permanently into video"""
        try:
            # Determine subtitle format and set appropriate options
            subtitle_str = str(subtitle_path)
            if subtitle_path.suffix.lower() == '.ass':
                # For ASS subtitles, use the ass filter
                stream = ffmpeg.input(str(video_path))
                audio = stream.audio
                video = stream.video.filter('ass', subtitle_str)
            else:
                # For SRT and other formats, use subtitles filter
                stream = ffmpeg.input(str(video_path))
                audio = stream.audio
                video = stream.video.filter('subtitles', subtitle_str)
            
            # Output configuration for high quality
            output = ffmpeg.output(
                video, audio, str(output_path),
                vcodec='libx264',
                crf=18,  # High quality
                preset='medium',
                acodec='aac',
                audio_bitrate='192k',
                movflags='+faststart'  # For web optimization
            )
            
            # Run FFmpeg
            process = output.run_async(overwrite_output=True)
            
            # Simulate progress updates (FFmpeg progress parsing is complex)
            for i in range(101):
                if progress_callback:
                    await progress_callback(i)
                await asyncio.sleep(0.1)  # Simulate processing time
                
            process.wait()
            return True
            
        except Exception as e:
            logger.error(f"FFmpeg error: {e}")
            return False
    
    async def extract_thumbnail(self, video_path: Path, output_path: Path, time_sec: int = 10):
        """Extract thumbnail from video at specific time"""
        try:
            (
                ffmpeg
                .input(str(video_path), ss=time_sec)
                .output(str(output_path), vframes=1)
                .overwrite_output()
                .run(quiet=True)
            )
            return True
        except Exception as e:
            logger.error(f"Thumbnail extraction error: {e}")
            return False
    
    def cleanup(self):
        """Clean up temporary files"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

class FilmziBot:
    """Main bot class"""
    def __init__(self):
        self.app = Client(
            "filmzi_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN
        )
        self.db = MongoDB()
        self.user_states = {}  # Track user states for rename/thumbnail operations
        
    async def start_bot(self):
        """Start the bot"""
        # Connect to database
        await self.db.connect()
        
        # Register handlers
        self.register_handlers()
        
        # Start health check server
        asyncio.create_task(self.start_health_check())
        
        # Start the bot
        await self.app.start()
        logger.info("🎬 Filmzi Bot Started Successfully!")
        await idle()
        await self.app.stop()
        await self.db.close()

    def register_handlers(self):
        """Register all message handlers"""
        
        @self.app.on_message(filters.command("start"))
        async def start_command(client, message: Message):
            """Handle /start command"""
            user = message.from_user
            await self.db.save_user(user.id, user.username)
            
            welcome_text = (
                "🎬 **Welcome to Filmzi Subtitle Burner!**\n\n"
                "I can burn permanent subtitles into your videos.\n\n"
                "**How to use:**\n"
                "1. Send me a video file (up to 4GB)\n"
                "2. Send a subtitle file (.srt or .ass)\n"
                "3. I'll process it and send back with burned subtitles\n\n"
                "**Extra features:**\n"
                "• Rename output files\n"
                "• Custom thumbnails\n"
                "• High-quality processing"
            )
            
            await message.reply_text(welcome_text)
        
        @self.app.on_message(filters.video | filters.document)
        async def handle_video(client, message: Message):
            """Handle incoming videos"""
            try:
                user_id = message.from_user.id
                await self.db.save_user(user_id, message.from_user.username)
                
                # Check if it's a video
                if message.video:
                    file_size = message.video.file_size
                    file_name = message.video.file_name or "video.mp4"
                elif message.document:
                    # Check if it's a video file
                    mime_type = message.document.mime_type or ""
                    if not mime_type.startswith('video/'):
                        return
                    file_size = message.document.file_size
                    file_name = message.document.file_name or "video.mp4"
                else:
                    return
                
                # Check file size
                if file_size > MAX_FILE_SIZE:
                    await message.reply_text(
                        f"❌ File too large! Maximum size is {MAX_FILE_SIZE // 1024 // 1024}MB"
                    )
                    return
                
                # Store video info in user state
                self.user_states[user_id] = {
                    'video_message': message,
                    'video_file_name': file_name,
                    'video_size': file_size,
                    'waiting_for_subtitle': True
                }
                
                await message.reply_text(
                    "📹 Video received! Now please send me the subtitle file (.srt or .ass)"
                )
                
            except Exception as e:
                logger.error(f"Error handling video: {e}")
                await message.reply_text("❌ Error processing video. Please try again.")
        
        @self.app.on_message(filters.document & filters.private)
        async def handle_subtitle(client, message: Message):
            """Handle subtitle files"""
            try:
                user_id = message.from_user.id
                user_state = self.user_states.get(user_id, {})
                
                if not user_state.get('waiting_for_subtitle'):
                    return
                
                # Check if it's a subtitle file
                file_name = message.document.file_name or ""
                if not file_name.lower().endswith(('.srt', '.ass')):
                    await message.reply_text("❌ Please send a .srt or .ass subtitle file")
                    return
                
                # Update user state
                self.user_states[user_id]['subtitle_message'] = message
                self.user_states[user_id]['waiting_for_subtitle'] = False
                self.user_states[user_id]['waiting_for_rename'] = True
                
                # Ask for custom filename
                original_name = user_state['video_file_name']
                suggested_name = original_name.replace('.', '_subbed.')
                
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Use Default Name", callback_data="use_default_name")
                ]])
                
                await message.reply_text(
                    f"📝 **Rename Output File**\n\n"
                    f"Original: `{original_name}`\n"
                    f"Suggested: `{suggested_name}`\n\n"
                    "Send me a new filename or click the button below:",
                    reply_markup=keyboard
                )
                
            except Exception as e:
                logger.error(f"Error handling subtitle: {e}")
                await message.reply_text("❌ Error processing subtitle. Please try again.")
        
        @self.app.on_message(filters.text & filters.private)
        async def handle_text(client, message: Message):
            """Handle text messages for renaming"""
            try:
                user_id = message.from_user.id
                user_state = self.user_states.get(user_id, {})
                
                if user_state.get('waiting_for_rename'):
                    # User sent a custom filename
                    custom_name = message.text.strip()
                    if not custom_name.endswith('.mp4'):
                        custom_name += '.mp4'
                    
                    self.user_states[user_id]['output_filename'] = custom_name
                    self.user_states[user_id]['waiting_for_rename'] = False
                    
                    # Ask for thumbnail
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("Auto-generate Thumbnail", callback_data="auto_thumbnail")
                    ]])
                    
                    await message.reply_text(
                        "🖼️ **Thumbnail Selection**\n\n"
                        "Send me a custom thumbnail image or click below to auto-generate:",
                        reply_markup=keyboard
                    )
                
                elif user_state.get('waiting_for_thumbnail'):
                    # This would handle thumbnail sent as photo
                    pass
                    
            except Exception as e:
                logger.error(f"Error handling text: {e}")
        
        @self.app.on_callback_query()
        async def handle_callbacks(client, callback_query):
            """Handle inline keyboard callbacks"""
            try:
                user_id = callback_query.from_user.id
                data = callback_query.data
                
                if data == "use_default_name":
                    user_state = self.user_states.get(user_id, {})
                    original_name = user_state['video_file_name']
                    suggested_name = original_name.replace('.', '_subbed.')
                    
                    self.user_states[user_id]['output_filename'] = suggested_name
                    self.user_states[user_id]['waiting_for_rename'] = False
                    
                    # Ask for thumbnail
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("Auto-generate Thumbnail", callback_data="auto_thumbnail")
                    ]])
                    
                    await callback_query.message.edit_text(
                        "🖼️ **Thumbnail Selection**\n\n"
                        "Send me a custom thumbnail image or click below to auto-generate:",
                        reply_markup=keyboard
                    )
                
                elif data == "auto_thumbnail":
                    # Process with auto-generated thumbnail
                    await self.process_video_with_subtitles(user_id)
                    
                await callback_query.answer()
                
            except Exception as e:
                logger.error(f"Callback error: {e}")
                await callback_query.answer("Error processing request", show_alert=True)
        
        @self.app.on_message(filters.photo & filters.private)
        async def handle_thumbnail(client, message: Message):
            """Handle custom thumbnail images"""
            try:
                user_id = message.from_user.id
                user_state = self.user_states.get(user_id, {})
                
                if not user_state:
                    return
                
                # Download thumbnail
                processor = VideoProcessor()
                thumb_path = processor.temp_dir / "custom_thumb.jpg"
                
                progress_msg = await message.reply_text("📥 Downloading thumbnail...")
                
                await message.download(str(thumb_path))
                
                # Save thumbnail to database
                async with aiofiles.open(thumb_path, 'rb') as f:
                    thumb_data = await f.read()
                await self.db.save_thumbnail(user_id, thumb_data)
                
                await progress_msg.delete()
                await message.reply_text("✅ Thumbnail saved! Starting video processing...")
                
                # Start video processing
                await self.process_video_with_subtitles(user_id, custom_thumb=str(thumb_path))
                
            except Exception as e:
                logger.error(f"Thumbnail error: {e}")
                await message.reply_text("❌ Error processing thumbnail")
    
    async def process_video_with_subtitles(self, user_id: int, custom_thumb: str = None):
        """Main video processing function"""
        processor = VideoProcessor()
        progress_tracker = None
        
        try:
            user_state = self.user_states.get(user_id, {})
            if not user_state:
                return
            
            video_msg = user_state['video_message']
            subtitle_msg = user_state.get('subtitle_message')
            output_filename = user_state.get('output_filename', 'output.mp4')
            
            # Create progress message
            progress_tracker = ProgressTracker(self.app, user_id)
            await progress_tracker.create_progress_message()
            
            # Download files
            await progress_tracker.update_progress("download", 10)
            
            video_path = processor.temp_dir / "input_video.mp4"
            subtitle_path = processor.temp_dir / "subtitle"
            output_path = processor.temp_dir / output_filename
            
            # Download video
            await video_msg.download(str(video_path))
            await progress_tracker.update_progress("download", 40)
            
            # Download subtitle
            if subtitle_msg:
                subtitle_ext = Path(subtitle_msg.document.file_name).suffix
                subtitle_path = subtitle_path.with_suffix(subtitle_ext)
                await subtitle_msg.download(str(subtitle_path))
            
            await progress_tracker.update_progress("download", 70)
            
            # Burn subtitles
            await progress_tracker.update_progress("burn", 10)
            
            success = await processor.burn_subtitles(
                video_path, subtitle_path, output_path,
                progress_callback=lambda p: progress_tracker.update_progress("burn", p)
            )
            
            if not success:
                raise Exception("Subtitle burning failed")
            
            await progress_tracker.update_progress("burn", 100)
            
            # Handle thumbnail
            thumb_path = None
            if custom_thumb:
                thumb_path = Path(custom_thumb)
            else:
                # Auto-generate thumbnail
                thumb_path = processor.temp_dir / "auto_thumb.jpg"
                await processor.extract_thumbnail(output_path, thumb_path)
            
            await progress_tracker.update_progress("upload", 10)
            
            # Upload processed video
            await self.app.send_chat_action(user_id, "upload_video")
            
            upload_progress_callback = lambda current, total: asyncio.create_task(
                progress_tracker.update_progress("upload", (current / total) * 100)
            )
            
            # Send the processed video
            await self.app.send_video(
                chat_id=user_id,
                video=str(output_path),
                thumb=str(thumb_path) if thumb_path.exists() else None,
                caption=f"🎬 **Processed with Filmzi Bot**\n📁 `{output_filename}`",
                file_name=output_filename,
                progress=upload_progress_callback
            )
            
            await progress_tracker.update_progress("upload", 100)
            
            # Save metadata
            await self.db.save_video_metadata(
                file_id=str(output_path),  # In real implementation, use actual file_id
                user_id=user_id,
                original_name=user_state['video_file_name'],
                processed_name=output_filename,
                subtitle_file=subtitle_path.name,
                thumbnail="custom" if custom_thumb else "auto"
            )
            
            # Cleanup user state
            if user_id in self.user_states:
                del self.user_states[user_id]
                
        except Exception as e:
            logger.error(f"Processing error: {e}")
            if progress_tracker:
                await self.app.send_message(user_id, f"❌ Processing failed: {str(e)}")
        finally:
            processor.cleanup()
    
    async def start_health_check(self):
        """Start health check server on port 8000"""
        from aiohttp import web
        
        async def health_check(request):
            return web.json_response({
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "service": "filmzi-bot"
            })
        
        app = web.Application()
        app.router.add_get('/health', health_check)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        
        logger.info(f"✅ Health check server running on port {PORT}")

async def main():
    """Main entry point"""
    # Validate required environment variables
    required_vars = ['BOT_TOKEN', 'API_ID', 'API_HASH']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return
    
    bot = FilmziBot()
    await bot.start_bot()

if __name__ == "__main__":
    # Create event loop and run
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
