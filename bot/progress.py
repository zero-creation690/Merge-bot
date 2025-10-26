import time
from utils.helpers import format_time

class UltraProgress:
    def __init__(self, client, chat_id: int, message_id: int, filename: str, action="DOWNLOAD"):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.action = action
        self.start_time = time.time()
        self.last_update = self.start_time
        self.history = []

    async def update(self, current: int, total: int):
        now = time.time()
        if now - self.last_update < 0.5 and current < total:
            return
        elapsed = now - self.start_time
        self.last_update = now
        self.history.append((now, current))
        if len(self.history) > 5:
            self.history.pop(0)

        if len(self.history) >= 2:
            dt = self.history[-1][0] - self.history[0][0]
            db = self.history[-1][1] - self.history[0][1]
            avg_speed = (db / dt) / (1024 * 1024) if dt > 0 else 0
        else:
            avg_speed = (current / elapsed) / (1024 * 1024) if elapsed > 0 else 0

        percent = (current * 100 / total) if total > 0 else 0
        eta = (total - current) / (avg_speed * 1024 * 1024) if avg_speed > 0 else 0

        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        bar = "█" * filled_len + "░" * (bar_len - filled_len)

        if avg_speed > 20:
            emoji = "🚀"
        elif avg_speed > 10:
            emoji = "⚡"
        elif avg_speed > 5:
            emoji = "🔥"
        else:
            emoji = "📶"

        text = (
            f"{emoji} **{self.action}** • **{avg_speed:.1f} MB/s**\n"
            f"`{bar}` **{percent:.1f}%** • ETA: `{format_time(eta)}`\n"
            f"`{self.filename[:40]}`"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception:
            pass

class BurningProgress:
    def __init__(self, client, chat_id: int, message_id: int, filename: str, total_duration: float):
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.filename = filename
        self.total_duration = total_duration
        self.start_time = time.time()
        self.last_update = 0

    async def update(self, percent: float, speed_x: float):
        now = time.time()
        if now - self.last_update < 1 and percent < 100:
            return
        self.last_update = now
        elapsed = now - self.start_time

        estimated_total_time = max(300, self.total_duration / 2.5) if self.total_duration > 0 else 300
        percent_based_on_time = min((elapsed / estimated_total_time) * 100, 99.9)
        speed_x = 2.5 + (percent_based_on_time / 100) * 1.5
        percent = percent_based_on_time

        if percent > 0:
            total_est = elapsed * 100.0 / percent
            eta = max(int(total_est - elapsed), 0)
        else:
            eta = estimated_total_time

        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        bar = "🔥" * filled_len + "░" * (bar_len - filled_len)

        if speed_x > 3.0:
            status = "ULTRA BURN"
        elif speed_x > 2.0:
            status = "TURBO BURN"
        elif speed_x > 1.0:
            status = "FAST BURN"
        else:
            status = "BURNING"

        text = (
            f"⚙️ **{status}** • **{speed_x:.1f}x**\n"
            f"`{bar}` **{percent:.1f}%** • ETA: `{format_time(eta)}`\n"
            f"**Burning subtitles into video...**"
        )

        try:
            await self.client.edit_message_text(self.chat_id, self.message_id, text)
        except Exception:
            pass
