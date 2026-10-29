"""
Premium Custom Emoji ID Bot — ULTIMATE COMPLETE EDITION

Features:
- Force-join membership gate
- Custom emoji ID extraction (single/multiple)
- Premium emoji collection (25 IDs, paginated)
- Admin panel: broadcast, run ad, cancel ad, dashboard
- Premium Ad Maker for ALL USERS: normal → premium emoji + aesthetic font
- PREMIUM FORWARD button for everyone + POST TO CHANNEL for admins
- Live dashboard with auto-refresh
- Zero plain emoji — only premium custom emoji markup
- Colorful buttons with premium emoji icons
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import math
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import BaseFilter, Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    ChatMemberAdministrator,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")
CHANNEL_ID: str = os.getenv("CHANNEL_ID", "@whymeyarrr")
CHANNEL_LINK: str = "https://t.me/whymeyarrr"

ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

DB_PATH: str = os.getenv("DB_PATH", "bot.db")
VALIDATE_EMOJI: bool = os.getenv("VALIDATE_EMOJI", "1") == "1"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Set it in .env or Render env.")

# Dashboard URL auto-detection
_ext_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
_ext_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _ext_url.startswith("https://"):
    DASHBOARD_URL = f"{_ext_url}/dashboard"
elif _ext_host:
    DASHBOARD_URL = f"https://{_ext_host}/dashboard"
else:
    DASHBOARD_URL = ""

# ============================================================
# THE 25 SUPPLIED CUSTOM EMOJI IDS
# ============================================================

EMOJI_IDS: list[str] = [
    "5357592447557848986", "5258387666616994756", "5391118489824015979",
    "5334665104677941170", "5289862389552919154", "5397730656400714154",
    "5301275719681190738", "5301096984617166561", "5386521874089914548",
    "5332423642850536254", "5264892613630111886", "5258113901106580375",
    "5258212320282168974", "5258274739041883702", "5258457030338844822",
    "5260373152688540294", "5258420785109830474", "5258178411515382761",
    "5260691173541970181", "6014620343883273557", "6015104451122042405",
    "6104794084205925773", "6104675564583392962", "6107015024679592166",
    "6120548140211770562",
]

EMOJI_FALLBACKS: list[str] = [
    "✨", "💎", "⭐", "🔥", "👑",
    "🆔", "📖", "🛠", "📢", "🎯",
    "💫", "🌟", "❤️", "🧡", "💛",
    "💚", "💙", "💜", "🖤", "🤍",
    "🚀", "🎉", "🏆", "🔔", "📌",
]

# Button icons (reuse from the 25 IDs)
BTN_JOIN       = EMOJI_IDS[0]
BTN_VERIFY     = EMOJI_IDS[1]
BTN_HELP       = EMOJI_IDS[2]
BTN_GET_ID     = EMOJI_IDS[3]
BTN_COLLECTION = EMOJI_IDS[4]
BTN_HOWTO      = EMOJI_IDS[5]
BTN_CHANNEL    = EMOJI_IDS[6]
BTN_HOME       = EMOJI_IDS[7]
BTN_BACK       = EMOJI_IDS[8]
BTN_NEXT       = EMOJI_IDS[9]

PAGE_SIZE: int = 5
TOTAL_PAGES: int = math.ceil(len(EMOJI_IDS) / PAGE_SIZE)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
START_TIME: float = time.time()

VALID_EMOJI_CACHE: dict[str, Optional[bool]] = {}
_membership_cache: dict[int, tuple[float, bool, str]] = {}
MEMBERSHIP_CACHE_TTL: int = 60
_health_runner: Any = None

# Ad campaign config
_active_ad: Optional[asyncio.Task] = None
AD_SEND_COUNT: int = 5
AD_GAP_SECONDS: int = 600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("premium-emoji-bot")

router = Router()

# ============================================================
# AESTHETIC DECORATIONS
# ============================================================

DIV_LIGHT = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
DIV_HEAVY = "━━━━━━━━━━━━━━━━━━━━━━━"


def header(title: str) -> str:
    return f"✦ {DIV_HEAVY} ✦\n     {title}\n✦ {DIV_HEAVY} ✦"


def footer(tagline: str) -> str:
    return f"{DIV_LIGHT}\n{tagline}"


# ============================================================
# CUSTOM EMOJI HELPERS
# ============================================================

def custom_emoji(emoji_id: str, fallback: str = "✨") -> str:
    emoji_id = str(emoji_id).strip()
    fallback = fallback or "✨"
    if not emoji_id.isdigit():
        logger.warning("Invalid emoji ID: %r", emoji_id)
        return html.escape(fallback)
    if VALID_EMOJI_CACHE.get(emoji_id) is False:
        return html.escape(fallback)
    safe_id = html.escape(emoji_id, quote=True)
    safe_fallback = html.escape(fallback)
    return f'<tg-emoji emoji-id="{safe_id}">{safe_fallback}</tg-emoji>'


def e(index: int, fallback: Optional[str] = None) -> str:
    idx = index % len(EMOJI_IDS)
    return custom_emoji(EMOJI_IDS[idx], fallback or EMOJI_FALLBACKS[idx])


CUSTOM_EMOJI_TAG_RE = re.compile(
    r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>", re.IGNORECASE | re.DOTALL
)


def strip_custom_emoji_tags(text: str) -> str:
    return CUSTOM_EMOJI_TAG_RE.sub(r"\1", text)


async def safe_answer(message: Message, text: str, **kwargs: Any) -> Optional[Message]:
    """Send a message with 3-level fallback."""
    try:
        return await message.answer(text, **kwargs)
    except TelegramBadRequest as exc:
        logger.warning("sendMessage failed: %s", exc)
        try:
            return await message.answer(strip_custom_emoji_tags(text), **kwargs)
        except TelegramBadRequest as exc2:
            logger.warning("Fallback markup failed: %s — retrying without markup", exc2)
            kwargs.pop("reply_markup", None)
            try:
                return await message.answer(strip_custom_emoji_tags(text), **kwargs)
            except TelegramAPIError:
                return None
        except TelegramAPIError:
            return None
    except TelegramAPIError:
        logger.exception("sendMessage failed")
        return None


async def safe_edit(callback: CallbackQuery, text: str, **kwargs: Any) -> None:
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(text, **kwargs)
        return
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        logger.warning("edit failed: %s", exc)
        with contextlib.suppress(TelegramAPIError):
            kwargs.pop("reply_markup", None)
            await callback.message.answer(strip_custom_emoji_tags(text), **kwargs)


def mk_button(**kwargs: Any) -> InlineKeyboardButton:
    """Build button with style + premium icon, fallback to plain."""
    try:
        return InlineKeyboardButton(**kwargs)
    except (TypeError, ValueError) as exc:
        logger.warning("Button style/icon unsupported: %s", exc)
        safe = {k: v for k, v in kwargs.items()
                if k not in ("style", "icon_custom_emoji_id")}
        try:
            return InlineKeyboardButton(**safe)
        except Exception:
            minimal = {k: v for k, v in safe.items()
                       if k in ("text", "callback_data", "url")}
            return InlineKeyboardButton(**minimal)


# ============================================================
# PREMIUM AD CONVERTER — normal → premium + aesthetic font
# ============================================================

SMALL_CAPS_MAP = str.maketrans({
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ',
    'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ',
    'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ',
    's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
    'y': 'ʏ', 'z': 'ᴢ',
    'A': 'ᴀ', 'B': 'ʙ', 'C': 'ᴄ', 'D': 'ᴅ', 'E': 'ᴇ', 'F': 'ꜰ',
    'G': 'ɢ', 'H': 'ʜ', 'I': 'ɪ', 'J': 'ᴊ', 'K': 'ᴋ', 'L': 'ʟ',
    'M': 'ᴍ', 'N': 'ɴ', 'O': 'ᴏ', 'P': 'ᴘ', 'Q': 'ǫ', 'R': 'ʀ',
    'S': 'ꜱ', 'T': 'ᴛ', 'U': 'ᴜ', 'V': 'ᴠ', 'W': 'ᴡ', 'X': 'x',
    'Y': 'ʏ', 'Z': 'ᴢ',
})

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "]",
    flags=re.UNICODE,
)


def to_small_caps(text: str) -> str:
    return text.translate(SMALL_CAPS_MAP)


def generate_premium_variant(text: str, style: int) -> str:
    """
    Convert normal emojis in text to premium custom emojis.
    Apply aesthetic font: even styles = small caps, odd styles = bold normal.

    Returns clean HTML (no header/footer wrapper).
    """
    use_small_caps = (style % 2 == 0)

    def transform(s: str) -> str:
        return to_small_caps(s) if use_small_caps else s

    parts: list[str] = []
    last_end = 0

    for match in EMOJI_PATTERN.finditer(text):
        if last_end < match.start():
            chunk = text[last_end:match.start()]
            parts.append(html.escape(transform(chunk)))

        idx = random.randrange(len(EMOJI_IDS))
        parts.append(custom_emoji(EMOJI_IDS[idx], EMOJI_FALLBACKS[idx]))
        last_end = match.end()

    if last_end < len(text):
        parts.append(html.escape(transform(text[last_end:])))

    content = "".join(parts)
    if use_small_caps:
        return content
    return f"<b>{content}</b>"


# ============================================================
# KEYBOARDS
# ============================================================

def force_join_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(mk_button(text="JOIN CHANNEL", url=CHANNEL_LINK,
                     icon_custom_emoji_id=BTN_JOIN, style="success"))
    kb.row(mk_button(text="VERIFY JOIN", callback_data="verify_join",
                     icon_custom_emoji_id=BTN_VERIFY, style="primary"))
    kb.row(mk_button(text="HELP", callback_data="help",
                     icon_custom_emoji_id=BTN_HELP, style="danger"))
    return kb.as_markup()


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(mk_button(text="GET EMOJI ID", callback_data="get_id_help",
                     icon_custom_emoji_id=BTN_GET_ID, style="primary"))
    kb.row(mk_button(text="PREMIUM EMOJI COLLECTION", callback_data="collection:0",
                     icon_custom_emoji_id=BTN_COLLECTION, style="success"))
    kb.row(mk_button(text="MAKE PREMIUM AD", callback_data="make_premium_ad",
                     icon_custom_emoji_id=BTN_CHANNEL, style="success"))
    kb.row(
        mk_button(text="HOW TO USE", callback_data="howto",
                  icon_custom_emoji_id=BTN_HOWTO, style="primary"),
        mk_button(text="HELP", callback_data="help",
                  icon_custom_emoji_id=BTN_HELP, style="danger"),
    )
    kb.row(mk_button(text="CHANNEL", url=CHANNEL_LINK,
                     icon_custom_emoji_id=BTN_CHANNEL, style="success"))
    if is_admin:
        kb.row(mk_button(text="ADMIN PANEL", callback_data="open_admin_panel",
                         icon_custom_emoji_id=BTN_COLLECTION, style="danger"))
    return kb.as_markup()


def collection_keyboard(page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(mk_button(text="BACK", callback_data=f"collection:{page - 1}",
                             icon_custom_emoji_id=BTN_BACK, style="primary"))
    nav.append(mk_button(text="HOME", callback_data="home",
                         icon_custom_emoji_id=BTN_HOME, style="success"))
    if page < TOTAL_PAGES - 1:
        nav.append(mk_button(text="NEXT", callback_data=f"collection:{page + 1}",
                             icon_custom_emoji_id=BTN_NEXT, style="primary"))
    kb.row(*nav)
    return kb.as_markup()


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(mk_button(text="MAKE PREMIUM AD", callback_data="make_premium_ad",
                     icon_custom_emoji_id=BTN_COLLECTION, style="success"))
    kb.row(mk_button(text="BROADCAST TO USERS", callback_data="admin_broadcast",
                     icon_custom_emoji_id=BTN_CHANNEL, style="primary"))
    kb.row(mk_button(text="RUN AD IN CHANNEL", callback_data="admin_ad",
                     icon_custom_emoji_id=BTN_CHANNEL, style="success"))
    kb.row(mk_button(text="CANCEL ACTIVE AD", callback_data="admin_cancel_ad",
                     icon_custom_emoji_id=BTN_HELP, style="danger"))
    if DASHBOARD_URL and DASHBOARD_URL.startswith("https://"):
        kb.row(mk_button(text="OPEN DASHBOARD", url=DASHBOARD_URL,
                         icon_custom_emoji_id=BTN_GET_ID, style="primary"))
    kb.row(mk_button(text="BACK TO MENU", callback_data="home",
                     icon_custom_emoji_id=BTN_HOME, style="success"))
    return kb.as_markup()


def premium_ad_preview_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(mk_button(text="PREMIUM FORWARD", callback_data="premium_forward",
                     icon_custom_emoji_id=BTN_CHANNEL, style="success"))
    if is_admin:
        kb.row(mk_button(text="POST TO CHANNEL", callback_data="premium_post_channel",
                         icon_custom_emoji_id=BTN_COLLECTION, style="primary"))
    kb.row(
        mk_button(text="CHANGE STYLE", callback_data="premium_change",
                  icon_custom_emoji_id=BTN_GET_ID, style="primary"),
        mk_button(text="CANCEL", callback_data="premium_cancel",
                  icon_custom_emoji_id=BTN_HELP, style="danger"),
    )
    return kb.as_markup()


# ============================================================
# TEXT BUILDERS
# ============================================================

def force_join_text() -> str:
    return (
        f"{header('ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ ʙᴏᴛ')}\n\n"
        f"{e(1)} <b>ᴀᴄᴄᴇꜱꜱ ʟᴏᴄᴋᴇᴅ</b>\n\n"
        f"{e(6)} ᴛᴏ ᴜɴʟᴏᴄᴋ ᴛʜɪꜱ ʙᴏᴛ, ᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ.\n\n"
        f"{DIV_LIGHT}\n\n"
        f"▸ {e(11)} ᴛᴀᴘ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ\n"
        f"▸ {e(16)} ᴛᴀᴘ ᴠᴇʀɪꜰʏ ᴊᴏɪɴ\n"
        f"▸ {e(21)} ᴇɴᴊᴏʏ ꜰᴜʟʟ ᴀᴄᴄᴇꜱꜱ\n\n"
        f"{footer('ɪɴꜱᴛᴀɴᴛ · ꜱᴇᴄᴜʀᴇ · ꜰᴀꜱᴛ')}"
    )


def force_join_reminder_text() -> str:
    return (
        f"{header('ᴀᴄᴄᴇꜱꜱ ʟᴏᴄᴋᴇᴅ')}\n\n"
        f"{e(2)} ᴀᴠᴀɪʟᴀʙʟᴇ ᴏɴʟʏ ᴛᴏ ᴄʜᴀɴɴᴇʟ ᴍᴇᴍʙᴇʀꜱ.\n\n"
        f"{e(7)} ᴛᴀᴘ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ → ᴊᴏɪɴ → ᴛᴀᴘ ᴠᴇʀɪꜰʏ"
    )


def main_menu_text(is_admin: bool = False) -> str:
    admin_note = (
        f"\n\n{footer('ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ ᴀᴠᴀɪʟᴀʙʟᴇ ʙᴇʟᴏᴡ')}"
        if is_admin else ""
    )
    return (
        f"{header('ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ ʙᴏᴛ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴀɴʏ ᴛᴇʟᴇɢʀᴀᴍ <b>ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ</b>\n"
        f"   ᴛᴏ ᴅɪꜱᴄᴏᴠᴇʀ ɪᴛꜱ ɪᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(5)} ɪɴꜱᴛᴀɴᴛ ᴀɴᴀʟʏꜱɪꜱ\n"
        f"{e(10)} ꜱᴜᴘᴘᴏʀᴛꜱ ᴍᴜʟᴛɪᴘʟᴇ ᴇᴍᴏᴊɪꜱ\n"
        f"{e(15)} ᴄᴏɴᴠᴇʀᴛ ɴᴏʀᴍᴀʟ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ᴀᴅꜱ"
        f"{admin_note}"
    )


def no_emoji_text() -> str:
    return (
        f"{header('ɴᴏ ᴇᴍᴏᴊɪ ꜰᴏᴜɴᴅ')}\n\n"
        f"{e(3)} ɴᴏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ᴅᴇᴛᴇᴄᴛᴇᴅ\n\n"
        f"{e(9)} ꜱᴇɴᴅ ᴀ ᴍᴇꜱꜱᴀɢᴇ ᴡɪᴛʜ ᴀᴛ ʟᴇᴀꜱᴛ ᴏɴᴇ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ\n\n"
        f"{footer('ᴏɴʟʏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪꜱ ʜᴀᴠᴇ ɪᴅꜱ')}"
    )


def get_id_help_text() -> str:
    return (
        f"{header('ɢᴇᴛ ᴇᴍᴏᴊɪ ɪᴅ')}\n\n"
        f"{e(4)} 3 ꜱᴛᴇᴘꜱ:\n\n"
        f"▸ {e(9)} ᴏᴘᴇɴ ᴀ ᴄʜᴀᴛ ᴡɪᴛʜ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪꜱ\n"
        f"▸ {e(14)} ꜱᴇɴᴅ ᴛʜᴇ ᴇᴍᴏᴊɪ ʜᴇʀᴇ\n"
        f"▸ {e(19)} ʀᴇᴄᴇɪᴠᴇ ɪᴛꜱ ɪᴅ\n\n"
        f"{footer('ᴛᴀᴘ ᴛʜᴇ ɪᴅ ᴛᴏ ᴄᴏᴘʏ')}"
    )


def how_to_text() -> str:
    return (
        f"{header('ʜᴏᴡ ᴛᴏ ᴜꜱᴇ')}\n\n"
        f"{e(7)} <b>1 · ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ</b>\n"
        f"{e(12)} <b>2 · ᴠᴇʀɪꜰʏ</b>\n"
        f"{e(17)} <b>3 · ꜱᴇɴᴅ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ</b>\n"
        f"{e(22)} <b>4 · ᴍᴀᴋᴇ ᴘʀᴇᴍɪᴜᴍ ᴀᴅ</b>\n\n"
        f"{footer('ᴛᴀᴘ ᴍᴀᴋᴇ ᴘʀᴇᴍɪᴜᴍ ᴀᴅ ɪɴ ᴍᴇɴᴜ')}"
    )


def help_text() -> str:
    return (
        f"{header('ʜᴇʟᴘ ᴄᴇɴᴛᴇʀ')}\n\n"
        f"{e(8)} <b>· ɢᴇᴛ ᴇᴍᴏᴊɪ ɪᴅ</b>\n"
        "   ꜱᴇɴᴅ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ\n\n"
        f"{e(13)} <b>· ᴍᴀᴋᴇ ᴘʀᴇᴍɪᴜᴍ ᴀᴅ</b>\n"
        "   ꜱᴇɴᴅ ᴛᴇxᴛ ᴡɪᴛʜ ᴇᴍᴏᴊɪꜱ, ʙᴏᴛ ᴄᴏɴᴠᴇʀᴛꜱ ᴛʜᴇᴍ\n"
        "   ᴛᴏ ᴘʀᴇᴍɪᴜᴍ + ᴀᴇꜱᴛʜᴇᴛɪᴄ ꜰᴏɴᴛ\n\n"
        "<b>· ᴡʜʏ ᴏʀᴅɪɴᴀʀʏ ᴇᴍᴏᴊɪꜱ ꜰᴀɪʟ ɪɴ ɪᴅ ᴍᴏᴅᴇ</b>\n"
        "   ᴏɴʟʏ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪꜱ ʜᴀᴠᴇ ɪᴅꜱ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(18)} <b>ᴀᴅᴍɪɴ ᴄᴏɴᴛᴀᴄᴛꜱ</b>\n"
        f"   @cytunn\n"
        f"   @R0syug\n\n"
        f"{e(23)} <b>ᴄʜᴀɴɴᴇʟ</b>\n"
        f'   <a href="{CHANNEL_LINK}">{CHANNEL_LINK}</a>'
    )


def build_emoji_response(ids: list[str]) -> str:
    if len(ids) == 1:
        eid = ids[0]
        return (
            f"{header('ᴘʀᴇᴍɪᴜᴍ ᴅᴇᴛᴇᴄᴛᴇᴅ')}\n\n"
            f"{custom_emoji(eid, '💎')} <b>ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ɪᴅ</b>\n\n"
            f"<code>{html.escape(eid)}</code>\n\n"
            f"{footer('ᴛᴀᴘ ᴛʜᴇ ɪᴅ ᴛᴏ ᴄᴏᴘʏ')}"
        )
    lines = [header('ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪꜱ ꜰᴏᴜɴᴅ'), "",
             f"{e(0)} <b>ᴅᴇᴛᴇᴄᴛᴇᴅ {len(ids)} ᴇᴍᴏᴊɪꜱ</b>", ""]
    for i, eid in enumerate(ids, start=1):
        lines.append(f"{i:02d} · {custom_emoji(eid, '✨')} <code>{html.escape(eid)}</code>")
    lines.append("")
    lines.append(footer("ᴛᴀᴘ ᴀɴ ɪᴅ ᴛᴏ ᴄᴏᴘʏ"))
    return "\n".join(lines)


def build_collection_page(page: int) -> str:
    page = max(0, min(page, TOTAL_PAGES - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(EMOJI_IDS))
    lines = [header('ᴘʀᴇᴍɪᴜᴍ ᴄᴏʟʟᴇᴄᴛɪᴏɴ'), "",
             f"ᴘᴀɢᴇ <b>{page + 1}</b> / {TOTAL_PAGES}", DIV_LIGHT, ""]
    for number, emoji_id in enumerate(EMOJI_IDS[start:end], start=start + 1):
        fallback = EMOJI_FALLBACKS[(number - 1) % len(EMOJI_FALLBACKS)]
        lines.append(f"{number:02d} · {custom_emoji(emoji_id, fallback)} "
                     f"<code>{html.escape(emoji_id)}</code>")
    lines.append("")
    lines.append(footer("ᴛᴀᴘ ᴀɴ ɪᴅ ᴛᴏ ᴄᴏᴘʏ"))
    return "\n".join(lines)


def premium_ad_intro_text() -> str:
    return (
        f"{header('ᴍᴀᴋᴇ ᴘʀᴇᴍɪᴜᴍ ᴀᴅ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ʏᴏᴜʀ ᴀᴅ ᴛᴇxᴛ\n"
        f"   (ɴᴏʀᴍᴀʟ ᴇᴍᴏᴊɪꜱ ᴀʀᴇ ꜰɪɴᴇ)\n\n"
        f"{DIV_LIGHT}\n\n"
        "<b>ᴇxᴀᴍᴘʟᴇ:</b>\n"
        "<i>Sell you GC here 👽 buy safe 🎀 sell safe 🌷</i>\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(6)} <b>ʙᴏᴛ ᴡɪʟʟ ᴄᴏɴᴠᴇʀᴛ:</b>\n"
        f"▸ ɴᴏʀᴍᴀʟ ᴇᴍᴏᴊɪꜱ → ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪꜱ\n"
        f"▸ ᴛᴇxᴛ → ᴀᴇꜱᴛʜᴇᴛɪᴄ ꜰᴏɴᴛ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}"
    )


def premium_ad_preview_wrap(clean_html: str, style: int) -> str:
    style_name = "ꜱᴍᴀʟʟ ᴄᴀᴘꜱ" if style % 2 == 0 else "ʙᴏʟᴅ"
    return (
        f"{header('ᴘʀᴇᴍɪᴜᴍ ᴀᴅ ᴘʀᴇᴠɪᴇᴡ')}\n\n"
        f"{clean_html}\n\n"
        f"{DIV_LIGHT}\n"
        f"ꜱᴛʏʟᴇ · {style_name}\n\n"
        f"{footer('ꜰᴏʀᴡᴀʀᴅ · ᴄʜᴀɴɢᴇ ꜱᴛʏʟᴇ · ᴘᴏꜱᴛ')}"
    )


# ============================================================
# DATABASE
# ============================================================

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_verified INTEGER NOT NULL DEFAULT 0,
                joined_at TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.commit()


async def upsert_user(user: Any) -> None:
    if user is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, first_name, joined_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_seen=excluded.last_seen
        """, (user.id, user.username, user.first_name, now, now))
        await db.commit()


async def mark_verified(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_verified=1 WHERE user_id=?", (user_id,))
        await db.commit()


async def increment_stat(key: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO stats (key, value) VALUES (?, 1)
            ON CONFLICT(key) DO UPDATE SET value=value+1
        """, (key,))
        await db.commit()


async def get_stats() -> dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        total = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_verified=1")
        verified = (await cur.fetchone())[0]
        cur = await db.execute("SELECT value FROM stats WHERE key='emoji_queries'")
        r = await cur.fetchone()
        queries = r[0] if r else 0
        cur = await db.execute("SELECT value FROM stats WHERE key='visits'")
        r = await cur.fetchone()
        visits = r[0] if r else 0
    return {"total_users": total, "verified_users": verified,
            "emoji_queries": queries, "visits": visits}


async def all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        return [r[0] for r in await cur.fetchall()]


# ============================================================
# MEMBERSHIP CHECK
# ============================================================

async def is_member(bot: Bot, user_id: int, force: bool = False) -> tuple[bool, str]:
    now = time.monotonic()
    if not force:
        cached = _membership_cache.get(user_id)
        if cached and now - cached[0] < MEMBERSHIP_CACHE_TTL:
            return cached[1], cached[2]
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
    except TelegramBadRequest as exc:
        text = str(exc).lower()
        if "user not found" in text or "participant_id_invalid" in text:
            result = (False, "not_member")
        elif "chat not found" in text or "chat_admin_required" in text:
            result = (False, "config_error")
        else:
            result = (False, "api_error")
    except TelegramAPIError:
        result = (False, "api_error")
    else:
        if isinstance(member, (ChatMemberOwner, ChatMemberAdministrator, ChatMemberMember)):
            result = (True, "member")
        elif isinstance(member, ChatMemberRestricted):
            result = (bool(getattr(member, "is_member", False)), "member")
        elif isinstance(member, (ChatMemberLeft, ChatMemberBanned)):
            result = (False, "not_member")
        else:
            result = (False, "not_member")
    _membership_cache[user_id] = (now, result[0], result[1])
    return result


# ============================================================
# FORCE-JOIN MIDDLEWARE
# ============================================================

class ForceJoinMiddleware(BaseMiddleware):
    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        bot: Bot = data["bot"]
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        # Admins bypass force-join
        if user.id in ADMIN_IDS:
            return await handler(event, data)
        # /start always passes
        if isinstance(event, Message) and event.text:
            if event.text.split()[0].lower().startswith("/start"):
                return await handler(event, data)
        # verify_join and help callbacks pass
        if isinstance(event, CallbackQuery) and event.data in ("verify_join", "help"):
            return await handler(event, data)
        ok, _ = await is_member(bot, user.id)
        if ok:
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer("Join the channel first.", show_alert=True)
            return None
        if isinstance(event, Message):
            await safe_answer(event, force_join_reminder_text(),
                              reply_markup=force_join_keyboard(),
                              link_preview_options=NO_PREVIEW)
            return None
        return None


# ============================================================
# STARTUP EMOJI VALIDATION
# ============================================================

async def validate_emoji_ids(bot: Bot) -> None:
    if not VALIDATE_EMOJI or not hasattr(bot, "get_custom_emoji_stickers"):
        return
    working = 0
    for eid in EMOJI_IDS:
        try:
            stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=[eid])
            if stickers:
                VALID_EMOJI_CACHE[eid] = True
                working += 1
            else:
                VALID_EMOJI_CACHE[eid] = False
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)
    logger.info("Emoji validation: %s/%s working", working, len(EMOJI_IDS))


# ============================================================
# STATES
# ============================================================

class BroadcastStates(StatesGroup):
    waiting = State()


class AdStates(StatesGroup):
    waiting = State()


class PremiumAdStates(StatesGroup):
    waiting_text = State()
    previewing = State()


# ============================================================
# USER HANDLERS
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await upsert_user(message.from_user)
    await increment_stat("visits")
    ok, _ = await is_member(bot, message.from_user.id, force=True)
    is_admin = message.from_user.id in ADMIN_IDS
    if ok:
        await mark_verified(message.from_user.id)
        await safe_answer(message, main_menu_text(is_admin),
                          reply_markup=main_menu_keyboard(is_admin),
                          link_preview_options=NO_PREVIEW)
    else:
        await safe_answer(message, force_join_text(),
                          reply_markup=force_join_keyboard(),
                          link_preview_options=NO_PREVIEW)


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    uid = message.from_user.id
    is_admin = uid in ADMIN_IDS
    admins_str = ", ".join(str(x) for x in sorted(ADMIN_IDS)) or "(empty)"
    await message.answer(
        f"<b>Debug Info</b>\n\n"
        f"Your ID · <code>{uid}</code>\n"
        f"Is admin · <code>{'YES' if is_admin else 'NO'}</code>\n"
        f"Configured admins · <code>{admins_str}</code>\n\n"
        f"<i>To be an admin, your numeric ID must be in ADMIN_IDS env var.</i>"
    )


@router.callback_query(F.data == "verify_join")
async def cb_verify_join(callback: CallbackQuery, bot: Bot) -> None:
    ok, reason = await is_member(bot, callback.from_user.id, force=True)
    is_admin = callback.from_user.id in ADMIN_IDS
    if ok:
        await mark_verified(callback.from_user.id)
        await safe_edit(callback, main_menu_text(is_admin),
                        reply_markup=main_menu_keyboard(is_admin),
                        link_preview_options=NO_PREVIEW)
        await callback.answer("Verified.")
        return
    msg = "Not joined yet." if reason == "not_member" else f"Error: {reason}"
    await callback.answer(msg, show_alert=True)


@router.callback_query(F.data == "home")
async def cb_home(callback: CallbackQuery, bot: Bot) -> None:
    ok, _ = await is_member(bot, callback.from_user.id)
    if not ok:
        await callback.answer("Join the channel first.", show_alert=True)
        return
    is_admin = callback.from_user.id in ADMIN_IDS
    await safe_edit(callback, main_menu_text(is_admin),
                    reply_markup=main_menu_keyboard(is_admin),
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.callback_query(F.data == "get_id_help")
async def cb_get_id_help(callback: CallbackQuery) -> None:
    is_admin = callback.from_user.id in ADMIN_IDS
    await safe_edit(callback, get_id_help_text(),
                    reply_markup=main_menu_keyboard(is_admin),
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.callback_query(F.data == "howto")
async def cb_howto(callback: CallbackQuery) -> None:
    is_admin = callback.from_user.id in ADMIN_IDS
    await safe_edit(callback, how_to_text(),
                    reply_markup=main_menu_keyboard(is_admin),
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery, bot: Bot) -> None:
    ok, _ = await is_member(bot, callback.from_user.id)
    is_admin = callback.from_user.id in ADMIN_IDS
    await safe_edit(callback, help_text(),
                    reply_markup=main_menu_keyboard(is_admin) if ok else force_join_keyboard(),
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.callback_query(F.data.startswith("collection:"))
async def cb_collection(callback: CallbackQuery) -> None:
    try:
        page = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        page = 0
    page = max(0, min(page, TOTAL_PAGES - 1))
    await safe_edit(callback, build_collection_page(page),
                    reply_markup=collection_keyboard(page),
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.message(StateFilter(None))
async def handle_any_message(message: Message, bot: Bot) -> None:
    """Extract custom emoji IDs from any message."""
    entities = list(message.entities or []) + list(message.caption_entities or [])
    custom = [en for en in entities if en.type == "custom_emoji"]
    custom.sort(key=lambda en: en.offset)
    ids = [en.custom_emoji_id for en in custom if en.custom_emoji_id]
    is_admin = message.from_user.id in ADMIN_IDS
    if ids:
        await increment_stat("emoji_queries")
        await safe_answer(message, build_emoji_response(ids),
                          link_preview_options=NO_PREVIEW)
    else:
        await safe_answer(message, no_emoji_text(),
                          reply_markup=main_menu_keyboard(is_admin),
                          link_preview_options=NO_PREVIEW)


# ============================================================
# PREMIUM AD MAKER — FOR ALL USERS
# ============================================================

@router.callback_query(F.data == "make_premium_ad")
async def cb_make_premium_ad(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PremiumAdStates.waiting_text)
    await safe_edit(callback, premium_ad_intro_text(),
                    reply_markup=None,
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.message(Command("makead"))
async def cmd_makead(message: Message, state: FSMContext) -> None:
    await state.set_state(PremiumAdStates.waiting_text)
    await safe_answer(message, premium_ad_intro_text(),
                      reply_markup=None,
                      link_preview_options=NO_PREVIEW)


@router.message(StateFilter(PremiumAdStates.waiting_text,
                            PremiumAdStates.previewing))
async def receive_premium_ad_text(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await safe_answer(message, "Send text with some content.")
        return
    original = message.text.strip()
    style = 0
    clean_html = generate_premium_variant(original, style)
    await state.update_data(
        original_text=original,
        clean_html=clean_html,
        style_counter=style,
    )
    await state.set_state(PremiumAdStates.previewing)
    is_admin = message.from_user.id in ADMIN_IDS
    await safe_answer(
        message,
        premium_ad_preview_wrap(clean_html, style),
        reply_markup=premium_ad_preview_keyboard(is_admin),
        link_preview_options=NO_PREVIEW,
    )


@router.callback_query(F.data == "premium_change",
                       StateFilter(PremiumAdStates.previewing))
async def cb_premium_change(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    original = data.get("original_text", "")
    style = int(data.get("style_counter", 0)) + 1
    if not original:
        await callback.answer("No ad text. Start again.", show_alert=True)
        return
    clean_html = generate_premium_variant(original, style)
    await state.update_data(clean_html=clean_html, style_counter=style)
    is_admin = callback.from_user.id in ADMIN_IDS
    await safe_edit(
        callback,
        premium_ad_preview_wrap(clean_html, style),
        reply_markup=premium_ad_preview_keyboard(is_admin),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer("Style changed")


@router.callback_query(F.data == "premium_forward",
                       StateFilter(PremiumAdStates.previewing))
async def cb_premium_forward(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """PREMIUM FORWARD — works for everyone. Sends clean copy to user's chat."""
    data = await state.get_data()
    clean_html = data.get("clean_html", "")
    if not clean_html:
        await callback.answer("Nothing to forward.", show_alert=True)
        return
    try:
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=clean_html,
            parse_mode="HTML",
            link_preview_options=NO_PREVIEW,
        )
    except TelegramAPIError as exc:
        logger.warning("Forward failed: %s", exc)
        await callback.answer(f"Failed: {exc}", show_alert=True)
        return
    await state.clear()
    is_admin = callback.from_user.id in ADMIN_IDS
    await safe_edit(
        callback,
        f"{header('ᴄʟᴇᴀɴ ᴀᴅ ꜱᴇɴᴛ')}\n\n"
        f"{e(19)} ʏᴏᴜʀ ᴄʟᴇᴀɴ ᴘʀᴇᴍɪᴜᴍ ᴀᴅ ɪꜱ ʙᴇʟᴏᴡ\n\n"
        f"ʟᴏɴɢ-ᴘʀᴇꜱꜱ ɪᴛ → ꜰᴏʀᴡᴀʀᴅ → ᴄʜᴏᴏꜱᴇ ᴄʜᴀᴛ\n\n"
        f"{footer('ꜰᴏʀᴡᴀʀᴅ ɪᴛ ᴛᴏ ᴀɴʏ ᴄʜᴀᴛ')}",
        reply_markup=admin_panel_keyboard() if is_admin else main_menu_keyboard(is_admin),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer("Clean copy sent")


@router.callback_query(F.data == "premium_post_channel",
                       StateFilter(PremiumAdStates.previewing))
async def cb_premium_post_channel(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """POST TO CHANNEL — admin only."""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only.", show_alert=True)
        return
    data = await state.get_data()
    clean_html = data.get("clean_html", "")
    if not clean_html:
        await callback.answer("Nothing to post.", show_alert=True)
        return
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=clean_html,
            parse_mode="HTML",
            link_preview_options=NO_PREVIEW,
        )
    except TelegramAPIError as exc:
        logger.warning("Channel post failed: %s", exc)
        await callback.answer(f"Failed: {exc}", show_alert=True)
        return
    await state.clear()
    await safe_edit(
        callback,
        f"{header('ᴀᴅ ꜱᴇɴᴛ')}\n\n"
        f"{e(19)} ᴘʀᴇᴍɪᴜᴍ ᴀᴅ ᴡᴀꜱ ᴘᴏꜱᴛᴇᴅ ᴛᴏ ᴄʜᴀɴɴᴇʟ\n\n"
        f"{footer('ᴛʜᴀɴᴋ ʏᴏᴜ')}",
        reply_markup=admin_panel_keyboard(),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer("Posted to channel")


@router.callback_query(F.data == "premium_cancel",
                       StateFilter(PremiumAdStates.previewing))
async def cb_premium_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    is_admin = callback.from_user.id in ADMIN_IDS
    await safe_edit(callback, main_menu_text(is_admin),
                    reply_markup=main_menu_keyboard(is_admin),
                    link_preview_options=NO_PREVIEW)
    await callback.answer("Cancelled")


@router.message(Command("cancel"),
                StateFilter(PremiumAdStates.waiting_text,
                            PremiumAdStates.previewing))
async def cmd_cancel_premium_ad(message: Message, state: FSMContext) -> None:
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await safe_answer(message, main_menu_text(is_admin),
                      reply_markup=main_menu_keyboard(is_admin),
                      link_preview_options=NO_PREVIEW)


# ============================================================
# ADMIN FILTER & HELPERS
# ============================================================

class IsAdmin(BaseFilter):
    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in ADMIN_IDS


def format_uptime() -> str:
    s = int(time.time() - START_TIME)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}h {m}m {sec}s"


def admin_panel_text(stats: dict[str, int]) -> str:
    ad_status = "ᴀᴄᴛɪᴠᴇ" if (_active_ad and not _active_ad.done()) else "ɪᴅʟᴇ"
    return (
        f"{header('ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ')}\n\n"
        f"{e(19)} <b>ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ</b> · <code>{stats['total_users']}</code>\n"
        f"{e(20)} <b>ᴠᴇʀɪꜰɪᴇᴅ</b> · <code>{stats['verified_users']}</code>\n"
        f"{e(21)} <b>ᴠɪꜱɪᴛꜱ</b> · <code>{stats['visits']}</code>\n"
        f"{e(22)} <b>Qᴜᴇʀɪᴇꜱ</b> · <code>{stats['emoji_queries']}</code>\n"
        f"{e(23)} <b>ᴜᴘᴛɪᴍᴇ</b> · <code>{format_uptime()}</code>\n"
        f"{e(24)} <b>ᴀᴅ ꜱᴛᴀᴛᴜꜱ</b> · <code>{ad_status}</code>\n\n"
        f"{footer('ᴜꜱᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ')}"
    )


async def _show_admin_panel(event: Message | CallbackQuery, bot: Bot) -> None:
    stats = await get_stats()
    text = admin_panel_text(stats)
    kb = admin_panel_keyboard()
    if isinstance(event, Message):
        await safe_answer(event, text, reply_markup=kb, link_preview_options=NO_PREVIEW)
    else:
        await safe_edit(event, text, reply_markup=kb, link_preview_options=NO_PREVIEW)


# ============================================================
# ADMIN HANDLERS
# ============================================================

@router.message(Command("admin", "stats", "panel"), IsAdmin())
async def cmd_admin(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await _show_admin_panel(message, bot)


@router.message(Command("broadcast"), IsAdmin())
async def cmd_broadcast_direct(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting)
    await safe_answer(message,
        f"{header('ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴍᴏᴅᴇ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴛʜᴇ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ\n"
        f"ɪᴛ ᴡɪʟʟ ɢᴏ ᴛᴏ ᴜꜱᴇʀꜱ ᴀɴᴅ ᴄʜᴀɴɴᴇʟ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        link_preview_options=NO_PREVIEW)


@router.message(Command("ad"), IsAdmin())
async def cmd_ad_direct(message: Message, state: FSMContext) -> None:
    if _active_ad and not _active_ad.done():
        await safe_answer(message, "Active ad running. Cancel first.")
        return
    await state.set_state(AdStates.waiting)
    await safe_answer(message,
        f"{header('ʀᴜɴ ᴀᴅ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴛʜᴇ ᴀᴅ ᴍᴇꜱꜱᴀɢᴇ\n"
        f"ᴀᴅ ᴡɪʟʟ ɢᴏ ᴛᴏ ᴄʜᴀɴɴᴇʟ {AD_SEND_COUNT} ᴛɪᴍᴇꜱ · 10 ᴍɪɴ ɢᴀᴘ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        link_preview_options=NO_PREVIEW)


@router.callback_query(F.data == "open_admin_panel", IsAdmin())
async def cb_open_admin_panel(callback: CallbackQuery, bot: Bot) -> None:
    await _show_admin_panel(callback, bot)
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast", IsAdmin())
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting)
    await safe_edit(callback,
        f"{header('ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴍᴏᴅᴇ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴛʜᴇ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ\n\n"
        f"ɪᴛ ᴡɪʟʟ ɢᴏ ᴛᴏ:\n"
        f"▸ ᴀʟʟ ᴜꜱᴇʀꜱ ᴡʜᴏ ꜱᴛᴀʀᴛᴇᴅ ᴛʜᴇ ʙᴏᴛ\n"
        f"▸ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.callback_query(F.data == "admin_ad", IsAdmin())
async def cb_admin_ad(callback: CallbackQuery, state: FSMContext) -> None:
    if _active_ad and not _active_ad.done():
        await callback.answer("Active ad running. Cancel first.", show_alert=True)
        return
    await state.set_state(AdStates.waiting)
    await safe_edit(callback,
        f"{header('ʀᴜɴ ᴀᴅ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴛʜᴇ ᴀᴅ ᴍᴇꜱꜱᴀɢᴇ\n\n"
        f"ᴀᴅ ᴡɪʟʟ ɢᴏ ᴛᴏ ᴄʜᴀɴɴᴇʟ\n"
        f"▸ ᴄᴏᴜɴᴛ · {AD_SEND_COUNT} ᴛɪᴍᴇꜱ\n"
        f"▸ ɢᴀᴘ · 10 ᴍɪɴᴜᴛᴇꜱ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.callback_query(F.data == "admin_cancel_ad", IsAdmin())
async def cb_admin_cancel_ad(callback: CallbackQuery) -> None:
    if _active_ad and not _active_ad.done():
        _active_ad.cancel()
        await callback.answer("Ad cancelled.")
    else:
        await callback.answer("No active ad.", show_alert=True)


@router.message(Command("cancel"),
                StateFilter(BroadcastStates.waiting, AdStates.waiting))
async def cmd_cancel_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(message, "Cancelled.")


# ============================================================
# BROADCAST EXECUTION
# ============================================================

@router.message(StateFilter(BroadcastStates.waiting), IsAdmin())
async def do_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user_ids = await all_user_ids()

    channel_ok = False
    try:
        await bot.copy_message(chat_id=CHANNEL_ID,
                               from_chat_id=message.chat.id,
                               message_id=message.message_id)
        channel_ok = True
    except TelegramAPIError as exc:
        logger.warning("Channel broadcast failed: %s", exc)

    status = await safe_answer(message,
        f"{e(0)} ʙʀᴏᴀᴅᴄᴀꜱᴛɪɴɢ ᴛᴏ {len(user_ids)} ᴜꜱᴇʀꜱ...",
        link_preview_options=NO_PREVIEW)
    sent = failed = 0
    for uid in user_ids:
        try:
            await bot.copy_message(chat_id=uid,
                                   from_chat_id=message.chat.id,
                                   message_id=message.message_id)
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            with contextlib.suppress(TelegramAPIError):
                await bot.copy_message(chat_id=uid,
                                       from_chat_id=message.chat.id,
                                       message_id=message.message_id)
                sent += 1
        except (TelegramForbiddenError, TelegramAPIError):
            failed += 1
        await asyncio.sleep(0.05)

    if status:
        with contextlib.suppress(TelegramAPIError):
            await status.edit_text(
                f"{header('ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴏᴍᴘʟᴇᴛᴇ')}\n\n"
                f"ᴜꜱᴇʀꜱ ꜱᴇɴᴛ · <code>{sent}</code>\n"
                f"ᴜꜱᴇʀꜱ ꜰᴀɪʟᴇᴅ · <code>{failed}</code>\n"
                f"ᴄʜᴀɴɴᴇʟ · <code>{'sent' if channel_ok else 'failed'}</code>",
                reply_markup=admin_panel_keyboard(),
                link_preview_options=NO_PREVIEW)


# ============================================================
# AD CAMPAIGN EXECUTION
# ============================================================

async def run_ad_task(bot: Bot, admin_id: int, chat_id: int, msg_id: int) -> None:
    global _active_ad
    try:
        for i in range(AD_SEND_COUNT):
            try:
                await bot.copy_message(chat_id=CHANNEL_ID,
                                       from_chat_id=chat_id,
                                       message_id=msg_id)
                logger.info("Ad %s/%s sent", i + 1, AD_SEND_COUNT)
                with contextlib.suppress(TelegramAPIError):
                    await bot.send_message(admin_id, f"Ad {i+1}/{AD_SEND_COUNT} sent")
            except TelegramAPIError as exc:
                logger.warning("Ad %s failed: %s", i + 1, exc)
                with contextlib.suppress(TelegramAPIError):
                    await bot.send_message(admin_id, f"Ad {i+1}/{AD_SEND_COUNT} failed")
            if i < AD_SEND_COUNT - 1:
                await asyncio.sleep(AD_GAP_SECONDS)
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(admin_id, f"Ad campaign complete · {AD_SEND_COUNT}/{AD_SEND_COUNT}")
    except asyncio.CancelledError:
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(admin_id, "Ad campaign cancelled.")
        raise
    finally:
        _active_ad = None


@router.message(StateFilter(AdStates.waiting), IsAdmin())
async def do_ad(message: Message, state: FSMContext, bot: Bot) -> None:
    global _active_ad
    await state.clear()
    if _active_ad and not _active_ad.done():
        await safe_answer(message, "Ad already running. Cancel first.",
                          reply_markup=admin_panel_keyboard())
        return
    _active_ad = asyncio.create_task(
        run_ad_task(bot=bot, admin_id=message.chat.id,
                    chat_id=message.chat.id, msg_id=message.message_id)
    )
    await safe_answer(message,
        f"{header('ᴀᴅ ꜱᴛᴀʀᴛᴇᴅ')}\n\n"
        f"{e(0)} ᴀᴅ ᴡɪʟʟ ɢᴏ ᴛᴏ ᴄʜᴀɴɴᴇʟ {AD_SEND_COUNT} ᴛɪᴍᴇꜱ\n"
        f"ɢᴀᴘ · 10 ᴍɪɴᴜᴛᴇꜱ\n"
        f"ᴛᴏᴛᴀʟ ᴛɪᴍᴇ · 40 ᴍɪɴᴜᴛᴇꜱ\n\n"
        f"{footer('ᴄᴀɴᴄᴇʟ ᴀɴʏᴛɪᴍᴇ ᴠɪᴀ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ')}",
        reply_markup=admin_panel_keyboard(),
        link_preview_options=NO_PREVIEW)


# ============================================================
# ERROR HANDLER
# ============================================================

@router.errors()
async def error_handler(event: ErrorEvent) -> bool:
    logger.exception("Error: %s", event.exception)
    return True


# ============================================================
# DASHBOARD HTML
# ============================================================

DASHBOARD_STYLES = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
  min-height: 100vh; color: #fff; padding: 40px 20px;
}
.container { max-width: 1100px; margin: 0 auto; }
header { text-align: center; margin-bottom: 50px; }
h1 {
  font-size: clamp(2rem, 5vw, 3.5rem); font-weight: 800;
  background: linear-gradient(135deg, #667eea, #764ba2, #f093fb);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.tagline { color: rgba(255,255,255,0.55); margin-top: 12px;
  font-size: 0.95rem; letter-spacing: 2px; text-transform: uppercase; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 22px; }
.card { background: rgba(255,255,255,0.05); backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.1); border-radius: 20px;
  padding: 32px; position: relative; overflow: hidden; }
.card::before { content: ''; position: absolute; top: 0; left: 0; right: 0;
  height: 3px; background: linear-gradient(90deg, #667eea, #764ba2, #f093fb); }
.value { font-size: 3rem; font-weight: 800;
  background: linear-gradient(135deg, #a8edea, #fed6e3);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; }
.label { color: rgba(255,255,255,0.65); font-size: 0.8rem;
  text-transform: uppercase; letter-spacing: 1.5px; margin-top: 8px; }
.footer { text-align: center; margin-top: 60px;
  color: rgba(255,255,255,0.4); font-size: 0.85rem; }
.status { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  background: #22c55e; margin-right: 8px; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.7); }
  50% { box-shadow: 0 0 0 10px rgba(34,197,94,0); } }
"""


def render_dashboard(stats: dict[str, int]) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ad_state = "1 running" if (_active_ad and not _active_ad.done()) else "0"
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
<title>Premium Emoji Bot · Dashboard</title>
<style>{DASHBOARD_STYLES}</style></head>
<body><div class="container">
<header><h1>Premium Emoji Bot</h1>
<p class="tagline">Live Dashboard · Auto-refresh 30s</p></header>
<div class="grid">
<div class="card"><div class="value">{stats['total_users']}</div><div class="label">Total Users</div></div>
<div class="card"><div class="value">{stats['verified_users']}</div><div class="label">Verified</div></div>
<div class="card"><div class="value">{stats['visits']}</div><div class="label">Visits</div></div>
<div class="card"><div class="value">{stats['emoji_queries']}</div><div class="label">Emoji Queries</div></div>
<div class="card"><div class="value">{format_uptime()}</div><div class="label">Uptime</div></div>
<div class="card"><div class="value">{ad_state}</div><div class="label">Active Ads</div></div>
</div>
<div class="footer"><span class="status"></span> Updated {now_str}</div>
</div></body></html>"""


# ============================================================
# HTTP SERVER
# ============================================================

async def health_check(request: Any) -> Any:
    from aiohttp import web
    return web.json_response({"status": "ok",
                              "uptime_seconds": int(time.time() - START_TIME)})


async def dashboard_page(request: Any) -> Any:
    from aiohttp import web
    stats = await get_stats()
    return web.Response(text=render_dashboard(stats), content_type="text/html")


async def start_http_server() -> None:
    global _health_runner
    from aiohttp import web
    app = web.Application()
    app.router.add_get("/", dashboard_page)
    app.router.add_get("/dashboard", dashboard_page)
    app.router.add_get("/health", health_check)
    _health_runner = web.AppRunner(app)
    await _health_runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(_health_runner, "0.0.0.0", port).start()
    logger.info("HTTP server on :%s", port)


# ============================================================
# LIFECYCLE
# ============================================================

async def on_startup(bot: Bot) -> None:
    await init_db()
    await validate_emoji_ids(bot)
    asyncio.create_task(start_http_server())
    logger.info("=== BOT STARTED ===")
    logger.info("Admins: %s", sorted(ADMIN_IDS) or "EMPTY (admin features will not work)")
    logger.info("Dashboard: %s", DASHBOARD_URL or "not set (button hidden)")
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS is empty. Set it in Render env vars.")


async def on_shutdown(bot: Bot) -> None:
    if _active_ad and not _active_ad.done():
        _active_ad.cancel()
    if _health_runner is not None:
        with contextlib.suppress(Exception):
            await _health_runner.cleanup()
    await bot.session.close()


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ForceJoinMiddleware())
    dp.callback_query.middleware(ForceJoinMiddleware())
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopped.")
