import os
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters
from pyrogram.types import Message
from config import MAX_FILE_SIZE
from utils.helpers import human_readable, generate_unique_id, cleanup_files, escape_html
from utils.ffmpeg import get_video_duration, burn_subtitles
from bot.progress import UltraProgress, BurningProgress
from bot.commands import user_data
import logging

logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    chat_id = message.chat.id

    file_obj = None
    if message.video:
        file_obj = message.video
    elif message.document:
        file_obj = message.document
        if file_obj.file_name and file_obj.file_name.lower().endswith('.srt'):
            await handle_subtitle(client, message)
            return

    if not file_obj:
        return

    if file_obj.file_size is None:
        await message.reply_text("❌ **Cannot determine file size.**")
        return

    if file_obj.file_size > MAX_FILE_SIZE:
        await message.reply_text(f"❌ **Too large!** Max: {human_readable(MAX_FILE_SIZE)}")
        return

    if chat_id in user_data and "video" in user_data[chat_id]:
        await message.reply_text("⚠️ **Video already received** — send the .srt file now.")
        return

    unique_id = generate_unique_id()
    ext = os.path.splitext(file_obj.file_name or "video.mp4")[1] or ".mp4"
    download_path = os.path.join(CACHE_DIR, f"v_{unique_id}{ext}")

    status_msg = await message.reply_text("🚀 **ULTRA DOWNLOAD STARTED**")
    progress = UltraProgress(client, chat_id, status_msg.id, file_obj.file_name or f"video_{unique_id}", "DOWNLOAD")

    try:
        download_start = time.time()
        video_path = await message.download(file_name=download_path, progress=progress.update)
        download_time = time.time() - download_start
        avg_speed = file_obj.file_size / download_time / (1024 * 1024) if download_time > 0 else 0

        user_data[chat_id] = {
            "video": video_path,
            "filename": file_obj.file_name or os.path.basename(video_path),
            "file_size": file_obj.file_size,
            "start_time": time.time()
        }

        await status_msg.edit_text(
            f"✅ **DOWNLOAD COMPLETE!**\n\n"
            f"🚀 **Speed:** {avg_speed:.1f} MB/s\n"
            f"⏱️ **Time:** {format_time(download_time)}\n\n"
            f"🔥 **Send subtitle file (.srt)**\n"
            f"🌍 **Supports:** Sinhala, Tamil, English"
        )

    except Exception as e:
        logger.exception("Download failed")
        try:
            await status_msg.edit_text(f"❌ **Download failed:** {escape_html(str(e))}")
        except Exception:
            pass
        if chat_id in user_data:
            del user_data[chat_id]

async def handle_subtitle(client: Client, message: Message):
    chat_id = message.chat.id

    if chat_id not in user_data or "video" not in user_data[chat_id]:
        await message.reply_text("⚠️ **Send video first!**")
        return

    sub_obj = message.document
    if not sub_obj or not sub_obj.file_name or not sub_obj.file_name.lower().endswith('.srt'):
        await message.reply_text("❌ **Invalid!** Send a .srt subtitle file.")
        return

    status_msg = await message.reply_text("🚀 **DOWNLOADING SUBTITLE**")
    unique_id = generate_unique_id()
    sub_filename = os.path.join(CACHE_DIR, f"s_{unique_id}.srt")

    progress = UltraProgress(client, chat_id, status_msg.id, sub_obj.file_name, "DOWNLOAD")

    try:
        sub_path = await message.download(file_name=sub_filename, progress=progress.update)

        video_path = user_data[chat_id]["video"]
        original_filename = user_data[chat_id]["filename"]
        base_name = os.path.splitext(original_filename)[0]
        output_filename = f"burned_{unique_id}.mp4"
        output_file = os.path.join(CACHE_DIR, output_filename)

        await status_msg.edit_text("🔍 **Analyzing video...**")
        duration = await asyncio.get_event_loop().run_in_executor(executor, get_video_duration, video_path)

        burn_progress = BurningProgress(client, chat_id, status_msg.id, base_name, duration)
        await status_msg.edit_text("🔥 **STARTING ULTRA BURN**\n`░░░░░░░░░░` **0%**\n🌍 **Unicode Support: Enabled**")

        burn_start = time.time()

        # Simulate progress
        async def simulate_burn_progress():
            start = time.time()
            while True:
                elapsed = time.time() - start
                await burn_progress.update(0, 0)
                await asyncio.sleep(1)
                if burn_task.done():
                    break
            await burn_progress.update(100, 4.0)

        burn_task = asyncio.create_task(burn_subtitles(video_path, sub_path, output_file))
        progress_task = asyncio.create_task(simulate_burn_progress())

        try:
            await burn_task
        except Exception:
            burn_task.cancel()
            raise
        finally:
            progress_task.cancel()

        burn_time = time.time() - burn_start

        if not os.path.exists(output_file):
            raise Exception("Output file not created by ffmpeg")

        output_size = os.path.getsize(output_file)
        burn_speed = (user_data[chat_id]["file_size"] / burn_time) / (1024 * 1024) if burn_time > 0 else 0

        # Upload
        await status_msg.edit_text("🚀 **ULTRA UPLOAD STARTED**")
        upload_progress = UltraProgress(client, chat_id, status_msg.id, os.path.basename(output_file), "UPLOAD")

        upload_start = time.time()
        await client.send_video(
            chat_id,
            output_file,
            caption=(
                f"✅ **ULTRA BURN COMPLETE!**\n\n"
                f"🚀 **Burn Speed:** {burn_speed:.1f} MB/s\n"
                f"⏱️ **Burn Time:** {format_time(burn_time)}\n"
                f"📦 **Output Size:** {human_readable(output_size)}\n"
                f"🌍 **Unicode Support:** Sinhala/Tamil/English ✓\n\n"
                f"🔥 **Subtitles permanently burned!**"
            ),
            progress=upload_progress.update,
            supports_streaming=True
        )
        upload_time = time.time() - upload_start

        total_time = time.time() - user_data[chat_id]["start_time"]
        await status_msg.edit_text(
            f"🎉 **MISSION ACCOMPLISHED!**\n\n"
            f"✅ **Total Time:** {format_time(total_time)}\n"
            f"🌍 **Unicode Support:** Active ✓\n"
            f"🚀 **Ready for next file!**"
        )

        # Cleanup
        await asyncio.sleep(1)
        try:
            await status_msg.delete()
        except Exception:
            pass

        cleanup_files(video_path, sub_path, output_file)
        del user_data[chat_id]

    except Exception as e:
        logger.exception("Ultra burn error")
        error_msg = str(e)
        try:
            await status_msg.edit_text(
                f"❌ **ULTRA BURN FAILED!**\n\n"
                f"`{escape_html(error_msg)}`\n\n"
                f"💡 **Tips for Sinhala/Tamil subtitles:**\n"
                f"• Ensure subtitle file is UTF-8 encoded\n"
                f"• The **FreeSans** font should now be installed correctly.\n"
                f"• Use MP4 files for best compatibility\n"
                f"• Keep files under 1GB\n"
                f"• Use /cancel to restart"
            )
        except Exception:
            pass

        if chat_id in user_data:
            for key in ["video", "subtitle", "output"]:
                file_path = user_data[chat_id].get(key)
                cleanup_files(file_path)
            del user_data[chat_id]
