import asyncio
import time
from pyrogram import Client
from pyrogram.types import Message
from config import ADMIN_IDS, BROADCAST_CHUNK_SIZE
import logging

logger = logging.getLogger(__name__)

async def broadcast_message(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply_text("❌ **Admin only command!**")
        return

    if not message.reply_to_message:
        await message.reply_text("❌ **Please reply to a message to broadcast!**")
        return

    broadcast_msg = message.reply_to_message
    status_msg = await message.reply_text("🔄 **Starting broadcast...**")

    all_chats = []
    async for dialog in client.get_dialogs():
        if dialog.chat.type in ["group", "supergroup", "channel"]:
            all_chats.append(dialog.chat.id)

    total = len(all_chats)
    success = 0
    failed = 0

    await status_msg.edit_text(f"📤 **Broadcasting to {total} chats...**\n✅ Success: 0\n❌ Failed: 0")

    for i in range(0, total, BROADCAST_CHUNK_SIZE):
        chunk = all_chats[i:i + BROADCAST_CHUNK_SIZE]
        
        for chat_id in chunk:
            try:
                await broadcast_msg.copy(chat_id)
                success += 1
            except Exception as e:
                logger.error(f"Failed to send to {chat_id}: {e}")
                failed += 1
            
            await asyncio.sleep(0.1)  # Rate limiting

        if i + BROADCAST_CHUNK_SIZE < total:
            await status_msg.edit_text(
                f"📤 **Broadcasting...**\n"
                f"Progress: {i + len(chunk)}/{total}\n"
                f"✅ Success: {success}\n"
                f"❌ Failed: {failed}"
            )

    await status_msg.edit_text(
        f"✅ **Broadcast Complete!**\n\n"
        f"• Total: {total}\n"
        f"• ✅ Success: {success}\n"
        f"• ❌ Failed: {failed}\n"
        f"• Success Rate: {(success/total)*100:.1f}%"
    )
