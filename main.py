#!/usr/bin/env python3
"""
Ultra Super AutoFilter Subtitle Bot
- Auto detects videos & .srt subtitles
- Real-time progress: download, burn, upload
- Supports up to 4GB
- Auto cleans files
- Small progress bars, fixed ETA
- Supports Sinhala, Tamil, Hindi, English, and other Unicode
"""

import os, time, asyncio, secrets, logging, subprocess
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", 4294967296))  # 4GB
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/ultra_autobot")
os.makedirs(CACHE_DIR, exist_ok=True)
WORKERS = 4

# Fonts supporting multiple languages
FONTS = {
    "sinhala": "/usr/share/fonts/truetype/sinhala/FMAbhaya.ttf",
    "tamil": "/usr/share/fonts/truetype/tamil/Latha.ttf",
    "hindi": "/usr/share/fonts/truetype/hindi/Mangal.ttf",
    "english": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "default": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=WORKERS)
user_data = {}

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
    def log_message(self, format, *args): return

threading.Thread(target=lambda: HTTPServer(("0.0.0.0",8000),HealthHandler).serve_forever(), daemon=True).start()

# ---------------- APP ----------------
app = Client("UltraAutoBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------------- HELPERS ----------------
def human_readable(size:int)->str:
    for unit in ["B","KB","MB","GB"]:
        if size<1024: return f"{size:.1f} {unit}"; size/=1024
    return f"{size:.1f} GB"

def format_time(seconds:float)->str:
    seconds=int(seconds)
    if seconds<60: return f"{seconds}s"
    elif seconds<3600: return f"{seconds//60}m {seconds%60}s"
    else: return f"{seconds//3600}h {(seconds%3600)//60}m"

def detect_language(sub_file:str)->str:
    """Detect language in the subtitle file by simple character check"""
    try:
        with open(sub_file,"r",encoding="utf-8") as f:
            content=f.read()
        if any('\u0d80' <= c <= '\u0dff' for c in content): return "sinhala"
        if any('\u0b80' <= c <= '\u0bff' for c in content): return "tamil"
        if any('\u0900' <= c <= '\u097f' for c in content): return "hindi"
        if any(c.isascii() for c in content): return "english"
        return "default"
    except:
        return "default"

def get_font(language:str)->str:
    return FONTS.get(language,FONTS["default"])

# ---------------- PROGRESS ----------------
class SmoothProgress:
    def __init__(self, client, chat_id, message_id, filename, action="PROCESS"):
        self.client=client
        self.chat_id=chat_id
        self.message_id=message_id
        self.filename=filename
        self.action=action
        self.start_time=time.time()
        self.last_update=0

    async def update(self, current, total):
        now=time.time()
        if now-self.last_update<0.3 and current<total: return
        self.last_update=now
        elapsed=now-self.start_time
        speed=(current/elapsed)/(1024*1024) if elapsed>0 else 0.01
        speed=max(min(speed,20),0.01)
        percent=(current*100/total) if total else 0
        bar_len=10 if self.action=="BURN" else 15
        filled=int(bar_len*percent/100)
        bar="█"*filled+"░"*(bar_len-filled)
        eta=(total-current)/(speed*1024*1024) if current>0 else 0
        text=f"⚡ **{self.action}** | `{bar}` {percent:.1f}%\nSpeed: {speed:.1f} MB/s | ETA: `{format_time(eta)}`\n`{self.filename[:25]}`"
        try: await self.client.edit_message_text(self.chat_id,self.message_id,text)
        except: pass

# ---------------- COMMANDS ----------------
@app.on_message(filters.command("start"))
async def start_cmd(client,message:Message):
    await message.reply_text(
        "🚀 **SUPER ULTRA AUTOFILTER SUBTITLE BOT**\n"
        "Send video → then .srt subtitle.\nSupports Sinhala, Tamil, English, Hindi. Up to 4GB."
    )

@app.on_message(filters.command("cancel"))
async def cancel_cmd(client,message:Message):
    chat_id=message.chat.id
    if chat_id in user_data:
        for f in ["video","subtitle","output"]:
            fp=user_data[chat_id].get(f)
            if fp and os.path.exists(fp): os.remove(fp)
        del user_data[chat_id]
        await message.reply_text("✅ Cancelled & cleaned!")
    else: await message.reply_text("❌ No active operation.")

# ---------------- FILE HANDLER ----------------
@app.on_message(filters.video|filters.document)
async def file_handler(client,message:Message):
    chat_id=message.chat.id
    if message.video: file_obj=message.video
    else:
        file_obj=message.document
        if file_obj.file_name.lower().endswith(".srt"):
            await handle_subtitle(client,message)
            return

    if file_obj.file_size>MAX_FILE_SIZE:
        await message.reply_text(f"❌ Too large! Max {human_readable(MAX_FILE_SIZE)}")
        return

    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text("⚠️ Video uploaded, send subtitle now.")
        return

    unique=secrets.token_hex(6)
    ext=os.path.splitext(file_obj.file_name or "video.mp4")[1] or ".mp4"
    path=os.path.join(CACHE_DIR,f"v_{unique}{ext}")
    msg=await message.reply_text("🚀 Downloading video...")
    progress=SmoothProgress(client,chat_id,msg.id,file_obj.file_name,"DOWNLOAD")
    start=time.time()
    video_path=await message.download(file_name=path, progress=progress.update)
    elapsed=time.time()-start
    user_data[chat_id]={"video":video_path,"filename":file_obj.file_name,"start_time":time.time()}
    await msg.edit_text(f"✅ Video downloaded ({format_time(elapsed)}). Send .srt subtitle.")

async def handle_subtitle(client,message:Message):
    chat_id=message.chat.id
    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text("⚠️ Send video first!"); return
    sub_obj=message.document
    if not sub_obj.file_name.lower().endswith(".srt"):
        await message.reply_text("❌ Send valid .srt subtitle!"); return

    msg=await message.reply_text("🚀 Downloading subtitle...")
    unique=secrets.token_hex(6)
    sub_path=os.path.join(CACHE_DIR,f"s_{unique}.srt")
    progress=SmoothProgress(client,chat_id,msg.id,sub_obj.file_name,"DOWNLOAD")
    sub_file=await message.download(file_name=sub_path, progress=progress.update)
    
    await msg.edit_text("✅ Subtitle downloaded. Starting TURBO BURN...")

    video_path=user_data[chat_id]["video"]
    output_file=os.path.join(CACHE_DIR,f"burned_{unique}.mp4")
    burn_progress=SmoothProgress(client,chat_id,msg.id,"BURN","BURN")

    language = detect_language(sub_file)
    font_path = get_font(language)

    def ffmpeg_burn():
        vf=f"subtitles='{sub_file}':force_style='FontName={font_path},FontSize=24,PrimaryColour=&H00FFFFFF&,OutlineColour=&H00000000&'"
        cmd=["ffmpeg","-i",video_path,"-vf",vf,"-c:v","libx264","-preset","ultrafast","-crf","24","-c:a","aac","-b:a","128k","-movflags","+faststart","-y",output_file]
        subprocess.run(cmd,check=True)

    loop=asyncio.get_event_loop()
    burn_task=loop.run_in_executor(executor, ffmpeg_burn)

    async def burn_sim():
        start=time.time()
        while not burn_task.done():
            elapsed=time.time()-start
            percent=min(elapsed/10*100,99)
            await burn_progress.update(percent,0)
            await asyncio.sleep(0.3)
        await burn_progress.update(100,0)

    await asyncio.gather(burn_task,burn_sim())
    await msg.edit_text("🚀 TURBO BURN COMPLETE! Uploading...")

    upload_progress=SmoothProgress(client,chat_id,msg.id,"UPLOAD","UPLOAD")
    start_upload=time.time()
    await client.send_video(chat_id,output_file,caption="🔥 Subtitles permanently burned!",progress=upload_progress.update)
    elapsed_upload=time.time()-start_upload
    await msg.edit_text(f"✅ Upload complete ({format_time(elapsed_upload)})")

    for f in [video_path,sub_file,output_file]:
        if os.path.exists(f): os.remove(f)
    del user_data[chat_id]

# ---------------- RUN BOT ----------------
if __name__=="__main__":
    print("🚀 SUPER ULTRA AUTOFILTER SUBTITLE BOT STARTED")
    app.run()
