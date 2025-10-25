FILE: bot.py

""" Permanent Subtitle (burn-in) Telegram Bot with Health Check (port 8000) Features:

Accepts video uploads (limit configurable, default 4GB)

Accepts subtitle files (.srt, .ass) and burns them permanent (hard subtitles) using ffmpeg

Progress bars for Download, Burning, Upload phases (single live message)

Simple speed cap (default 10 MB/s) for download/upload enforced in progress callbacks

Health check on port 8000


Environment variables:

BOT_TOKEN, API_ID, API_HASH, MONGODB_URI (optional)

MAX_FILE_SIZE (bytes, optional)

RATE_LIMIT_MB (optional, default 10) — caps download/upload speed in MB/s


"""

import os import asyncio import logging import tempfile import shutil import subprocess from pathlib import Path from typing import Optional

from pyrogram import Client, filters from pyrogram.types import Message import motor.motor_asyncio from aiohttp import web

--- CONFIG ---

BOT_TOKEN = os.getenv('BOT_TOKEN') API_ID = int(os.getenv('API_ID', '0')) API_HASH = os.getenv('API_HASH', '') MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017') MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', str(4 * 1024**3)))  # 4GB default RATE_LIMIT_MB = float(os.getenv('RATE_LIMIT_MB', '10'))  # 10 MB/s default RATE_LIMIT_BPS = RATE_LIMIT_MB * 1024 * 1024

if not BOT_TOKEN or not API_ID or not API_HASH: raise SystemExit('Missing BOT_TOKEN or API_ID/API_HASH environment variables')

Logging

logging.basicConfig(level=logging.INFO) logger = logging.getLogger(name)

Pyrogram client

app = Client('permsub_bot', bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

MongoDB (optional usage here)

mongo = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI) db = mongo.get_database('permsub_db') files_col = db.get_collection('files')

USER_PENDING = {}

--- Utilities for progress and rate limiting ---

_progress_state = {}  # maps (user_id, phase) -> {last_bytes, last_time}

async def rate_limit_sleep(user_id: int, phase: str, current: int): """Simple rate limiter: checks instantaneous speed and sleeps if above RATE_LIMIT_BPS.""" key = (user_id, phase) now = asyncio.get_event_loop().time() state = _progress_state.get(key) if not state: _progress_state[key] = {'last_bytes': current, 'last_time': now} return last = state['last_bytes'] last_t = state['last_time'] delta_bytes = current - last delta_t = now - last_t if delta_t <= 0: return speed = delta_bytes / delta_t  # bytes per sec if speed > RATE_LIMIT_BPS: # compute needed sleep to bring speed to limit approximately excess = speed - RATE_LIMIT_BPS # Sleep proportionally (small) — avoid long sleeps in callback sleep_for = excess / RATE_LIMIT_BPS * 0.1 await asyncio.sleep(sleep_for) # update state _progress_state[key] = {'last_bytes': current, 'last_time': now}

async def edit_status_message(msg: Message, text: str): try: await msg.edit_text(text) except Exception: # ignore edit failures pass

async def progress_callback(current: int, total: int, user_id: int, status_msg: Message, phase: str): try: percent = (current / total * 100) if total else 0 bar_len = 20 filled = int(bar_len * percent / 100) bar = '█' * filled + '─' * (bar_len - filled) text = f"{phase.upper()} | [{bar}] {percent:5.1f}% " # Build combined three-phase view if status_msg contains prior text # We'll preserve previous lines for other phases if present prev = status_msg.text or '' lines = { } # parse previous to keep other phases for line in prev.splitlines(): if 'DOWNLOAD |' in line: lines['DOWNLOAD'] = line elif 'BURNING |' in line: lines['BURNING'] = line elif 'UPLOAD |' in line: lines['UPLOAD'] = line lines[phase.upper()] = text.strip() final = ' '.join([lines.get('DOWNLOAD','DOWNLOAD | [────────────────────]   0.0%'), lines.get('BURNING','BURNING  | [────────────────────]   0.0%'), lines.get('UPLOAD','UPLOAD   | [────────────────────]   0.0%')]) await edit_status_message(status_msg, final) # Apply rate limit if phase is download/upload if phase.lower() in ('download','upload'): await rate_limit_sleep(user_id, phase, current) except Exception as e: logger.debug('progress callback error: %s', e)

Wrap synchronous progress hooks (Pyrogram may call progress sync) — schedule async

def make_progress_hook(user_id: int, status_msg: Message, phase: str): def hook(current, total): asyncio.ensure_future(progress_callback(current, total, user_id, status_msg, phase)) return hook

--- FFmpeg burning with progress parsing ---

async def get_duration_seconds(path: Path) -> float: # use ffprobe proc = await asyncio.create_subprocess_exec('ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE) out, _ = await proc.communicate() try: return float(out.decode().strip()) except Exception: return 0.0

async def burn_subtitles_with_progress(video_path: Path, subtitle_path: Path, output_path: Path, user_id: int, status_msg: Message): duration = await get_duration_seconds(video_path) # ffmpeg -i in -vf subtitles=... -c:a copy out -progress pipe:1 cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'info', '-i', str(video_path), '-vf', f"subtitles='{subtitle_path}'", '-c:a', 'copy', '-progress', 'pipe:1', str(output_path)] proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE) # ffmpeg will write key=value lines to stdout; parse out_time_ms or out_time while True: line = await proc.stdout.readline() if not line: break try: line = line.decode().strip() if line.startswith('out_time_ms='): out_ms = int(line.split('=')[1]) seconds = out_ms / 1_000_000  # out_time_ms in microseconds in some ffmpeg builds percent = (seconds / duration * 100) if duration else 0 await progress_callback(int(percent), 100, user_id, status_msg, 'burning') elif line.startswith('out_time='): # format HH:MM:SS.micro t = line.split('=')[1] parts = t.split(':') secs = 0.0 if len(parts) == 3: secs = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]) percent = (secs / duration * 100) if duration else 0 await progress_callback(int(percent), 100, user_id, status_msg, 'burning') except Exception: continue await proc.wait() if proc.returncode != 0: raise RuntimeError('ffmpeg failed')

--- Handlers ---

@app.on_message(filters.command('start')) async def start_handler(c: Client, m: Message): await m.reply('👋 Send me a video and subtitle file (.srt/.ass) to burn subtitles permanently. Progress for Download/Burning/Upload will be shown.')

@app.on_message(filters.video | filters.document) async def video_handler(c: Client, m: Message): if not (m.video or m.document): return file_size = m.video.file_size if m.video else m.document.file_size if file_size > MAX_FILE_SIZE: await m.reply('❌ File too large (max allowed).') return tmpdir = Path(tempfile.mkdtemp()) vpath = tmpdir / (m.video.file_name if m.video else m.document.file_name or f'video_{m.message_id}.mp4') status_msg = await m.reply('Preparing download... DOWNLOAD | [────────────────────]   0.0% BURNING  | [────────────────────]   0.0% UPLOAD   | [────────────────────]   0.0%') await m.reply('⬇️ Downloading video...') # use progress hook with rate limiting hook = make_progress_hook(m.from_user.id, status_msg, 'download') await m.download(file_name=str(vpath), progress=hook) USER_PENDING[m.from_user.id] = {'video_path': vpath, 'status_msg': status_msg} await status_msg.edit_text('DOWNLOAD | [████████████████████] 100.0% BURNING  | [────────────────────]   0.0% UPLOAD   | [────────────────────]   0.0%') await m.reply('✅ Video saved. Now send subtitle (.srt/.ass) file.')

@app.on_message(filters.document & (filters.file_extension('srt') | filters.file_extension('ass'))) async def subtitle_handler(c: Client, m: Message): user_id = m.from_user.id pending = USER_PENDING.get(user_id) if not pending: await m.reply('❌ Send a video first.') return vpath = pending['video_path'] status_msg = pending['status_msg'] spath = vpath.parent / m.document.file_name await m.reply('⬇️ Downloading subtitle...') await m.download(file_name=str(spath)) out = vpath.parent / f"burned_{vpath.stem}.mp4" await status_msg.edit_text('DOWNLOAD | [████████████████████] 100.0% BURNING  | [────────────────────]   0.0% UPLOAD   | [────────────────────]   0.0%') try: await progress_callback(0, 100, user_id, status_msg, 'burning') await burn_subtitles_with_progress(vpath, spath, out, user_id, status_msg) # mark burning complete await progress_callback(100, 100, user_id, status_msg, 'burning') # Upload with progress await status_msg.edit_text('DOWNLOAD | [████████████████████] 100.0% BURNING  | [████████████████████] 100.0% UPLOAD   | [────────────────────]   0.0%') hook = make_progress_hook(user_id, status_msg, 'upload') await m.reply('⬆️ Uploading final video...') # send_document via client await app.send_document(chat_id=m.chat.id, document=str(out), caption='🎬 Burned subtitles ready!', progress=hook) await progress_callback(100, 100, user_id, status_msg, 'upload') except Exception as e: await m.reply(f'❌ Error: {e}') finally: shutil.rmtree(vpath.parent, ignore_errors=True) USER_PENDING.pop(user_id, None)

--- HEALTH CHECK SERVER ---

async def healthcheck(request): return web.Response(text='OK', status=200)

async def run_web(): app_web = web.Application() app_web.router.add_get('/', healthcheck) runner = web.AppRunner(app_web) await runner.setup() site = web.TCPSite(runner, '0.0.0.0', 8000) await site.start() while True: await asyncio.sleep(3600)

--- MAIN ---

async def main(): await asyncio.gather(app.start(), run_web()) # keep running while True: await asyncio.sleep(3600)

if name == 'main': asyncio.run(main())

