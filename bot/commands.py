from pyrogram import Client, filters
from pyrogram.types import Message
from config import ADMIN_IDS
from utils.helpers import human_readable, cleanup_files
import os

# Global user data storage
user_data = {}

async def start_command(client: Client, message: Message):
    welcome_text = (
        "🚀 **ULTRA FAST SUBTITLE BOT** 🚀\n\n"
        "⚡ **Features:**\n"
        "• **High download speed** (depends on host)\n"
        "• **Real-time burning** progress\n"
        "• **Any format** to MP4\n"
        "• **Permanent** subtitle burning\n"
        "• **Unicode Support** (Sinhala, Tamil, English)\n"
        "• **2GB** max file size (configurable)\n\n"
        "📋 **How to use:**\n"
        "1. Send video file\n"
        "2. Send .srt subtitle file\n"
        "3. Receive video with burned subtitles!\n\n"
        "🔥 **Ready for ultra speed!**"
    )
    await message.reply_text(welcome_text)

async def help_command(client: Client, message: Message):
    from config import MAX_FILE_SIZE
    help_text = (
        "🆘 **ULTRA FAST GUIDE**\n\n"
        "**Format:** Any → MP4\n"
        "**Subtitles:** Burned permanently\n"
        "**Languages:** Sinhala, Tamil, English (Unicode)\n"
        "**Max Size:** {}\n\n".format(human_readable(MAX_FILE_SIZE)) +
        "**Commands:**\n"
        "`/start` - Start bot\n"
        "`/help` - This guide\n"
        "`/cancel` - Cancel operation and cleanup\n"
        "`/stats` - Bot statistics (Admin)\n"
        "`/broadcast` - Broadcast message (Admin)\n\n"
        "🚀 **Send a video to experience ultra speed!**"
    )
    await message.reply_text(help_text)

async def cancel_command(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id in user_data:
        for key in ["video", "subtitle", "output"]:
            file_path = user_data[chat_id].get(key)
            cleanup_files(file_path)
        del user_data[chat_id]
        await message.reply_text("✅ **Cancelled and cleaned up!**")
    else:
        await message.reply_text("❌ **No active operation!**")

async def stats_command(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply_text("❌ **Admin only command!**")
        return
    
    stats_text = (
        f"📊 **Bot Statistics**\n\n"
        f"• **Active Processes:** {len(user_data)}\n"
        f"• **Total Chats:** {len(user_data)}\n"
        f"• **Max File Size:** {human_readable(MAX_FILE_SIZE)}\n"
    )
    await message.reply_text(stats_text)
