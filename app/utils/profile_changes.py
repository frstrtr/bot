from datetime import datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import html
 # NOTE: safe_send_message not needed here; keep helpers pure

async def build_elapsed(joined_at_raw: str | None) -> str:
    if not joined_at_raw:
        return ""
    try:
        joined_dt = datetime.strptime(joined_at_raw, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - joined_dt
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes and not days:
            parts.append(f"{minutes}m")
        if seconds and not days and not hours:
            parts.append(f"{seconds}s")
        return f"Joined at: {joined_at_raw} (elapsed: {' '.join(parts) or f'{seconds}s'})"
    except ValueError:  # narrow expected parsing errors
        return f"Joined at: {joined_at_raw}"


def diff_block(old_first, old_last, old_usern, old_pcnt, new_first, new_last, new_usern, new_pcnt, user_id):
    def _fmt(old, new, label, username=False):
        if username:
            old_disp = ("@" + old) if old else "@!UNDEFINED!"
            new_disp = ("@" + new) if new else "@!UNDEFINED!"
        else:
            old_disp = html.escape(old) if old else ""
            new_disp = html.escape(new) if new else ""
        if old != new:
            return f"{label}: {old_disp or '∅'} ➜ <b>{new_disp or '∅'}</b>"
        return f"{label}: {new_disp or '∅'}"

    lines = [
        _fmt(old_first, new_first, "First name"),
        _fmt(old_last, new_last, "Last name"),
        _fmt(old_usern, new_usern, "Username", username=True),
        f"User ID: <code>{user_id}</code>",
    ]
    if old_pcnt == 0 and new_pcnt > 0:
        lines.append("Profile photo: none ➜ <b>set</b>")
    return lines


def profile_links(user_id: int) -> str:
    return (
        "🔗 <b>Profile links:</b>\n"
        f"   ├ <a href='tg://user?id={user_id}'>id based profile link</a>\n"
        f"   └ <a href='tg://openmessage?user_id={user_id}'>Android</a>, <a href='https://t.me/@id{user_id}'>IOS (Apple)</a>"
    )


def add_action_buttons(kb: InlineKeyboardMarkup, chat_id: int, report_id: int, user_id: int):
    kb.add(InlineKeyboardButton("🚫 Ban User", callback_data=f"suspiciousban_{chat_id}_{report_id}_{user_id}"))
    kb.add(InlineKeyboardButton("🌐 Global Ban", callback_data=f"suspiciousglobalban_{chat_id}_{report_id}_{user_id}"))
    return kb
