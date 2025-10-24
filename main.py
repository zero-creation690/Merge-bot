#!/usr/bin/env python3
"""
Ultra Turbo Subtitle Burner Bot
Supports videos up to 4GB, fast burn and upload

Requirements:
  pip install pyrogram aiofiles

System requirements:
  ffmpeg + ffprobe installed
  Python 3.10+
"""

import os
import time
import asyncio
import secrets
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", 4294967296))  # 4GB
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/ultra_bot")
os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- APP ----------------
app = Client(
    "UltraTurboBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

user_data = {}
executor = ThreadPoolExecutor(max_workers=4)

# ---------------- HELPERS ----------------
def human_readable(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

def format_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"

# ---------------- PROGRESS ----------------
class TurboProgress:
    """Single progress message showing TURBO BURN."""
    def __init__(self, client, chat_id, message_id):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id

    async def update(self, percent: float):
        filled_len = int(percent // 10)
        bar = "🔥" * filled_len + "░" * (10 - filled_len)
        eta = max(int((100 - percent) * 0.08), 1)
        text = f"⚙️ **TURBO BURN** • **3.0x**{bar} **{percent:.1f}%** • ETA: {eta}s\n**Burning subtitles into video...**"
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except: pass

# ---------------- COMMANDS ----------------
@app.on_message(filters.command("start"))
async def start(client, message):
    text = (
        "🚀 **ULTRA TURBO SUBTITLE BOT** 🚀\n\n"
        "📋 **How to use:**\n"
        "1️⃣ Send video file (MP4, MKV, etc.)\n"
        "2️⃣ Send .srt subtitle\n"
        "3️⃣ Receive video with burned subtitles!\n\n"
        f"⚡ Max file size: {human_readable(MAX_FILE_SIZE)}"
    )
    await message.reply_text(text)

@app.on_message(filters.command("cancel"))
async def cancel(client, message):
    chat_id = message.chat.id
    if chat_id in user_data:
        for f in ["video", "subtitle", "output"]:
            fp = user_data[chat_id].get(f)
            if fp and os.path.exists(fp):
                try: os.remove(fp)
                except: pass
        del user_data[chat_id]
        await message.reply_text("✅ **Cancelled and cleaned!**")
    else:
        await message.reply_text("❌ **No active operation.**")

# ---------------- FILE HANDLER ----------------
@app.on_message(filters.video | filters.document)
async def handle_file(client, message):
    chat_id = message.chat.id
    if message.video:
        file_obj = message.video
    else:
        file_obj = message.document
        if file_obj.file_name.lower().endswith(".srt"):
            await handle_subtitle(client, message)
            return

    if file_obj.file_size > MAX_FILE_SIZE:
        await message.reply_text(f"❌ Too large! Max {human_readable(MAX_FILE_SIZE)}")
        return

    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text("⚠️ Video already uploaded, send subtitle (.srt) now.")
        return

    unique = secrets.token_hex(6)
    ext = os.path.splitext(file_obj.file_name or "video.mp4")[1] or ".mp4"
    path = os.path.join(CACHE_DIR, f"v_{unique}{ext}")

    msg = await message.reply_text("🚀 Downloading video...")
    start_time = time.time()
    video_path = await message.download(file_name=path)
    elapsed = time.time() - start_time

    user_data[chat_id] = {"video": video_path, "filename": file_obj.file_name, "start_time": time.time()}
    await msg.edit_text(f"✅ Download complete ({format_time(elapsed)}). Now send .srt subtitle.")

async def handle_subtitle(client, message):
    chat_id = message.chat.id
    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text("⚠️ Please send video first!")
        return

    sub_obj = message.document
    if not sub_obj.file_name.lower().endswith(".srt"):
        await message.reply_text("❌ Invalid file. Send .srt subtitle.")
        return

    msg = await message.reply_text("🚀 Downloading subtitle...")
    unique = secrets.token_hex(6)
    sub_path = os.path.join(CACHE_DIR, f"s_{unique}.srt")
    sub_file = await message.download(file_name=sub_path)
    await msg.edit_text("✅ Subtitle downloaded. Starting TURBO BURN...")

    video_path = user_data[chat_id]["video"]
    output_file = os.path.join(CACHE_DIR, f"burned_{unique}.mp4")

    # Start ffmpeg burn
    progress = TurboProgress(client, chat_id, msg.id)

    def ffmpeg_task():
        vf = f"subtitles='{sub_file}':force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF&,OutlineColour=&H00000000&'"
        cmd = [
            "ffmpeg", "-i", video_path, "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-y", output_file
        ]
        subprocess.run(cmd, check=True)

    # Run ffmpeg in executor
    loop = asyncio.get_event_loop()
    burn_task = loop.run_in_executor(executor, ffmpeg_task)

    # Simulate fast progress (~8-10s)
    async def progress_sim():
        start = time.time()
        while not burn_task.done():
            elapsed = time.time() - start
            percent = min(elapsed / 8 * 100, 99)
            await progress.update(percent)
            await asyncio.sleep(0.5)
        await progress.update(100)

    await asyncio.gather(burn_task, progress_sim())

    # Upload
    await msg.edit_text("🚀 TURBO BURN COMPLETE! Uploading...")
    await client.send_video(chat_id, output_file, caption="🔥 Subtitles permanently burned!")

    # Cleanup
    for f in [video_path, sub_file, output_file]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass
    if chat_id in user_data:
        del user_data[chat_id]

# ---------------- RUN BOT ----------------
if __name__ == "__main__":
    print("🚀 ULTRA TURBO SUBTITLE BOT STARTED")
    app.run()
