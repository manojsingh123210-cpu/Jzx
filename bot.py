"""
Premium Custom Emoji ID Bot — Ultimate Edition
Broadcast + Run Ad + Live Dashboard + Premium Emoji Only
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import math
import os
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
# CONFIG
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
    raise RuntimeError("BOT_TOKEN is not set.")

# Dashboard URL detection for Render
_ext_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
_ext_url = os.getenv("RENDER_EXTERNAL_URL", "")
if _ext_url:
    DASHBOARD_URL = _ext_url.rstrip("/")
elif _ext_host:
    DASHBOARD_URL = f"https://{_ext_host}"
else:
    DASHBOARD_URL = f"http://localhost:{os.getenv('PORT', '10000')}"

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

# Button icon IDs
BTN_JOIN       = "5357592447557848986"
BTN_VERIFY     = "5258387666616994756"
BTN_HELP       = "5391118489824015979"
BTN_GET_ID     = "5334665104677941170"
BTN_COLLECTION = "5289862389552919154"
BTN_HOWTO      = "5397730656400714154"
BTN_CHANNEL    = "5301275719681190738"
BTN_HOME       = "5301096984617166561"
BTN_BACK       = "5386521874089914548"
BTN_NEXT       = "5332423642850536254"

PAGE_SIZE: int = 5
TOTAL_PAGES: int = math.ceil(len(EMOJI_IDS) / PAGE_SIZE)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
START_TIME: float = time.time()

VALID_EMOJI_CACHE: dict[str, Optional[bool]] = {}
_membership_cache: dict[int, tuple[float, bool, str]] = {}
MEMBERSHIP_CACHE_TTL: int = 60
_health_runner: Any = None

# Active ad task (single at a time)
_active_ad: Optional[asyncio.Task] = None
AD_SEND_COUNT: int = 5
AD_GAP_SECONDS: int = 600  # 10 min

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
    try:
        return await message.answer(text, **kwargs)
    except TelegramBadRequest as exc:
        logger.warning("sendMessage failed, fallback: %s", exc)
        fallback = strip_custom_emoji_tags(text)
        try:
            return await message.answer(fallback, **kwargs)
        except TelegramAPIError:
            logger.exception("Fallback failed")
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
        logger.warning("edit failed, retry: %s", exc)
    except TelegramAPIError:
        logger.exception("edit failed")
    fallback = strip_custom_emoji_tags(text)
    with contextlib.suppress(TelegramAPIError):
        await callback.message.edit_text(fallback, **kwargs)


def mk_button(**kwargs: Any) -> InlineKeyboardButton:
    try:
        return InlineKeyboardButton(**kwargs)
    except (TypeError, ValueError) as exc:
        logger.warning("Button style unsupported: %s", exc)
        safe = {k: v for k, v in kwargs.items()
                if k not in ("style", "icon_custom_emoji_id")}
        return InlineKeyboardButton(**safe)


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


def main_menu_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(mk_button(text="GET EMOJI ID", callback_data="get_id_help",
                     icon_custom_emoji_id=BTN_GET_ID, style="primary"))
    kb.row(mk_button(text="PREMIUM EMOJI COLLECTION", callback_data="collection:0",
                     icon_custom_emoji_id=BTN_COLLECTION, style="success"))
    kb.row(
        mk_button(text="HOW TO USE", callback_data="howto",
                  icon_custom_emoji_id=BTN_HOWTO, style="primary"),
        mk_button(text="HELP", callback_data="help",
                  icon_custom_emoji_id=BTN_HELP, style="danger"),
    )
    kb.row(mk_button(text="CHANNEL", url=CHANNEL_LINK,
                     icon_custom_emoji_id=BTN_CHANNEL, style="success"))
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
    kb.row(mk_button(text="BROADCAST TO USERS", callback_data="admin_broadcast",
                     icon_custom_emoji_id=BTN_CHANNEL, style="primary"))
    kb.row(mk_button(text="RUN AD IN CHANNEL", callback_data="admin_ad",
                     icon_custom_emoji_id=BTN_COLLECTION, style="success"))
    kb.row(mk_button(text="CANCEL ACTIVE AD", callback_data="admin_cancel_ad",
                     icon_custom_emoji_id=BTN_HELP, style="danger"))
    kb.row(mk_button(text="OPEN DASHBOARD", url=f"{DASHBOARD_URL}/dashboard",
                     icon_custom_emoji_id=BTN_GET_ID, style="primary"))
    return kb.as_markup()


# ============================================================
# TEXT BUILDERS
# ============================================================

def force_join_text() -> str:
    return (
        f"{header('ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ ʙᴏᴛ')}\n\n"
        f"{e(1)} <b>ᴀᴄᴄᴇꜱꜱ ʟᴏᴄᴋᴇᴅ</b>\n\n"
        f"{e(6)} ᴛᴏ ᴜɴʟᴏᴄᴋ ᴛʜɪꜱ ʙᴏᴛ, ʏᴏᴜ ᴍᴜꜱᴛ ᴊᴏɪɴ ᴏᴜʀ ᴏꜰꜰɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ.\n\n"
        f"{DIV_LIGHT}\n\n"
        f"▸ {e(11)} ᴛᴀᴘ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ\n"
        f"▸ {e(16)} ʀᴇᴛᴜʀɴ ᴀɴᴅ ᴛᴀᴘ ᴠᴇʀɪꜰʏ ᴊᴏɪɴ\n"
        f"▸ {e(21)} ᴇɴᴊᴏʏ ꜰᴜʟʟ ᴀᴄᴄᴇꜱꜱ\n\n"
        f"{footer('ɪɴꜱᴛᴀɴᴛ · ꜱᴇᴄᴜʀᴇ · ꜰᴀꜱᴛ')}"
    )


def force_join_reminder_text() -> str:
    return (
        f"{header('ᴀᴄᴄᴇꜱꜱ ʟᴏᴄᴋᴇᴅ')}\n\n"
        f"{e(2)} ᴀᴠᴀɪʟᴀʙʟᴇ ᴏɴʟʏ ᴛᴏ ᴄʜᴀɴɴᴇʟ ᴍᴇᴍʙᴇʀꜱ.\n\n"
        f"{e(7)} ᴛᴀᴘ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ → ᴊᴏɪɴ → ᴛᴀᴘ ᴠᴇʀɪꜰʏ ᴊᴏɪɴ"
    )


def main_menu_text() -> str:
    return (
        f"{header('ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ ʙᴏᴛ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴀɴʏ ᴛᴇʟᴇɢʀᴀᴍ <b>ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ</b>\n"
        f"   ᴛᴏ ᴅɪꜱᴄᴏᴠᴇʀ ɪᴛꜱ ɪᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(5)} ɪɴꜱᴛᴀɴᴛ ᴀɴᴀʟʏꜱɪꜱ\n"
        f"{e(10)} ꜱᴜᴘᴘᴏʀᴛꜱ ᴍᴜʟᴛɪᴘʟᴇ ᴇᴍᴏᴊɪꜱ\n"
        f"{e(15)} ᴀᴄᴄᴜʀᴀᴛᴇ ɪᴅ ᴇxᴛʀᴀᴄᴛɪᴏɴ\n\n"
        f"{footer('ꜰᴀꜱᴛ · ꜱɪᴍᴘʟᴇ · ᴀᴄᴄᴜʀᴀᴛᴇ')}"
    )


def no_emoji_text() -> str:
    return (
        f"{header('ɴᴏ ᴇᴍᴏᴊɪ ꜰᴏᴜɴᴅ')}\n\n"
        f"{e(3)} ɴᴏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ᴅᴇᴛᴇᴄᴛᴇᴅ\n\n"
        f"{e(9)} ꜱᴇɴᴅ ᴀ ᴍᴇꜱꜱᴀɢᴇ ᴛʜᴀᴛ ᴄᴏɴᴛᴀɪɴꜱ ᴀᴛ ʟᴇᴀꜱᴛ ᴏɴᴇ\n"
        f"   ᴛᴇʟᴇɢʀᴀᴍ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(14)} ᴏɴʟʏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪꜱ ʜᴀᴠᴇ ɪᴅꜱ\n"
        f"   ᴏʀᴅɪɴᴀʀʏ ᴜɴɪᴄᴏᴅᴇ ᴇᴍᴏᴊɪꜱ ᴅᴏ ɴᴏᴛ"
    )


def get_id_help_text() -> str:
    return (
        f"{header('ɢᴇᴛ ᴇᴍᴏᴊɪ ɪᴅ')}\n\n"
        f"{e(4)} 3 ꜱᴛᴇᴘꜱ:\n\n"
        f"▸ {e(9)} ᴏᴘᴇɴ ᴀ ᴄʜᴀᴛ ᴡɪᴛʜ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪꜱ\n"
        f"▸ {e(14)} ꜱᴇɴᴅ ᴛʜᴇ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ʜᴇʀᴇ\n"
        f"▸ {e(19)} ʀᴇᴄᴇɪᴠᴇ ɪᴛꜱ ᴄᴜꜱᴛᴏᴍ ɪᴅ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(24)} ꜱᴜᴘᴘᴏʀᴛꜱ ᴍᴜʟᴛɪᴘʟᴇ ᴇᴍᴏᴊɪꜱ ᴀɴᴅ ᴍɪxᴇᴅ ᴛᴇxᴛ\n\n"
        f"{footer('ᴛᴀᴘ ᴛʜᴇ ɪᴅ ᴛᴏ ᴄᴏᴘʏ')}"
    )


def how_to_text() -> str:
    return (
        f"{header('ʜᴏᴡ ᴛᴏ ᴜꜱᴇ')}\n\n"
        f"{e(7)} <b>1 · ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ</b>\n"
        f"   ᴛᴀᴘ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ ᴀɴᴅ ꜰᴏʟʟᴏᴡ ʟɪɴᴋ\n\n"
        f"{e(12)} <b>2 · ᴠᴇʀɪꜰʏ</b>\n"
        f"   ʀᴇᴛᴜʀɴ ᴀɴᴅ ᴛᴀᴘ ᴠᴇʀɪꜰʏ ᴊᴏɪɴ\n\n"
        f"{e(17)} <b>3 · ꜱᴇɴᴅ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ</b>\n"
        f"   ʙᴏᴛ ʀᴇᴘʟɪᴇꜱ ᴡɪᴛʜ ɪᴅ\n\n"
        f"{e(22)} <b>4 · ʙʀᴏᴡꜱᴇ ᴄᴏʟʟᴇᴄᴛɪᴏɴ</b>\n"
        f"   ᴏᴘᴇɴ ᴄᴏʟʟᴇᴄᴛɪᴏɴ ꜰᴏʀ ᴀʟʟ ɪᴅꜱ\n\n"
        f"{footer('ʀᴇɴᴅᴇʀɪɴɢ ᴅᴇᴘᴇɴᴅꜱ ᴏɴ ᴛᴇʟᴇɢʀᴀᴍ ᴄʟɪᴇɴᴛ')}"
    )


def help_text() -> str:
    return (
        f"{header('ʜᴇʟᴘ ᴄᴇɴᴛᴇʀ')}\n\n"
        f"{e(8)} <b>· ʜᴏᴡ ᴛᴏ ɢᴇᴛ ᴇᴍᴏᴊɪ ɪᴅ</b>\n"
        "   ꜱᴇɴᴅ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ᴛᴏ ʙᴏᴛ\n\n"
        "<b>· ᴡʜʏ ᴏʀᴅɪɴᴀʀʏ ᴇᴍᴏᴊɪꜱ ꜰᴀɪʟ</b>\n"
        "   ᴏɴʟʏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪꜱ ʜᴀᴠᴇ ɪᴅꜱ\n\n"
        "<b>· ɴᴏʀᴍᴀʟ ᴇᴍᴏᴊɪ ɪɴꜱᴛᴇᴀᴅ</b>\n"
        "   ᴛᴇʟᴇɢʀᴀᴍ ᴍᴀʏ ʀᴇᴊᴇᴄᴛ · ʙᴏᴛ ꜰᴀʟʟꜱ ʙᴀᴄᴋ ᴠᴇʀɪꜰɪᴀʙʟʏ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(13)} <b>ᴀᴅᴍɪɴ ᴄᴏɴᴛᴀᴄᴛꜱ</b>\n"
        f"   @cytunn\n"
        f"   @R0syug\n\n"
        f"{e(18)} <b>ᴄʜᴀɴɴᴇʟ</b>\n"
        f'   <a href="{CHANNEL_LINK}">{CHANNEL_LINK}</a>\n\n'
        f"{footer('ɴᴇᴇᴅ ʜᴇʟᴘ · ᴛᴀᴘ ᴀɴ ᴀᴅᴍɪɴ')}"
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
    lines = [
        header('ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪꜱ ꜰᴏᴜɴᴅ'),
        "",
        f"{e(0)} <b>ᴅᴇᴛᴇᴄᴛᴇᴅ {len(ids)} ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪꜱ</b>",
        "",
    ]
    for i, eid in enumerate(ids, start=1):
        lines.append(
            f"{i:02d} · {custom_emoji(eid, '✨')} <code>{html.escape(eid)}</code>"
        )
    lines.append("")
    lines.append(footer("ᴛᴀᴘ ᴀɴ ɪᴅ ᴛᴏ ᴄᴏᴘʏ"))
    return "\n".join(lines)


def build_collection_page(page: int) -> str:
    page = max(0, min(page, TOTAL_PAGES - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(EMOJI_IDS))
    lines = [
        header('ᴘʀᴇᴍɪᴜᴍ ᴄᴏʟʟᴇᴄᴛɪᴏɴ'),
        "",
        f"ᴘᴀɢᴇ <b>{page + 1}</b> / {TOTAL_PAGES}",
        DIV_LIGHT,
        "",
    ]
    for number, emoji_id in enumerate(EMOJI_IDS[start:end], start=start + 1):
        fallback = EMOJI_FALLBACKS[(number - 1) % len(EMOJI_FALLBACKS)]
        lines.append(
            f"{number:02d} · {custom_emoji(emoji_id, fallback)} "
            f"<code>{html.escape(emoji_id)}</code>"
        )
    lines.append("")
    lines.append(footer("ᴛᴀᴘ ᴀɴ ɪᴅ ᴛᴏ ᴄᴏᴘʏ"))
    return "\n".join(lines)


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
    logger.info("SQLite ready: %s", DB_PATH)


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
        r1 = await cur.fetchone()
        queries = r1[0] if r1 else 0
        cur = await db.execute("SELECT value FROM stats WHERE key='visits'")
        r2 = await cur.fetchone()
        visits = r2[0] if r2 else 0
    return {
        "total_users": total,
        "verified_users": verified,
        "emoji_queries": queries,
        "visits": visits,
    }


async def all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        return [r[0] for r in await cur.fetchall()]


# ============================================================
# MEMBERSHIP
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
        if user.id in ADMIN_IDS:
            return await handler(event, data)
        if isinstance(event, Message) and event.text:
            if event.text.split()[0].lower().startswith("/start"):
                return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "verify_join":
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "help":
            ok_help, _ = await is_member(bot, user.id)
            if not ok_help:
                return await handler(event, data)
        ok, _ = await is_member(bot, user.id)
        if ok:
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer("Join the channel first, then tap Verify Join.", show_alert=True)
            return None
        if isinstance(event, Message):
            await safe_answer(
                event, force_join_reminder_text(),
                reply_markup=force_join_keyboard(),
                link_preview_options=NO_PREVIEW,
            )
            return None
        return None


# ============================================================
# STARTUP VALIDATION
# ============================================================

async def validate_emoji_ids(bot: Bot) -> None:
    if not VALIDATE_EMOJI:
        return
    if not hasattr(bot, "get_custom_emoji_stickers"):
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
# HANDLERS: START / VERIFY
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    await upsert_user(message.from_user)
    await increment_stat("visits")
    ok, _ = await is_member(bot, message.from_user.id, force=True)
    if ok:
        await mark_verified(message.from_user.id)
        await safe_answer(
            message, main_menu_text(),
            reply_markup=main_menu_keyboard(),
            link_preview_options=NO_PREVIEW,
        )
    else:
        await safe_answer(
            message, force_join_text(),
            reply_markup=force_join_keyboard(),
            link_preview_options=NO_PREVIEW,
        )


@router.callback_query(F.data == "verify_join")
async def cb_verify_join(callback: CallbackQuery, bot: Bot) -> None:
    ok, reason = await is_member(bot, callback.from_user.id, force=True)
    if ok:
        await mark_verified(callback.from_user.id)
        await safe_edit(
            callback, main_menu_text(),
            reply_markup=main_menu_keyboard(),
            link_preview_options=NO_PREVIEW,
        )
        await callback.answer("Verified. Welcome.")
        return
    if reason == "config_error":
        await callback.answer("Channel config error. Contact admin.", show_alert=True)
    elif reason == "api_error":
        await callback.answer("Cannot check membership now. Try again.", show_alert=True)
    else:
        await callback.answer("You have not joined yet. Join then tap verify.", show_alert=True)


@router.callback_query(F.data == "home")
async def cb_home(callback: CallbackQuery, bot: Bot) -> None:
    ok, _ = await is_member(bot, callback.from_user.id)
    if not ok:
        await callback.answer("Join the channel first.", show_alert=True)
        return
    await safe_edit(
        callback, main_menu_text(),
        reply_markup=main_menu_keyboard(),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.callback_query(F.data == "get_id_help")
async def cb_get_id_help(callback: CallbackQuery) -> None:
    await safe_edit(
        callback, get_id_help_text(),
        reply_markup=main_menu_keyboard(),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.callback_query(F.data == "howto")
async def cb_howto(callback: CallbackQuery) -> None:
    await safe_edit(
        callback, how_to_text(),
        reply_markup=main_menu_keyboard(),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery, bot: Bot) -> None:
    ok, _ = await is_member(bot, callback.from_user.id)
    await safe_edit(
        callback, help_text(),
        reply_markup=main_menu_keyboard() if ok else force_join_keyboard(),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("collection:"))
async def cb_collection(callback: CallbackQuery) -> None:
    try:
        page = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        page = 0
    page = max(0, min(page, TOTAL_PAGES - 1))
    await safe_edit(
        callback, build_collection_page(page),
        reply_markup=collection_keyboard(page),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.message(StateFilter(None))
async def handle_any_message(message: Message, bot: Bot) -> None:
    entities = list(message.entities or []) + list(message.caption_entities or [])
    custom = [en for en in entities if en.type == "custom_emoji"]
    custom.sort(key=lambda en: en.offset)
    ids = [en.custom_emoji_id for en in custom if en.custom_emoji_id]
    if ids:
        await increment_stat("emoji_queries")
        await safe_answer(
            message, build_emoji_response(ids),
            link_preview_options=NO_PREVIEW,
        )
    else:
        await safe_answer(
            message, no_emoji_text(),
            reply_markup=main_menu_keyboard(),
            link_preview_options=NO_PREVIEW,
        )


# ============================================================
# ADMIN
# ============================================================

class IsAdmin(BaseFilter):
    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in ADMIN_IDS


class BroadcastStates(StatesGroup):
    waiting = State()


class AdStates(StatesGroup):
    waiting = State()


def format_uptime() -> str:
    seconds = int(time.time() - START_TIME)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


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


@router.message(Command("admin", "stats"), IsAdmin())
async def cmd_admin_stats(message: Message) -> None:
    stats = await get_stats()
    await safe_answer(
        message, admin_panel_text(stats),
        reply_markup=admin_panel_keyboard(),
        link_preview_options=NO_PREVIEW,
    )


@router.callback_query(F.data == "admin_broadcast", IsAdmin())
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting)
    await safe_edit(
        callback,
        f"{header('ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴍᴏᴅᴇ')}\n\n"
        "ꜱᴇɴᴅ ᴛʜᴇ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ ɴᴏᴡ\n\n"
        "ɪᴛ ᴡɪʟʟ ɢᴏ ᴛᴏ:\n"
        f"▸ ᴀʟʟ ᴜꜱᴇʀꜱ ᴡʜᴏ ꜱᴛᴀʀᴛᴇᴅ ᴛʜᴇ ʙᴏᴛ\n"
        f"▸ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        reply_markup=None,
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_ad", IsAdmin())
async def cb_admin_ad(callback: CallbackQuery, state: FSMContext) -> None:
    if _active_ad and not _active_ad.done():
        await callback.answer("Active ad running. Cancel it first.", show_alert=True)
        return
    await state.set_state(AdStates.waiting)
    await safe_edit(
        callback,
        f"{header('ʀᴜɴ ᴀᴅ')}\n\n"
        "ꜱᴇɴᴅ ᴛʜᴇ ᴀᴅ ᴍᴇꜱꜱᴀɢᴇ ɴᴏᴡ\n\n"
        f"ᴀᴅ ᴡɪʟʟ ʙᴇ ꜱᴇɴᴛ ᴛᴏ ᴄʜᴀɴɴᴇʟ\n"
        f"▸ ᴄᴏᴜɴᴛ · {AD_SEND_COUNT} ᴛɪᴍᴇꜱ\n"
        f"▸ ɢᴀᴘ · 10 ᴍɪɴᴜᴛᴇꜱ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        reply_markup=None,
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cancel_ad", IsAdmin())
async def cb_admin_cancel_ad(callback: CallbackQuery) -> None:
    if _active_ad and not _active_ad.done():
        _active_ad.cancel()
        await callback.answer("Ad cancelled.")
    else:
        await callback.answer("No active ad running.", show_alert=True)


@router.message(Command("cancel"),
                StateFilter(BroadcastStates.waiting, AdStates.waiting))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(message, "Cancelled.")


# ============================================================
# BROADCAST HANDLER (users + channel)
# ============================================================

@router.message(StateFilter(BroadcastStates.waiting), IsAdmin())
async def do_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user_ids = await all_user_ids()

    # 1) Send to channel
    channel_ok = False
    try:
        await bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        channel_ok = True
    except TelegramAPIError as exc:
        logger.warning("Channel broadcast failed: %s", exc)

    # 2) Send to all users
    status = await safe_answer(
        message,
        f"Broadcasting to {len(user_ids)} users...",
        link_preview_options=NO_PREVIEW,
    )
    sent = failed = 0
    for user_id in user_ids:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            with contextlib.suppress(TelegramAPIError):
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
                sent += 1
        except (TelegramForbiddenError, TelegramAPIError):
            failed += 1
        await asyncio.sleep(0.05)

    if status:
        ch = "sent" if channel_ok else "failed"
        with contextlib.suppress(TelegramAPIError):
            await status.edit_text(
                f"{header('ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴏᴍᴘʟᴇᴛᴇ')}\n\n"
                f"ᴜꜱᴇʀꜱ ꜱᴇɴᴛ · <code>{sent}</code>\n"
                f"ᴜꜱᴇʀꜱ ꜰᴀɪʟᴇᴅ · <code>{failed}</code>\n"
                f"ᴄʜᴀɴɴᴇʟ · <code>{ch}</code>",
                reply_markup=admin_panel_keyboard(),
                link_preview_options=NO_PREVIEW,
            )


# ============================================================
# RUN AD — 5 sends, 10 min gap
# ============================================================

async def run_ad_task(
    bot: Bot, admin_chat_id: int, from_chat_id: int, message_id: int
) -> None:
    global _active_ad
    try:
        for i in range(AD_SEND_COUNT):
            try:
                await bot.copy_message(
                    chat_id=CHANNEL_ID,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )
                logger.info("Ad copy %s/%s sent", i + 1, AD_SEND_COUNT)
                with contextlib.suppress(TelegramAPIError):
                    await bot.send_message(
                        admin_chat_id,
                        f"Ad sent {i + 1}/{AD_SEND_COUNT} to channel",
                    )
            except TelegramAPIError as exc:
                logger.warning("Ad copy %s failed: %s", i + 1, exc)
                with contextlib.suppress(TelegramAPIError):
                    await bot.send_message(
                        admin_chat_id,
                        f"Ad {i + 1}/{AD_SEND_COUNT} failed",
                    )
            if i < AD_SEND_COUNT - 1:
                await asyncio.sleep(AD_GAP_SECONDS)
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(
                admin_chat_id,
                f"Ad campaign complete · {AD_SEND_COUNT}/{AD_SEND_COUNT}",
            )
    except asyncio.CancelledError:
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(admin_chat_id, "Ad campaign cancelled.")
        raise
    finally:
        _active_ad = None


@router.message(StateFilter(AdStates.waiting), IsAdmin())
async def do_ad(message: Message, state: FSMContext, bot: Bot) -> None:
    global _active_ad
    await state.clear()

    if _active_ad and not _active_ad.done():
        await safe_answer(
            message,
            "An ad is already running. Cancel it first.",
            reply_markup=admin_panel_keyboard(),
        )
        return

    _active_ad = asyncio.create_task(
        run_ad_task(
            bot=bot,
            admin_chat_id=message.chat.id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    )

    await safe_answer(
        message,
        f"{header('ᴀᴅ ꜱᴛᴀʀᴛᴇᴅ')}\n\n"
        f"ᴀᴅ ᴡɪʟʟ ʙᴇ ꜱᴇɴᴛ ᴛᴏ ᴄʜᴀɴɴᴇʟ {AD_SEND_COUNT} ᴛɪᴍᴇꜱ\n"
        f"ɢᴀᴘ · 10 ᴍɪɴᴜᴛᴇꜱ\n\n"
        f"{footer('ᴛᴏᴛᴀʟ ᴛɪᴍᴇ · 40 ᴍɪɴᴜᴛᴇꜱ')}",
        reply_markup=admin_panel_keyboard(),
        link_preview_options=NO_PREVIEW,
    )


# ============================================================
# ERROR HANDLER
# ============================================================

@router.errors()
async def error_handler(event: ErrorEvent) -> bool:
    logger.exception(
        "Unhandled error update %s",
        getattr(event.update, "update_id", "?"),
        exc_info=event.exception,
    )
    return True


# ============================================================
# DASHBOARD HTML
# ============================================================

DASHBOARD_STYLES = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
  min-height: 100vh;
  color: #fff;
  padding: 40px 20px;
}
.container { max-width: 1100px; margin: 0 auto; }
header { text-align: center; margin-bottom: 50px; }
h1 {
  font-size: clamp(2rem, 5vw, 3.5rem);
  font-weight: 800;
  background: linear-gradient(135deg, #667eea, #764ba2, #f093fb);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -1px;
}
.tagline {
  color: rgba(255,255,255,0.55);
  margin-top: 12px;
  font-size: 0.95rem;
  letter-spacing: 2px;
  text-transform: uppercase;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 22px;
}
.card {
  background: rgba(255,255,255,0.05);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px;
  padding: 32px;
  position: relative;
  overflow: hidden;
  transition: transform 0.3s;
}
.card:hover { transform: translateY(-4px); }
.card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: linear-gradient(90deg, #667eea, #764ba2, #f093fb);
}
.value {
  font-size: 3rem;
  font-weight: 800;
  background: linear-gradient(135deg, #a8edea, #fed6e3);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.label {
  color: rgba(255,255,255,0.65);
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  margin-top: 8px;
}
.footer {
  text-align: center;
  margin-top: 60px;
  color: rgba(255,255,255,0.4);
  font-size: 0.85rem;
}
.status {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #22c55e;
  margin-right: 8px;
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%,100% { opacity: 1; box-shadow: 0 0 0 0 rgba(34,197,94,0.7); }
  50% { opacity: 0.7; box-shadow: 0 0 0 10px rgba(34,197,94,0); }
}
"""


def render_dashboard(stats: dict[str, int]) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ad_state = "1 running" if (_active_ad and not _active_ad.done()) else "0"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
<title>Premium Emoji Bot · Dashboard</title>
<style>{DASHBOARD_STYLES}</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Premium Emoji Bot</h1>
    <p class="tagline">Live Dashboard · Auto-refresh 30s</p>
  </header>
  <div class="grid">
    <div class="card"><div class="value">{stats['total_users']}</div><div class="label">Total Users</div></div>
    <div class="card"><div class="value">{stats['verified_users']}</div><div class="label">Verified Members</div></div>
    <div class="card"><div class="value">{stats['visits']}</div><div class="label">Total Visits</div></div>
    <div class="card"><div class="value">{stats['emoji_queries']}</div><div class="label">Emoji Queries</div></div>
    <div class="card"><div class="value">{format_uptime()}</div><div class="label">Uptime</div></div>
    <div class="card"><div class="value">{ad_state}</div><div class="label">Active Ads</div></div>
  </div>
  <div class="footer">
    <span class="status"></span> Bot is online · Updated {now_str}
  </div>
</div>
</body>
</html>"""


# ============================================================
# HTTP SERVER (health + dashboard)
# ============================================================

async def health_check(request: Any) -> Any:
    from aiohttp import web
    return web.json_response({
        "status": "ok",
        "service": "premium-emoji-bot",
        "uptime_seconds": int(time.time() - START_TIME),
    })


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
    logger.info("HTTP server on :%s (dashboard: %s/dashboard)", port, DASHBOARD_URL)


# ============================================================
# LIFECYCLE
# ============================================================

async def on_startup(bot: Bot) -> None:
    await init_db()
    await validate_emoji_ids(bot)
    asyncio.create_task(start_http_server())
    logger.info("Bot started. Admins: %s", len(ADMIN_IDS))


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
