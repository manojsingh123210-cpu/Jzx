"""
Premium Custom Emoji ID Bot — Cool Edition
Python 3.11+, aiogram 3.x, SQLite, official Telegram Bot API.
Force-join compulsory. Premium icons on buttons. Colorful styles.
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
    raise RuntimeError("BOT_TOKEN is not set.")

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

# Button icons
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
        logger.warning("Invalid non-numeric emoji ID: %r", emoji_id)
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
        logger.warning("sendMessage failed, retrying without custom emoji: %s", exc)
        fallback = strip_custom_emoji_tags(text)
        try:
            return await message.answer(fallback, **kwargs)
        except TelegramAPIError:
            logger.exception("Fallback also failed")
            try:
                return await message.answer(
                    "⚠️ Could not render this message.",
                    reply_markup=kwargs.get("reply_markup"),
                )
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
        logger.warning("edit failed, retrying without emoji: %s", exc)
    except TelegramAPIError:
        logger.exception("edit failed")
    fallback = strip_custom_emoji_tags(text)
    try:
        await callback.message.edit_text(fallback, **kwargs)
    except TelegramBadRequest as exc2:
        if "message is not modified" in str(exc2).lower():
            return
        with contextlib.suppress(TelegramAPIError):
            await callback.message.answer(fallback, **kwargs)
    except TelegramAPIError:
        logger.exception("fallback edit failed")
        with contextlib.suppress(TelegramAPIError):
            await callback.message.answer(fallback, **kwargs)


# ============================================================
# SAFE BUTTON BUILDER
# ============================================================

def mk_button(**kwargs: Any) -> InlineKeyboardButton:
    try:
        return InlineKeyboardButton(**kwargs)
    except (TypeError, ValueError) as exc:
        logger.warning("Button style unsupported, fallback: %s", exc)
        safe = {k: v for k, v in kwargs.items()
                if k not in ("style", "icon_custom_emoji_id")}
        return InlineKeyboardButton(**safe)


# ============================================================
# KEYBOARDS — Colorful Hierarchy
# ============================================================

def force_join_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(mk_button(
        text="JOIN CHANNEL",
        url=CHANNEL_LINK,
        icon_custom_emoji_id=BTN_JOIN,
        style="success",     # 🟢
    ))
    kb.row(mk_button(
        text="VERIFY JOIN",
        callback_data="verify_join",
        icon_custom_emoji_id=BTN_VERIFY,
        style="primary",     # 🔵
    ))
    kb.row(mk_button(
        text="HELP",
        callback_data="help",
        icon_custom_emoji_id=BTN_HELP,
        style="danger",      # 🔴
    ))
    return kb.as_markup()


def main_menu_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(mk_button(
        text="GET EMOJI ID",
        callback_data="get_id_help",
        icon_custom_emoji_id=BTN_GET_ID,
        style="primary",
    ))
    kb.row(mk_button(
        text="PREMIUM EMOJI COLLECTION",
        callback_data="collection:0",
        icon_custom_emoji_id=BTN_COLLECTION,
        style="success",
    ))
    kb.row(
        mk_button(
            text="HOW TO USE",
            callback_data="howto",
            icon_custom_emoji_id=BTN_HOWTO,
            style="primary",
        ),
        mk_button(
            text="HELP",
            callback_data="help",
            icon_custom_emoji_id=BTN_HELP,
            style="danger",
        ),
    )
    kb.row(mk_button(
        text="CHANNEL",
        url=CHANNEL_LINK,
        icon_custom_emoji_id=BTN_CHANNEL,
        style="success",
    ))
    return kb.as_markup()


def collection_keyboard(page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(mk_button(
            text="BACK",
            callback_data=f"collection:{page - 1}",
            icon_custom_emoji_id=BTN_BACK,
            style="primary",
        ))
    nav.append(mk_button(
        text="HOME",
        callback_data="home",
        icon_custom_emoji_id=BTN_HOME,
        style="success",
    ))
    if page < TOTAL_PAGES - 1:
        nav.append(mk_button(
            text="NEXT",
            callback_data=f"collection:{page + 1}",
            icon_custom_emoji_id=BTN_NEXT,
            style="primary",
        ))
    kb.row(*nav)
    return kb.as_markup()


# ============================================================
# TEXT BUILDERS — Cool Aesthetic Edition
# ============================================================

def force_join_text() -> str:
    return (
        f"{header('ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ ʙᴏᴛ')}\n\n"
        f"{e(1)} <b>🔒 ᴀᴄᴄᴇꜱꜱ ʟᴏᴄᴋᴇᴅ</b>\n\n"
        f"{e(6)} ᴛᴏ ᴜɴʟᴏᴄᴋ ᴛʜɪꜱ ʙᴏᴛ, ʏᴏᴜ ᴍᴜꜱᴛ ᴊᴏɪɴ ᴏᴜʀ ᴏꜰꜰɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ.\n\n"
        f"{DIV_LIGHT}\n\n"
        f"❶ {e(11)} ᴛᴀᴘ  ➜  <b>ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ</b>\n"
        f"❷ {e(16)} ʀᴇᴛᴜʀɴ  ➜  <b>ᴠᴇʀɪꜰʏ ᴊᴏɪɴ</b>\n"
        f"❸ {e(21)} ᴇɴᴊᴏʏ  ➜  ꜰᴜʟʟ ᴀᴄᴄᴇꜱꜱ 🔓\n\n"
        f"{footer('⚡ ɪɴꜱᴛᴀɴᴛ · ꜱᴇᴄᴜʀᴇ · ꜰᴀꜱᴛ')}"
    )


def force_join_reminder_text() -> str:
    return (
        f"{header('ᴀᴄᴄᴇꜱꜱ ʟᴏᴄᴋᴇᴅ')}\n\n"
        f"{e(2)} ᴛʜɪꜱ ʙᴏᴛ ɪꜱ ᴀᴠᴀɪʟᴀʙʟᴇ ᴏɴʟʏ ᴛᴏ ᴄʜᴀɴɴᴇʟ ᴍᴇᴍʙᴇʀꜱ.\n\n"
        f"{e(7)} ᴛᴀᴘ <b>ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ</b> → ᴊᴏɪɴ → ᴛᴀᴘ <b>ᴠᴇʀɪꜰʏ ᴊᴏɪɴ</b>"
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
        f"{footer('🚀 ꜰᴀꜱᴛ · ꜱɪᴍᴘʟᴇ · ᴀᴄᴄᴜʀᴀᴛᴇ')}"
    )


def no_emoji_text() -> str:
    return (
        f"{header('ɴᴏ ᴇᴍᴏᴊɪ ꜰᴏᴜɴᴅ')}\n\n"
        f"{e(3)} ɴᴏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ᴅᴇᴛᴇᴄᴛᴇᴅ ɪɴ ʏᴏᴜʀ ᴍᴇꜱꜱᴀɢᴇ\n\n"
        f"{e(9)} ꜱᴇɴᴅ ᴀ ᴍᴇꜱꜱᴀɢᴇ ᴛʜᴀᴛ ᴄᴏɴᴛᴀɪɴꜱ ᴀᴛ ʟᴇᴀꜱᴛ ᴏɴᴇ\n"
        f"   ᴛᴇʟᴇɢʀᴀᴍ <b>ᴘʀᴇᴍɪᴜᴍ</b> ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(14)} <i>ᴏʀᴅɪɴᴀʀʏ ᴜɴɪᴄᴏᴅᴇ ᴇᴍᴏᴊɪꜱ ꜱᴜᴄʜ ᴀꜱ 😀 ᴏʀ ❤️\n"
        f"ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ɪᴅꜱ</i>\n\n"
        f"{footer('💡 ᴏɴʟʏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪꜱ ʜᴀᴠᴇ ɪᴅꜱ')}"
    )


def get_id_help_text() -> str:
    return (
        f"{header('ɢᴇᴛ ᴇᴍᴏᴊɪ ɪᴅ')}\n\n"
        f"{e(4)} <b>3 ꜱᴛᴇᴘꜱ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ᴇᴍᴏᴊɪ ɪᴅ:</b>\n\n"
        f"❶ {e(9)} ᴏᴘᴇɴ ᴀɴʏ ᴄʜᴀᴛ ᴡɪᴛʜ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪꜱ\n"
        f"❷ {e(14)} ꜱᴇɴᴅ ᴀ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ʜᴇʀᴇ\n"
        f"❸ {e(19)} ʀᴇᴄᴇɪᴠᴇ ɪᴛꜱ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ɪᴅ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(24)} <b>ꜱᴜᴘᴘᴏʀᴛꜱ:</b>\n"
        f"   • ꜱɪɴɢʟᴇ ᴇᴍᴏᴊɪ\n"
        f"   • ᴍᴜʟᴛɪᴘʟᴇ ᴇᴍᴏᴊɪꜱ\n"
        f"   • ᴇᴍᴏᴊɪꜱ ᴍɪxᴇᴅ ᴡɪᴛʜ ᴛᴇxᴛ\n\n"
        f"{footer('💡 ᴛɪᴘ · ᴛᴀᴘ ᴛʜᴇ ɪᴅ ᴛᴏ ᴄᴏᴘʏ ɪᴛ')}"
    )


def how_to_text() -> str:
    return (
        f"{header('ʜᴏᴡ ᴛᴏ ᴜꜱᴇ')}\n\n"
        f"{e(7)} <b>❶ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ</b>\n"
        f"   ᴛᴀᴘ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ ᴀɴᴅ ꜰᴏʟʟᴏᴡ ᴛʜᴇ ʟɪɴᴋ\n\n"
        f"{e(12)} <b>❷ ᴠᴇʀɪꜰʏ ᴍᴇᴍʙᴇʀꜱʜɪᴘ</b>\n"
        f"   ʀᴇᴛᴜʀɴ ᴀɴᴅ ᴛᴀᴘ ᴠᴇʀɪꜰʏ ᴊᴏɪɴ\n\n"
        f"{e(17)} <b>❸ ꜱᴇɴᴅ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ</b>\n"
        f"   ʙᴏᴛ ʀᴇᴘʟɪᴇꜱ ᴡɪᴛʜ ɪᴛꜱ ɪᴅ\n\n"
        f"{e(22)} <b>❹ ʙʀᴏᴡꜱᴇ ᴄᴏʟʟᴇᴄᴛɪᴏɴ</b>\n"
        f"   ᴏᴘᴇɴ ᴘʀᴇᴍɪᴜᴍ ᴄᴏʟʟᴇᴄᴛɪᴏɴ ꜰᴏʀ ᴀʟʟ ɪᴅꜱ\n\n"
        f"{footer('⚠️ ʀᴇɴᴅᴇʀɪɴɢ ᴅᴇᴘᴇɴᴅꜱ ᴏɴ ᴛᴇʟᴇɢʀᴀᴍ ᴄʟɪᴇɴᴛ')}"
    )


def help_text() -> str:
    return (
        f"{header('ʜᴇʟᴘ ᴄᴇɴᴛᴇʀ')}\n\n"
        f"{e(8)} <b>· ʜᴏᴡ ᴅᴏ ɪ ɢᴇᴛ ᴀɴ ᴇᴍᴏᴊɪ ɪᴅ?</b>\n"
        "   ꜱᴇɴᴅ ᴀ ᴛᴇʟᴇɢʀᴀᴍ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ᴛᴏ ᴛʜᴇ ʙᴏᴛ\n\n"
        "<b>· ᴡʜʏ ᴏʀᴅɪɴᴀʀʏ ᴇᴍᴏᴊɪꜱ ꜰᴀɪʟ?</b>\n"
        "   ᴏɴʟʏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪꜱ ʜᴀᴠᴇ ɪᴅꜱ\n\n"
        "<b>· ɴᴏʀᴍᴀʟ ᴇᴍᴏᴊɪ ɪɴꜱᴛᴇᴀᴅ ᴏꜰ ᴄᴜꜱᴛᴏᴍ?</b>\n"
        "   ᴛᴇʟᴇɢʀᴀᴍ ᴍᴀʏ ʀᴇᴊᴇᴄᴛ ɪᴛ · ʙᴏᴛ ꜰᴀʟʟꜱ ʙᴀᴄᴋ ꜱᴀꜰᴇʟʏ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(13)} <b>ᴀᴅᴍɪɴ ᴄᴏɴᴛᴀᴄᴛꜱ</b>\n"
        f"   👤 @cytunn\n"
        f"   👤 @R0syug\n\n"
        f"{e(18)} <b>ᴄʜᴀɴɴᴇʟ</b>\n"
        f'   <a href="{CHANNEL_LINK}">{CHANNEL_LINK}</a>\n\n'
        f"{footer('💫 ɴᴇᴇᴅ ᴍᴏʀᴇ ʜᴇʟᴘ? ᴛᴀᴘ ᴀɴ ᴀᴅᴍɪɴ ᴀʙᴏᴠᴇ')}"
    )


def build_emoji_response(ids: list[str]) -> str:
    if len(ids) == 1:
        eid = ids[0]
        return (
            f"{header('ᴘʀᴇᴍɪᴜᴍ ᴅᴇᴛᴇᴄᴛᴇᴅ')}\n\n"
            f"{custom_emoji(eid, '💎')} <b>ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ɪᴅ</b>\n\n"
            f"<code>{html.escape(eid)}</code>\n\n"
            f"{footer('👆 ᴛᴀᴘ ᴛʜᴇ ɪᴅ ᴀʙᴏᴠᴇ ᴛᴏ ᴄᴏᴘʏ')}"
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
    lines.append(footer("👆 ᴛᴀᴘ ᴀɴ ɪᴅ ᴛᴏ ᴄᴏᴘʏ"))
    return "\n".join(lines)


def build_collection_page(page: int) -> str:
    page = max(0, min(page, TOTAL_PAGES - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(EMOJI_IDS))
    lines = [
        header('ᴘʀᴇᴍɪᴜᴍ ᴄᴏʟʟᴇᴄᴛɪᴏɴ'),
        "",
        f"📄 ᴘᴀɢᴇ <b>{page + 1}</b> / {TOTAL_PAGES}",
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
    lines.append(footer("👆 ᴛᴀᴘ ᴀɴ ɪᴅ ᴛᴏ ᴄᴏᴘʏ"))
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
        row = await cur.fetchone()
        queries = row[0] if row else 0
    return {"total_users": total, "verified_users": verified, "emoji_queries": queries}


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
        logger.warning("getChatMember failed: %s", exc)
        if "user not found" in text or "participant_id_invalid" in text:
            result = (False, "not_member")
        elif "chat not found" in text or "chat_admin_required" in text:
            result = (False, "config_error")
        else:
            result = (False, "api_error")
    except TelegramAPIError as exc:
        logger.warning("API error: %s", exc)
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
            await event.answer(
                "❌ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ, ᴛʜᴇɴ ᴛᴀᴘ ᴠᴇʀɪꜰʏ ᴊᴏɪɴ.",
                show_alert=True,
            )
            return None
        if isinstance(event, Message):
            await safe_answer(
                event,
                force_join_reminder_text(),
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
        logger.info("Validation disabled")
        return
    if not hasattr(bot, "get_custom_emoji_stickers"):
        logger.info("Emoji validation unavailable")
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
        except TelegramAPIError as exc:
            logger.warning("Validation failed for %s: %s", eid, exc)
        await asyncio.sleep(0.05)
    logger.info("Emoji validation: %s/%s working", working, len(EMOJI_IDS))


# ============================================================
# HANDLERS
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    await upsert_user(message.from_user)
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
        await callback.answer("✅ ᴠᴇʀɪꜰɪᴇᴅ! ᴡᴇʟᴄᴏᴍᴇ.")
        return
    if reason == "config_error":
        await callback.answer(
            "⚠️ Channel config error. Contact admin.", show_alert=True
        )
    elif reason == "api_error":
        await callback.answer(
            "⚠️ Cannot check membership right now. Try again.", show_alert=True
        )
    else:
        await callback.answer(
            "❌ ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ ᴊᴏɪɴᴇᴅ ʏᴇᴛ. ᴊᴏɪɴ ᴛʜᴇɴ ᴛᴀᴘ ᴠᴇʀɪꜰʏ.",
            show_alert=True,
        )


@router.callback_query(F.data == "home")
async def cb_home(callback: CallbackQuery, bot: Bot) -> None:
    ok, _ = await is_member(bot, callback.from_user.id)
    if not ok:
        await callback.answer("❌ Join the channel first.", show_alert=True)
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


def format_uptime() -> str:
    seconds = int(time.time() - START_TIME)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


@router.message(Command("admin", "stats"), IsAdmin())
async def cmd_admin_stats(message: Message) -> None:
    stats = await get_stats()
    text = (
        f"{header('ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ')}\n\n"
        f"{e(19)} <b>· ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ</b> · <code>{stats['total_users']}</code>\n"
        f"{e(20)} <b>· ᴠᴇʀɪꜰɪᴇᴅ</b> · <code>{stats['verified_users']}</code>\n"
        f"{e(21)} <b>· Qᴜᴇʀɪᴇꜱ</b> · <code>{stats['emoji_queries']}</code>\n"
        f"{e(22)} <b>· ᴜᴘᴛɪᴍᴇ</b> · <code>{format_uptime()}</code>\n\n"
        f"{footer('📊 ᴅᴀᴛᴀʙᴀꜱᴇ · ' + html.escape(DB_PATH))}"
    )
    await safe_answer(message, text, link_preview_options=NO_PREVIEW)


@router.message(Command("broadcast"), IsAdmin())
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting)
    await safe_answer(
        message,
        f"{header('ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴍᴏᴅᴇ')}\n\n"
        "ꜱᴇɴᴅ ᴛʜᴇ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ʙʀᴏᴀᴅᴄᴀꜱᴛ\n"
        "ɪᴛ ᴡɪʟʟ ʙᴇ ᴄᴏᴘɪᴇᴅ ᴛᴏ ᴇᴠᴇʀʏ ᴜꜱᴇʀ\n\n"
        f"{footer('💡 /cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        link_preview_options=NO_PREVIEW,
    )


@router.message(Command("cancel"), StateFilter(BroadcastStates.waiting))
async def cmd_cancel_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(message, "✅ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴀɴᴄᴇʟʟᴇᴅ")


@router.message(StateFilter(BroadcastStates.waiting), IsAdmin())
async def do_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user_ids = await all_user_ids()
    status = await safe_answer(
        message,
        f"📤 ʙʀᴏᴀᴅᴄᴀꜱᴛɪɴɢ ᴛᴏ <b>{len(user_ids)}</b> ᴜꜱᴇʀꜱ...",
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
        with contextlib.suppress(TelegramAPIError):
            await status.edit_text(
                f"✅ <b>ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴏᴍᴘʟᴇᴛᴇ</b>\n\n"
                f"ꜱᴇɴᴛ · <code>{sent}</code>\n"
                f"ꜰᴀɪʟᴇᴅ · <code>{failed}</code>"
            )


@router.errors()
async def error_handler(event: ErrorEvent) -> bool:
    logger.exception(
        "Unhandled error update %s",
        getattr(event.update, "update_id", "?"),
        exc_info=event.exception,
    )
    return True


# ============================================================
# HEALTH SERVER
# ============================================================

async def health_check(request: Any) -> Any:
    from aiohttp import web
    return web.json_response({
        "status": "ok", "uptime_seconds": int(time.time() - START_TIME)
    })


async def start_health_server() -> None:
    global _health_runner
    from aiohttp import web
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    _health_runner = web.AppRunner(app)
    await _health_runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(_health_runner, "0.0.0.0", port).start()
    logger.info("Health server on :%s", port)


# ============================================================
# LIFECYCLE
# ============================================================

async def on_startup(bot: Bot) -> None:
    await init_db()
    await validate_emoji_ids(bot)
    asyncio.create_task(start_health_server())
    logger.info("Bot started. Admins: %s", len(ADMIN_IDS))


async def on_shutdown(bot: Bot) -> None:
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
