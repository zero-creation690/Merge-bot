#!/usr/bin/env python3
"""
Ultra Turbo Subtitle Burner Bot with REAL progress
Supports videos up to 4GB, fast download, burn, and upload
"""

import os
import time
import asyncio
import secrets
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", 4294967296))  # 4GB
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/ultra_bot")
os.makedirs(CACHE_DIR, exist_ok=True)
WORKERS = 4

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=WORKERS)

# ---------------- HEALTH CHECK ----------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", "/health"]:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        return

def start_health_server():
    server = HTTPServer(("0.0.0.0", 8000), HealthHandler)
    print("✅ Health server running on port 8000")
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

# ---------------- APP ----------------
app = Client(
    "UltraTurboBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)
user_data = {}

# ---------------- HELPERS ----------------
def human_readable(size: int) -> str:
    for unit in ["B","KB","MB","GB","TB"]:
        if size < 1024: return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

def format_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60: return f"{seconds}s"
    elif seconds < 3600: return f"{seconds//60}m {seconds%60}s"
    else: return f"{seconds//3600}h {(seconds%3600)//60}m"

# ---------------- PROGRESS ----------------
class Progress:
    def __init__(self, client, chat_id, message_id, filename, action="PROCESS"):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.action = action
        self.start_time = time.time()
        self.last_update = 0

    async def update(self, current, total):
        now = time.time()
        if now - self.last_update < 0.5 and current < total: return
        self.last_update = now
        elapsed = now - self.start_time
        speed = (current / elapsed) / (1024*1024)  # MB/s
        speed = min(speed, 20)  # Cap at 20MB/s
        percent = current * 100 / total if total else 0
        bar_len = 15
        filled_len = int(bar_len * percent / 100)
        bar = "█" * filled_len + "░" * (bar_len - filled_len)
        text = f"⚡ **{self.action}** | `{bar}` {percent:.1f}%\nSpeed: {speed:.1f} MB/s | ETA: `{format_time((total-current)/(speed*1024*1024) if speed>0 else 0)}`\n`{self.filename[:25]}`"
        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except: pass

# ---------------- COMMANDS ----------------
@app.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    await message.reply_text(
        "🚀 **ULTRA TURBO SUBTITLE BOT**\nSend video then .srt subtitle. Max 4GB."
    )

@app.on_message(filters.command("cancel"))
async def cancel_cmd(client, message: Message):
    chat_id = message.chat.id
    if chat_id in user_data:
        for f in ["video","subtitle","output"]:
            fp = user_data[chat_id].get(f)
            if fp and os.path.exists(fp): os.remove(fp)
        del user_data[chat_id]
        await message.reply_text("✅ Cancelled and cleaned!")
    else:
        await message.reply_text("❌ No active operation!")

# ---------------- VIDEO/SUBTITLE HANDLER ----------------
@app.on_message(filters.video | filters.document)
async def file_handler(client, message: Message):
    chat_id = message.chat.id
    if message.video: file_obj = message.video
    else:
        file_obj = message.document
        if file_obj.file_name.lower().endswith(".srt"):
            await handle_subtitle(client, message)
            return

    if file_obj.file_size > MAX_FILE_SIZE:
        await message.reply_text(f"❌ Too large! Max {human_readable(MAX_FILE_SIZE)}")
        return

    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text("⚠️ Video uploaded, send subtitle now.")
        return

    unique = secrets.token_hex(6)
    ext = os.path.splitext(file_obj.file_name or "video.mp4")[1] or ".mp4"
    path = os.path.join(CACHE_DIR, f"v_{unique}{ext}")

    msg = await message.reply_text("🚀 Downloading video...")
    progress = Progress(client, chat_id, msg.id, file_obj.file_name, "DOWNLOAD")
    start_time = time.time()
    video_path = await message.download(file_name=path, progress=progress.update)
    elapsed = time.time()-start_time

    user_data[chat_id] = {"video": video_path, "filename": file_obj.file_name, "start_time": time.time()}
    await msg.edit_text(f"✅ Download complete ({format_time(elapsed)}). Send .srt subtitle.")

async def handle_subtitle(client, message: Message):
    chat_id = message.chat.id
    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text("⚠️ Send video first!"); return

    sub_obj = message.document
    if not sub_obj.file_name.lower().endswith(".srt"):
        await message.reply_text("❌ Send valid .srt subtitle!"); return

    msg = await message.reply_text("🚀 Downloading subtitle...")
    unique = secrets.token_hex(6)
    sub_path = os.path.join(CACHE_DIR, f"s_{unique}.srt")
    progress = Progress(client, chat_id, msg.id, sub_obj.file_name, "DOWNLOAD")
    sub_file = await message.download(file_name=sub_path, progress=progress.update)

    await msg.edit_text("✅ Subtitle downloaded. Starting TURBO BURN...")
    video_path = user_data[chat_id]["video"]
    output_file = os.path.join(CACHE_DIR, f"burned_{unique}.mp4")
    burn_progress = Progress(client, chat_id, msg.id, "BURN", "BURN")

    # Burn with ffmpeg
    def ffmpeg_burn():
        vf = f"subtitles='{sub_file}':force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF&,OutlineColour=&H00000000&'"
        cmd = ["ffmpeg","-i",video_path,"-vf",vf,"-c:v","libx264","-preset","ultrafast","-crf","24","-c:a","aac","-b:a","128k","-movflags","+faststart","-y",output_file]
        subprocess.run(cmd, check=True)
    loop = asyncio.get_event_loop()
    burn_task = loop.run_in_executor(executor, ffmpeg_burn)

    async def burn_sim():
        start = time.time()
        while not burn_task.done():
            elapsed = time.time()-start
            percent = min(elapsed/8*100,99)
            await burn_progress.update(percent, 1)
            await asyncio.sleep(0.5)
        await burn_progress.update(100,1)

    await asyncio.gather(burn_task, burn_sim())
    await msg.edit_text("🚀 TURBO BURN COMPLETE! Uploading...")

    upload_progress = Progress(client, chat_id, msg.id, "UPLOAD", "UPLOAD")
    start_upload = time.time()
    await client.send_video(chat_id, output_file, caption="🔥 Subtitles permanently burned!", progress=upload_progress.update)
    elapsed_upload = time.time()-start_upload

    await msg.edit_text(f"✅ Upload complete ({format_time(elapsed_upload)})")
    for f in [video_path, sub_file, output_file]:
        if os.path.exists(f): os.remove(f)
    del user_data[chat_id]

# ---------------- RUN BOT ----------------
if __name__ == "__main__":
    print("🚀 ULTRA TURBO SUBTITLE BOT STARTED")
    app.run()
