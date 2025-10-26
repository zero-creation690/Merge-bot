#!/usr/bin/env python3
"""
Ultra Fast Subtitle Burner - Multi-file Production Version
"""

import logging
from pyrogram import Client, filters
from config import API_ID, API_HASH, BOT_TOKEN, WORKERS, CACHE_DIR, HEALTH_PORT
from utils.health import init_health_server
from bot.commands import start_command, help_command, cancel_command, stats_command
from admin.broadcast import broadcast_message
from bot.handlers import handle_file
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create cache directory
os.makedirs(CACHE_DIR, exist_ok=True)

# Validate config
if API_ID == 0 or not API_HASH or not BOT_TOKEN:
    logger.error("API_ID, API_HASH and BOT_TOKEN must be set in environment variables.")
    raise SystemExit("Missing Telegram API credentials")

# Initialize health server
init_health_server(HEALTH_PORT)

# Create bot client
app = Client(
    "UltraFastBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=CACHE_DIR,
    workers=WORKERS,
)

# Register command handlers
app.on_message(filters.command("start"))(start_command)
app.on_message(filters.command("help"))(help_command)
app.on_message(filters.command("cancel"))(cancel_command)
app.on_message(filters.command("stats"))(stats_command)
app.on_message(filters.command("broadcast"))(broadcast_message)

# Register file handlers
app.on_message(filters.video | filters.document)(handle_file)

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 ULTRA FAST SUBTITLE BURNER - MULTI-FILE")
    print("=" * 50)
    print(f"⚡ Max Size: {human_readable(MAX_FILE_SIZE)}")
    print(f"🔥 Workers: {WORKERS}")
    print(f"👑 Admins: {len(ADMIN_IDS)}")
    print("🌍 Unicode Support: Sinhala, Tamil, English")
    print("📦 Output: MP4 with burned subtitles")
    print("=" * 50)

    try:
        app.run()
    except KeyboardInterrupt:
        print("Stopping...")
    except Exception as e:
        logger.exception("Bot failed to start")
        print(f"❌ Bot failed to start: {e}")
