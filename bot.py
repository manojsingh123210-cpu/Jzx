"""
Premium Custom Emoji ID Bot
Python 3.11+, aiogram 3.x, SQLite, official Telegram Bot API.

IMPORTANT:
- This file does NOT contain a bot token.
- Put BOT_TOKEN in .env locally or in Render environment variables.
"""

from __future__ import annotations

import asyncio
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
    InlineKeyboardBuilder,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB  # noqa: F401
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
    raise RuntimeError(
        "BOT_TOKEN is not set. Create a .env file or add BOT_TOKEN in Render."
    )

# The 25 supplied custom emoji IDs. Do not modify or generate replacements.
EMOJI_IDS: list[str] = [
    "5357592447557848986",
    "5258387666616994756",
    "5391118489824015979",
    "5334665104677941170",
    "5289862389552919154",
    "5397730656400714154",
    "5301275719681190738",
    "5301096984617166561",
    "5386521874089914548",
    "5332423642850536254",
    "5264892613630111886",
    "5258113901106580375",
    "5258212320282168974",
    "5258274739041883702",
    "5258457030338844822",
    "5260373152688540294",
    "5258420785109830474",
    "5258178411515382761",
    "5260691173541970181",
    "6014620343883273557",
    "6015104451122042405",
    "6104794084205925773",
    "6104675564583392962",
    "6107015024679592166",
    "6120548140211770562",
]

# Unicode fallbacks shown if a custom emoji cannot be rendered.
EMOJI_FALLBACKS: list[str] = [
    "✨", "💎", "⭐", "🔥", "👑",
    "🆔", "📖", "🛠", "📢", "🎯",
    "💫", "🌟", "❤️", "🧡", "💛",
    "💚", "💙", "💜", "🖤", "🤍",
    "🚀", "🎉", "🏆", "🔔", "📌",
]

PAGE_SIZE: int = 5
TOTAL_PAGES: int = math.ceil(len(EMOJI_IDS) / PAGE_SIZE)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

START_TIME: float = time.time()

# Cache used for optional startup validation.
# True  = Telegram confirmed the ID exists.
# False = Telegram rejected the ID.
# missing = unknown; still attempt rendering.
VALID_EMOJI_CACHE: dict[str, Optional[bool]] = {}

# Membership cache to avoid calling getChatMember on every message.
_membership_cache: dict[int, tuple[float, bool, str]] = {}
MEMBERSHIP_CACHE_TTL: int = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("premium-emoji-bot")

router = Router()


# ============================================================
# CUSTOM EMOJI HELPER
# ============================================================

def custom_emoji(emoji_id: str, fallback: str = "✨") -> str:
    """
    Return Telegram HTML custom emoji markup.

    Format:
        <tg-emoji emoji-id="1234567890">✨</tg-emoji>

    If the ID is not numeric, or if startup validation marked it as invalid,
    return the escaped Unicode fallback instead.
    """
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
    """Pick a custom emoji by index, cycling through the 25 supplied IDs."""
    idx = index % len(EMOJI_IDS)
    return custom_emoji(EMOJI_IDS[idx], fallback or EMOJI_FALLBACKS[idx])


CUSTOM_EMOJI_TAG_RE = re.compile(
    r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>",
    re.IGNORECASE | re.DOTALL,
)


def strip_custom_emoji_tags(text: str) -> str:
    """Remove custom emoji tags but keep the fallback text."""
    return CUSTOM_EMOJI_TAG_RE.sub(r"\1", text)


async def safe_answer(message: Message, text: str, **kwargs: Any) -> Optional[Message]:
    """
    Send a message and gracefully fall back if Telegram rejects a custom emoji.
    """
    try:
        return await message.answer(text, **kwargs)
    except TelegramBadRequest as exc:
        logger.warning("sendMessage failed, retrying without custom emoji: %s", exc)
        fallback = strip_custom_emoji_tags(text)
        try:
            return await message.answer(fallback, **kwargs)
        except TelegramAPIError:
            logger.exception("Fallback message also failed")
            try:
                return await message.answer(
                    "⚠️ Could not render this message. Please try again.",
                    reply_markup=kwargs.get("reply_markup"),
                )
            except TelegramAPIError:
                return None


async def safe_edit(callback: CallbackQuery, text: str, **kwargs: Any) -> None:
    """Edit a callback message, falling back if content is identical or emoji fail."""
    if not isinstance(callback.message, Message):
        return

    try:
        await callback.message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        msg = str(exc).lower()
        if "message is not modified" in msg:
            return
        logger.warning("editMessageText failed, retrying without custom emoji: %s", exc)
        fallback = strip_custom_emoji_tags(text)
        try:
            await callback.message.edit_text(fallback, **kwargs)
        except TelegramBadRequest as exc2:
            if "message is not modified" in str(exc2).lower():
                return
            await callback.message.answer(fallback, **kwargs)
        except TelegramAPIError:
            logger.exception("Fallback edit failed")
    except TelegramAPIError:
        logger.exception("editMessageText failed")
        with_suppress = contextlib_suppress_telegram()
        with with_suppress:
            await callback.message.answer(text, **kwargs)


class contextlib_suppress_telegram:
    """Tiny context manager to suppress Telegram errors during fallback."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return exc_type is not None and issubclass(exc_type, TelegramAPIError)


# ============================================================
# DATABASE
# ============================================================

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                is_verified INTEGER NOT NULL DEFAULT 0,
                joined_at   TEXT NOT NULL,
                last_seen   TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS stats (
                key   TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.commit()
    logger.info("SQLite database ready: %s", DB_PATH)


async def upsert_user(user: Any) -> None:
    if user is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, username, first_name, joined_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                last_seen  = excluded.last_seen
            """,
            (user.id, user.username, user.first_name, now, now),
        )
        await db.commit()


async def mark_verified(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_verified = 1 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()


async def increment_stat(key: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO stats (key, value) VALUES (?, 1)
            ON CONFLICT(key) DO UPDATE SET value = value + 1
            """,
            (key,),
        )
        await db.commit()


async def get_stats() -> dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_verified = 1")
        verified_users = (await cur.fetchone())[0]

        cur = await db.execute("SELECT value FROM stats WHERE key = 'emoji_queries'")
        row = await cur.fetchone()
        emoji_queries = row[0] if row else 0

    return {
        "total_users": total_users,
        "verified_users": verified_users,
        "emoji_queries": emoji_queries,
    }


async def all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()
    return [row[0] for row in rows]


# ============================================================
# MEMBERSHIP CHECK
# ============================================================

async def is_member(bot: Bot, user_id: int, force: bool = False) -> tuple[bool, str]:
    """
    Check whether a user is a member of the required channel.

    Returns:
        (is_member, reason)
        reason: "member", "not_member", "config_error", "api_error"
    """
    now = time.monotonic()
    if not force:
        cached = _membership_cache.get(user_id)
        if cached and now - cached[0] < MEMBERSHIP_CACHE_TTL:
            return cached[1], cached[2]

    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
    except TelegramBadRequest as exc:
        text = str(exc).lower()
        logger.warning("getChatMember failed for user %s: %s", user_id, exc)

        if "user not found" in text or "participant_id_invalid" in text:
            result = (False, "not_member")
        elif "chat not found" in text or "chat_admin_required" in text:
            result = (False, "config_error")
        else:
            result = (False, "api_error")
    except TelegramAPIError as exc:
        logger.warning("Telegram API error during membership check: %s", exc)
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

        # Always allow /start so the welcome screen can be shown.
        if isinstance(event, Message):
            if event.text and event.text.split()[0].lower().startswith("/start"):
                return await handler(event, data)

        # Always allow the verify callback.
        if isinstance(event, CallbackQuery) and event.data == "verify_join":
            return await handler(event, data)

        ok, _reason = await is_member(bot, user.id)
        if ok:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(
                "❌ Join the channel first, then tap Verify Join.",
                show_alert=True,
            )
            return None

        if isinstance(event, Message):
            await safe_answer(
                event,
                force_join_text(),
                reply_markup=force_join_keyboard(),
                link_preview_options=NO_PREVIEW,
            )
            return None

        return None


# ============================================================
# KEYBOARDS
# ============================================================

def force_join_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 JOIN CHANNEL", url=CHANNEL_LINK)
    kb.button(text="🔵 VERIFY JOIN", callback_data="verify_join")
    kb.button(text="🔴 HELP", callback_data="help")
    kb.adjust(1)
    return kb.as_markup()


def main_menu_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🆔 GET EMOJI ID", callback_data="get_id_help")
    kb.button(text="👑 PREMIUM EMOJI COLLECTION", callback_data="collection:0")
    kb.button(text="📖 HOW TO USE", callback_data="howto")
    kb.button(text="🛠 HELP", callback_data="help")
    kb.button(text="📢 CHANNEL", url=CHANNEL_LINK)
    kb.adjust(1)
    return kb.as_markup()


def collection_keyboard(page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    nav: list[Any] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ BACK", callback_data=f"collection:{page - 1}"))
    nav.append(InlineKeyboardButton(text="🏠 HOME", callback_data="home"))
    if page < TOTAL_PAGES - 1:
        nav.append(InlineKeyboardButton(text="NEXT ➡️", callback_data=f"collection:{page + 1}"))
    kb.row(*nav)
    return kb.as_markup()


from aiogram.types import InlineKeyboardButton  # noqa: E402


# ============================================================
# TEXT BUILDERS
# ============================================================

def force_join_text() -> str:
    return (
        f"{e(1)} <b>Welcome to the Premium Emoji ID Bot!</b>\n\n"
        f"{e(6)} To use this bot, please join our official channel first.\n\n"
        f"{e(11)} <b>Step 1:</b> Tap <b>JOIN CHANNEL</b> below.\n"
        f"{e(16)} <b>Step 2:</b> Return here and tap <b>VERIFY JOIN</b>.\n\n"
        f"{e(21)} After verification, you will unlock the full premium dashboard."
    )


def main_menu_text() -> str:
    return (
        f"{e(0)} <b>Welcome to the Premium Emoji ID Bot!</b>\n\n"
        f"{e(5)} Send any Telegram custom premium emoji to discover its ID.\n\n"
        f"{e(10)} Your emoji will be analyzed automatically.\n\n"
        f"{e(15)} <i>Fast. Simple. Accurate.</i>"
    )


def no_emoji_text() -> str:
    return (
        f"{e(3)} <b>No premium custom emoji found.</b>\n\n"
        "Send a message that contains at least one Telegram Premium custom emoji.\n\n"
        "Ordinary Unicode emojis such as 😀 or ❤️ do not have custom emoji IDs. "
        "Only Telegram Premium custom emojis have IDs."
    )


def get_id_help_text() -> str:
    return (
        f"{e(4)} <b>GET EMOJI ID</b>\n\n"
        "1. Open any chat where you can use Telegram Premium custom emojis.\n"
        "2. Send a custom emoji to this bot.\n"
        "3. The bot will read the <code>custom_emoji</code> entity and reply with its ID.\n\n"
        f"{e(9)} You can send one emoji, several emojis, or emojis mixed with text.\n\n"
        "<i>Tip: Tap the ID in the bot's reply to copy it.</i>"
    )


def how_to_text() -> str:
    return (
        f"{e(7)} <b>HOW TO USE</b>\n\n"
        f"{e(12)} <b>1. Join the channel</b>\n"
        "Tap JOIN CHANNEL and follow the link.\n\n"
        f"{e(17)} <b>2. Verify membership</b>\n"
        "Return to the bot and tap VERIFY JOIN.\n\n"
        f"{e(22)} <b>3. Send a premium emoji</b>\n"
        "Send a Telegram Premium custom emoji. The bot replies with its ID.\n\n"
        f"{e(2)} <b>4. Browse the collection</b>\n"
        "Open PREMIUM EMOJI COLLECTION to see all supplied IDs.\n\n"
        "<i>Custom emoji rendering depends on Telegram's Bot API and whether the ID "
        "is available in that context. A Unicode fallback is shown if rendering fails.</i>"
    )


def help_text() -> str:
    return (
        f"{e(8)} <b>HELP</b>\n\n"
        "<b>How do I get an emoji ID?</b>\n"
        "Send a Telegram Premium custom emoji to the bot.\n\n"
        "<b>Why did my ordinary emoji not work?</b>\n"
        "Only Telegram Premium custom emojis have custom emoji IDs. "
        "Unicode emojis do not.\n\n"
        "<b>Why do I see a normal emoji instead of the custom one?</b>\n"
        "Telegram may reject a custom emoji in some contexts, or the recipient may "
        "not support Premium custom emoji rendering. The bot falls back safely.\n\n"
        f"{e(13)} <b>Admin contacts:</b>\n"
        "@cytunn\n"
        "@R0syug\n\n"
        f"{e(18)} <b>Channel:</b>\n"
        f'<a href="{CHANNEL_LINK}">{CHANNEL_LINK}</a>'
    )


def build_emoji_response(ids: list[str]) -> str:
    if len(ids) == 1:
        eid = ids[0]
        return (
            f"{custom_emoji(eid, '💎')} <b>PREMIUM EMOJI DETECTED</b>\n\n"
            f"<b>Custom Emoji ID:</b>\n"
            f"<code>{html.escape(eid)}</code>\n\n"
            "<i>Tap and copy the ID.</i>"
        )

    lines = [
        f"{e(0)} <b>PREMIUM EMOJIS DETECTED</b>",
        "",
        f"<b>Found {len(ids)} custom emojis:</b>",
        "",
    ]
    for i, eid in enumerate(ids, start=1):
        lines.append(
            f"{i}. {custom_emoji(eid, '✨')} <code>{html.escape(eid)}</code>"
        )
    lines.append("")
    lines.append("<i>Tap an ID to copy it.</i>")
    return "\n".join(lines)


def build_collection_page(page: int) -> str:
    page = max(0, min(page, TOTAL_PAGES - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(EMOJI_IDS))

    lines = [
        f"{e(page)} <b>PREMIUM EMOJI COLLECTION</b>",
        f"<i>Page {page + 1} / {TOTAL_PAGES}</i>",
        "",
    ]

    for number, emoji_id in enumerate(EMOJI_IDS[start:end], start=start + 1):
        fallback = EMOJI_FALLBACKS[(number - 1) % len(EMOJI_FALLBACKS)]
        lines.append(
            f"{number}. {custom_emoji(emoji_id, fallback)} "
            f"<code>{html.escape(emoji_id)}</code>"
        )

    lines.append("")
    lines.append("<i>Tap an ID to copy it.</i>")
    return "\n".join(lines)


# ============================================================
# STARTUP EMOJI VALIDATION
# ============================================================

async def validate_emoji_ids(bot: Bot) -> None:
    """
    Optionally check each custom emoji ID with get_custom_emoji_stickers.

    This confirms the ID exists on Telegram's side. It does not guarantee
    that every client will render it, so send failures are still handled.
    """
    if not VALIDATE_EMOJI:
        logger.info("Emoji validation disabled by VALIDATE_EMOJI=0")
        return

    if not hasattr(bot, "get_custom_emoji_stickers"):
        logger.info("get_custom_emoji_stickers unavailable; skipping validation")
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
                logger.warning("Custom emoji ID returned no sticker: %s", eid)
        except TelegramAPIError as exc:
            # Leave the cache entry missing so the bot still attempts rendering.
            logger.warning("Validation failed for %s: %s", eid, exc)
        await asyncio.sleep(0.05)

    logger.info(
        "Custom emoji validation complete: %s/%s confirmed working",
        working,
        len(EMOJI_IDS),
    )


# ============================================================
# HANDLERS: START / VERIFY / MENU
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    await upsert_user(message.from_user)
    ok, _ = await is_member(bot, message.from_user.id, force=True)

    if ok:
        await mark_verified(message.from_user.id)
        await safe_answer(
            message,
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            link_preview_options=NO_PREVIEW,
        )
    else:
        await safe_answer(
            message,
            force_join_text(),
            reply_markup=force_join_keyboard(),
            link_preview_options=NO_PREVIEW,
        )


@router.callback_query(F.data == "verify_join")
async def cb_verify_join(callback: CallbackQuery, bot: Bot) -> None:
    ok, reason = await is_member(bot, callback.from_user.id, force=True)

    if ok:
        await mark_verified(callback.from_user.id)
        await safe_edit(
            callback,
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            link_preview_options=NO_PREVIEW,
        )
        await callback.answer("✅ Verified! Welcome.")
        return

    if reason == "config_error":
        await callback.answer(
            "⚠️ Channel configuration error. Please contact the admin.",
            show_alert=True,
        )
    elif reason == "api_error":
        await callback.answer(
            "⚠️ Could not check membership right now. Try again in a moment.",
            show_alert=True,
        )
    else:
        await callback.answer(
            "❌ You have not joined the channel yet. Join first, then tap Verify Join.",
            show_alert=True,
        )


@router.callback_query(F.data == "home")
async def cb_home(callback: CallbackQuery, bot: Bot) -> None:
    ok, _ = await is_member(bot, callback.from_user.id)
    if not ok:
        await callback.answer("❌ Join the channel first.", show_alert=True)
        return
    await safe_edit(
        callback,
        main_menu_text(),
        reply_markup=main_menu_keyboard(),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.callback_query(F.data == "get_id_help")
async def cb_get_id_help(callback: CallbackQuery) -> None:
    await safe_edit(
        callback,
        get_id_help_text(),
        reply_markup=main_menu_keyboard(),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.callback_query(F.data == "howto")
async def cb_howto(callback: CallbackQuery) -> None:
    await safe_edit(
        callback,
        how_to_text(),
        reply_markup=main_menu_keyboard(),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery) -> None:
    await safe_edit(
        callback,
        help_text(),
        reply_markup=main_menu_keyboard(),
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
        callback,
        build_collection_page(page),
        reply_markup=collection_keyboard(page),
        link_preview_options=NO_PREVIEW,
    )
    await callback.answer()


# ============================================================
# EMOJI ID EXTRACTION
# ============================================================

@router.message(StateFilter(None))
async def handle_any_message(message: Message, bot: Bot) -> None:
    """
    Extract custom emoji IDs from text and captions.

    This handler is registered after commands and admin FSM handlers.
    StateFilter(None) prevents it from interfering with the broadcast flow.
    """
    entities = list(message.entities or []) + list(message.caption_entities or [])
    custom_entities = [
        entity for entity in entities if entity.type == "custom_emoji"
    ]
    custom_entities.sort(key=lambda entity: entity.offset)

    ids = [
        entity.custom_emoji_id
        for entity in custom_entities
        if entity.custom_emoji_id
    ]

    if ids:
        await increment_stat("emoji_queries")
        await safe_answer(
            message,
            build_emoji_response(ids),
            link_preview_options=NO_PREVIEW,
        )
    else:
        await safe_answer(
            message,
            no_emoji_text(),
            reply_markup=main_menu_keyboard(),
            link_preview_options=NO_PREVIEW,
        )


# ============================================================
# ADMIN PANEL
# ============================================================

class IsAdmin(BaseFilter):
    async def __call__(self, event: Any, **kwargs: Any) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in ADMIN_IDS


class BroadcastStates(StatesGroup):
    waiting = State()


def format_uptime() -> str:
    seconds = int(time.time() - START_TIME)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h {minutes}m {secs}s"


@router.message(Command("admin", "stats"), IsAdmin())
async def cmd_admin_stats(message: Message) -> None:
    stats = await get_stats()
    text = (
        f"{e(19)} <b>ADMIN PANEL</b>\n\n"
        f"<b>Total users:</b> <code>{stats['total_users']}</code>\n"
        f"<b>Verified users:</b> <code>{stats['verified_users']}</code>\n"
        f"<b>Emoji queries:</b> <code>{stats['emoji_queries']}</code>\n"
        f"<b>Uptime:</b> <code>{format_uptime()}</code>\n\n"
        f"<i>Database:</i> <code>{html.escape(DB_PATH)}</code>"
    )
    await safe_answer(message, text, link_preview_options=NO_PREVIEW)


@router.message(Command("broadcast"), IsAdmin())
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting)
    await safe_answer(
        message,
        f"{e(23)} <b>Broadcast mode</b>\n\n"
        "Send the message you want to broadcast.\n"
        "It will be copied to every known user.\n\n"
        "Send /cancel to abort.",
        link_preview_options=NO_PREVIEW,
    )


@router.message(Command("cancel"), StateFilter(BroadcastStates.waiting))
async def cmd_cancel_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(message, "✅ Broadcast cancelled.")


@router.message(StateFilter(BroadcastStates.waiting), IsAdmin())
async def do_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user_ids = await all_user_ids()

    status_msg = await safe_answer(
        message,
        f"📤 Broadcasting to <b>{len(user_ids)}</b> users...",
        link_preview_options=NO_PREVIEW,
    )

    sent = 0
    failed = 0

    for user_id in user_ids:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            sent += 1
        except TelegramRetryAfter as exc:
            logger.warning("Broadcast rate limit, sleeping %s seconds", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
                sent += 1
            except TelegramAPIError:
                failed += 1
        except TelegramForbiddenError:
            failed += 1
        except TelegramAPIError as exc:
            logger.warning("Broadcast to %s failed: %s", user_id, exc)
            failed += 1

        await asyncio.sleep(0.05)

    if status_msg:
        try:
            await status_msg.edit_text(
                f"✅ <b>Broadcast complete.</b>\n\n"
                f"Sent: <code>{sent}</code>\n"
                f"Failed: <code>{failed}</code>"
            )
        except TelegramAPIError:
            logger.exception("Could not edit broadcast status message")


# ============================================================
# ERROR HANDLER
# ============================================================

@router.errors()
async def error_handler(event: ErrorEvent) -> bool:
    logger.exception(
        "Unhandled error while processing update %s",
        getattr(event.update, "update_id", "unknown"),
        exc_info=event.exception,
    )
    return True


# ============================================================
# RENDER HEALTH SERVER
# ============================================================

async def health_check(request: Any) -> Any:
    from aiohttp import web

    return web.json_response(
        {
            "status": "ok",
            "service": "premium-emoji-id-bot",
            "uptime_seconds": int(time.time() - START_TIME),
        }
    )


async def start_health_server() -> None:
    from aiohttp import web

    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health server listening on 0.0.0.0:%s", port)


# ============================================================
# LIFECYCLE
# ============================================================

async def on_startup(bot: Bot) -> None:
    await init_db()
    await validate_emoji_ids(bot)
    asyncio.create_task(start_health_server())
    logger.info("Bot started. Admins configured: %s", len(ADMIN_IDS))
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS is empty. /admin and /broadcast will not work.")


async def on_shutdown(bot: Bot) -> None:
    logger.info("Shutting down bot...")
    await bot.session.close()


async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Force join for messages and callbacks.
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
        logger.info("Bot stopped by user.")
