#!/usr/bin/env python3
"""
🎬 Filmzi Subtitle Burner Bot
Fixed MongoDB connection and Pyrogram session issues
"""

import os
import asyncio
import logging
import tempfile
import aiofiles
import aiohttp
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path

# Third-party imports
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import ffmpeg
from motor.motor_asyncio import AsyncIOMotorClient

# Environment variables for Koyeb
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/filmzi_bot")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "4294967296"))
PORT = int(os.getenv("PORT", "8000"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MongoDB:
    """MongoDB database handler with fixed connection"""
    def __init__(self):
        self.client = None
        self.db = None
        self.connected = False
        
    async def connect(self):
        """Connect to MongoDB with proper error handling"""
        try:
            logger.info("🔌 Connecting to MongoDB...")
            self.client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            
            # Test connection
            await self.client.admin.command('ping')
            logger.info("✅ MongoDB connection successful")
            
            # Get database name from URI
            if "mongodb.net" in MONGODB_URI:
                db_name = MONGODB_URI.split('/')[-1].split('?')[0]
                if not db_name or db_name == 'test':
                    db_name = "filmzi_bot"
            else:
                db_name = "filmzi_bot"
                
            self.db = self.client[db_name]
            self.connected = True
            
            await self._create_indexes()
            logger.info("✅ Database initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            self.connected = False
            # Don't raise exception, continue without DB
            
    async def _create_indexes(self):
        """Create database indexes"""
        if self.connected:
            try:
                await self.db.users.create_index("user_id", unique=True)
                await self.db.videos.create_index("file_id")
                logger.info("✅ Database indexes created")
            except Exception as e:
                logger.warning(f"Index creation warning: {e}")
        
    async def close(self):
        """Close database connection"""
        if self.client:
            self.client.close()
            logger.info("🔌 MongoDB connection closed")
            
    async def save_user(self, user_id: int, username: str = None):
        """Save or update user data"""
        if not self.connected:
            return
            
        try:
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
        except Exception as e:
            logger.warning(f"Failed to save user: {e}")
    
    async def save_video_metadata(self, file_id: str, user_id: int, original_name: str, 
                                 processed_name: str, subtitle_file: str, thumbnail: str = None):
        """Save video processing metadata"""
        if not self.connected:
            return
            
        try:
            await self.db.videos.insert_one({
                "file_id": file_id,
                "user_id": user_id,
                "original_name": original_name,
                "processed_name": processed_name,
                "subtitle_file": subtitle_file,
                "thumbnail": thumbnail,
                "processed_at": datetime.utcnow()
            })
        except Exception as e:
            logger.warning(f"Failed to save video metadata: {e}")

class ProgressTracker:
    """Track and display progress for download, burn, and upload"""
    def __init__(self, client: Client, chat_id: int):
        self.client = client
        self.chat_id = chat_id
        self.message_id = None
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
        def create_bar(progress, width=10):
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
            logger.info(f"Burning subtitles: {video_path} -> {output_path}")
            
            # Use direct FFmpeg command for reliability
            cmd = [
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vf', f'subtitles={subtitle_path}',
                '-c:v', 'libx264',
                '-crf', '23',
                '-preset', 'medium',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-movflags', '+faststart',
                str(output_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Simulate progress
            for i in range(0, 101, 10):
                if progress_callback:
                    await progress_callback(i)
                await asyncio.sleep(1)
                
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and output_path.exists():
                logger.info("✅ Subtitle burning successful")
                return True
            else:
                logger.error(f"FFmpeg error: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"FFmpeg error: {e}")
            return False
    
    async def extract_thumbnail(self, video_path: Path, output_path: Path, time_sec: int = 10):
        """Extract thumbnail from video at specific time"""
        try:
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-ss', str(time_sec),
                '-vframes', '1',
                '-q:v', '2',
                str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            return output_path.exists()
        except Exception as e:
            logger.error(f"Thumbnail extraction error: {e}")
            return False
    
    def cleanup(self):
        """Clean up temporary files"""
        import shutil
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            logger.warning(f"Cleanup warning: {e}")

class FilmziBot:
    """Main bot class"""
    def __init__(self):
        # Use memory session to avoid file issues
        self.app = Client(
            "filmzi_bot_session",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True  # Critical fix for file permission issues
        )
        self.db = MongoDB()
        self.user_states = {}
        
    async def start_bot(self):
        """Start the bot"""
        try:
            # Connect to database first
            await self.db.connect()
            
            # Start health check server
            asyncio.create_task(self.start_health_check())
            
            # Register handlers
            self.register_handlers()
            
            # Start the bot
            await self.app.start()
            logger.info("🎬 Filmzi Bot Started Successfully!")
            
            # Bot info
            me = await self.app.get_me()
            logger.info(f"🤖 Bot: @{me.username}")
            
            await idle()
            
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Shutdown the bot gracefully"""
        try:
            if self.app.is_connected:
                await self.app.stop()
            await self.db.close()
            logger.info("👋 Bot shutdown complete")
        except Exception as e:
            logger.error(f"Shutdown error: {e}")

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
                "1. Send me a video file\n"
                "2. Send a subtitle file (.srt or .ass)\n"
                "3. I'll process it with burned subtitles\n\n"
                "**Features:**\n"
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
                
                # Store video info
                self.user_states[user_id] = {
                    'video_message': message,
                    'video_file_name': file_name,
                    'video_size': file_size,
                    'waiting_for_subtitle': True
                }
                
                await message.reply_text(
                    "📹 Video received! Now send me the subtitle file (.srt or .ass)"
                )
                
            except Exception as e:
                logger.error(f"Error handling video: {e}")
                await message.reply_text("❌ Error processing video")
        
        @self.app.on_message(filters.document & filters.private)
        async def handle_subtitle(client, message: Message):
            """Handle subtitle files"""
            try:
                user_id = message.from_user.id
                user_state = self.user_states.get(user_id, {})
                
                if not user_state.get('waiting_for_subtitle'):
                    return
                
                file_name = message.document.file_name or ""
                if not file_name.lower().endswith(('.srt', '.ass')):
                    await message.reply_text("❌ Please send a .srt or .ass subtitle file")
                    return
                
                # Update user state
                self.user_states[user_id]['subtitle_message'] = message
                self.user_states[user_id]['waiting_for_subtitle'] = False
                
                original_name = user_state['video_file_name']
                suggested_name = original_name.rsplit('.', 1)[0] + '_subbed.mp4'
                
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Use Default Name", callback_data="use_default_name"),
                    InlineKeyboardButton("Start Processing", callback_data="start_processing")
                ]])
                
                await message.reply_text(
                    f"📝 **Output Filename**\n\n"
                    f"Original: `{original_name}`\n"
                    f"Default: `{suggested_name}`\n\n"
                    "Choose an option:",
                    reply_markup=keyboard
                )
                
            except Exception as e:
                logger.error(f"Error handling subtitle: {e}")
                await message.reply_text("❌ Error processing subtitle")
        
        @self.app.on_callback_query()
        async def handle_callbacks(client, callback_query):
            """Handle inline keyboard callbacks"""
            try:
                user_id = callback_query.from_user.id
                data = callback_query.data
                
                if data == "use_default_name":
                    user_state = self.user_states.get(user_id, {})
                    original_name = user_state['video_file_name']
                    suggested_name = original_name.rsplit('.', 1)[0] + '_subbed.mp4'
                    
                    self.user_states[user_id]['output_filename'] = suggested_name
                    
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("Start Processing", callback_data="start_processing")
                    ]])
                    
                    await callback_query.message.edit_text(
                        f"✅ Using: `{suggested_name}`\n\nClick below to start:",
                        reply_markup=keyboard
                    )
                
                elif data == "start_processing":
                    await callback_query.message.edit_text("🚀 Starting video processing...")
                    await self.process_video_with_subtitles(user_id)
                    
                await callback_query.answer()
                
            except Exception as e:
                logger.error(f"Callback error: {e}")
                await callback_query.answer("Error processing request", show_alert=True)
    
    async def process_video_with_subtitles(self, user_id: int):
        """Main video processing function"""
        processor = VideoProcessor()
        progress_tracker = None
        
        try:
            user_state = self.user_states.get(user_id, {})
            if not user_state:
                await self.app.send_message(user_id, "❌ Session expired. Please start over.")
                return
            
            video_msg = user_state['video_message']
            subtitle_msg = user_state.get('subtitle_message')
            output_filename = user_state.get('output_filename', 'output_subbed.mp4')
            
            # Create progress message
            progress_tracker = ProgressTracker(self.app, user_id)
            await progress_tracker.create_progress_message()
            
            # Setup paths
            video_path = processor.temp_dir / "input_video.mp4"
            subtitle_path = processor.temp_dir / "subtitle"
            output_path = processor.temp_dir / output_filename
            
            # Download video
            await progress_tracker.update_progress("download", 20)
            await video_msg.download(str(video_path))
            
            # Download subtitle
            await progress_tracker.update_progress("download", 60)
            if subtitle_msg and subtitle_msg.document:
                subtitle_ext = Path(subtitle_msg.document.file_name or "subtitle.srt").suffix
                subtitle_path = subtitle_path.with_suffix(subtitle_ext)
                await subtitle_msg.download(str(subtitle_path))
            
            await progress_tracker.update_progress("download", 100)
            
            # Burn subtitles
            await progress_tracker.update_progress("burn", 10)
            
            success = await processor.burn_subtitles(
                video_path, subtitle_path, output_path,
                progress_callback=lambda p: asyncio.create_task(
                    progress_tracker.update_progress("burn", p)
                )
            )
            
            if not success:
                raise Exception("Subtitle burning failed")
            
            await progress_tracker.update_progress("burn", 100)
            
            # Generate thumbnail
            thumb_path = processor.temp_dir / "thumbnail.jpg"
            await processor.extract_thumbnail(output_path, thumb_path)
            
            # Upload processed video
            await progress_tracker.update_progress("upload", 10)
            await self.app.send_chat_action(user_id, "upload_video")
            
            def upload_progress(current, total):
                progress = (current / total) * 80 + 10  # Scale to 10-90%
                asyncio.create_task(progress_tracker.update_progress("upload", progress))
            
            # Send the processed video
            thumb = str(thumb_path) if thumb_path.exists() else None
            await self.app.send_video(
                chat_id=user_id,
                video=str(output_path),
                thumb=thumb,
                caption=f"🎬 **Processed with Filmzi Bot**\n📁 `{output_filename}`",
                file_name=output_filename,
                progress=upload_progress
            )
            
            await progress_tracker.update_progress("upload", 100)
            
            # Save metadata
            await self.db.save_video_metadata(
                file_id=f"processed_{user_id}_{datetime.utcnow().timestamp()}",
                user_id=user_id,
                original_name=user_state['video_file_name'],
                processed_name=output_filename,
                subtitle_file=subtitle_path.name,
                thumbnail="auto"
            )
            
            # Cleanup
            if user_id in self.user_states:
                del self.user_states[user_id]
                
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Processing error: {e}")
            error_msg = f"❌ Processing failed: {str(e)}"
            if progress_tracker and progress_tracker.message_id:
                try:
                    await self.app.edit_message_text(
                        user_id, progress_tracker.message_id, error_msg
                    )
                except:
                    await self.app.send_message(user_id, error_msg)
            else:
                await self.app.send_message(user_id, error_msg)
        finally:
            processor.cleanup()
    
    async def start_health_check(self):
        """Start health check server on port 8000"""
        from aiohttp import web
        
        async def health_check(request):
            status = "healthy" if self.app.is_connected else "starting"
            return web.json_response({
                "status": status,
                "timestamp": datetime.utcnow().isoformat(),
                "service": "filmzi-bot",
                "database": self.db.connected
            })
        
        app = web.Application()
        app.router.add_get('/health', health_check)
        app.router.add_get('/', health_check)
        
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
        logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
        return
    
    if API_ID == 0:
        logger.error("API_ID must be a valid integer")
        return
    
    # Start the bot
    bot = FilmziBot()
    await bot.start_bot()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
