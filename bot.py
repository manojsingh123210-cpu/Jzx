"""
Premium Multi-Tool Bot — WITH STICKER MAKER
Features: Force-join · Emoji ID · Collection · TTS · Search · Feedback
          Sticker Maker (with bot watermark) · Premium Ad · Promo Channels
          Admin Panel · Broadcast · Run Ad · Dashboard
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import io
import logging
import math
import os
import random
import re
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite
from PIL import Image, ImageDraw, ImageFont
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
    BufferedInputFile,
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
from gtts import gTTS

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

_ext_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
_ext_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _ext_url.startswith("https://"):
    DASHBOARD_URL = f"{_ext_url}/dashboard"
elif _ext_host:
    DASHBOARD_URL = f"https://{_ext_host}/dashboard"
else:
    DASHBOARD_URL = ""

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
BTN_TTS        = EMOJI_IDS[10]
BTN_SEARCH     = EMOJI_IDS[11]
BTN_FEEDBACK   = EMOJI_IDS[12]
BTN_PROMO      = EMOJI_IDS[13]
BTN_STICKER    = EMOJI_IDS[14]

PAGE_SIZE: int = 5
TOTAL_PAGES: int = math.ceil(len(EMOJI_IDS) / PAGE_SIZE)
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
START_TIME: float = time.time()

VALID_EMOJI_CACHE: dict[str, Optional[bool]] = {}
_membership_cache: dict[str, tuple[float, bool, Any]] = {}
MEMBERSHIP_CACHE_TTL: int = 60
_health_runner: Any = None

_active_ad: Optional[asyncio.Task] = None
AD_SEND_COUNT: int = 5
AD_GAP_SECONDS: int = 600

TTS_LANGUAGES = {
    "en": "English 🇬🇧", "hi": "हिन्दी 🇮🇳", "es": "Español 🇪🇸",
    "fr": "Français 🇫🇷", "de": "Deutsch 🇩🇪", "it": "Italiano 🇮🇹",
    "pt": "Português 🇵🇹", "ja": "日本語 🇯🇵",
}

FONT_PATH_CACHE = "/tmp/bot_font_bold.ttf"
FONT_URLS = [
    "https://cdn.jsdelivr.net/gh/googlefonts/noto-fonts@main/hinted/ttf/NotoSans/NotoSans-Bold.ttf",
    "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf",
]

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
        logger.warning("sendMessage failed: %s", exc)
        try:
            return await message.answer(strip_custom_emoji_tags(text), **kwargs)
        except TelegramBadRequest as exc2:
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
    try:
        return InlineKeyboardButton(**kwargs)
    except (TypeError, ValueError) as exc:
        logger.warning("Button style unsupported: %s", exc)
        safe = {k: v for k, v in kwargs.items()
                if k not in ("style", "icon_custom_emoji_id")}
        try:
            return InlineKeyboardButton(**safe)
        except Exception:
            minimal = {k: v for k, v in safe.items()
                       if k in ("text", "callback_data", "url")}
            return InlineKeyboardButton(**minimal)


# ============================================================
# PREMIUM AD CONVERTER
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
    use_small_caps = (style % 2 == 0)

    def transform(s: str) -> str:
        return to_small_caps(s) if use_small_caps else s

    parts: list[str] = []
    last_end = 0
    for match in EMOJI_PATTERN.finditer(text):
        if last_end < match.start():
            parts.append(html.escape(transform(text[last_end:match.start()])))
        idx = random.randrange(len(EMOJI_IDS))
        parts.append(custom_emoji(EMOJI_IDS[idx], EMOJI_FALLBACKS[idx]))
        last_end = match.end()
    if last_end < len(text):
        parts.append(html.escape(transform(text[last_end:])))

    content = "".join(parts)
    return content if use_small_caps else f"<b>{content}</b>"


# ============================================================
# TTS HELPERS
# ============================================================

def _tts_generate_sync(text: str, lang: str, slow: bool) -> bytes:
    tts = gTTS(text=text, lang=lang, slow=slow)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    return buf.getvalue()


async def generate_tts_audio(text: str, lang: str = "en", slow: bool = False) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _tts_generate_sync, text, lang, slow)


# ============================================================
# STICKER MAKER HELPERS
# ============================================================

async def ensure_font() -> Optional[str]:
    """Download Noto Sans Bold once. Fallback to system DejaVu if fails."""
    if os.path.exists(FONT_PATH_CACHE) and os.path.getsize(FONT_PATH_CACHE) > 5000:
        return FONT_PATH_CACHE
    loop = asyncio.get_event_loop()

    def _dl(url: str) -> bool:
        try:
            urllib.request.urlretrieve(url, FONT_PATH_CACHE)
            return (os.path.exists(FONT_PATH_CACHE)
                    and os.path.getsize(FONT_PATH_CACHE) > 5000)
        except Exception:
            return False

    for url in FONT_URLS:
        if await loop.run_in_executor(None, _dl, url):
            logger.info("Font downloaded: %s", FONT_PATH_CACHE)
            return FONT_PATH_CACHE
    logger.warning("Font download failed; will use system fallback")
    return None


def _load_font(size: int, font_path: Optional[str]) -> Any:
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    for syspath in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(syspath, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _generate_sticker_sync(
    image_bytes: Optional[bytes],
    text: Optional[str],
    watermark: str,
    font_path: Optional[str],
) -> bytes:
    SIZE = 512
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    if image_bytes:
        try:
            src = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
            src.thumbnail((SIZE, SIZE), Image.LANCZOS)
            x = (SIZE - src.width) // 2
            y = (SIZE - src.height) // 2
            canvas.paste(src, (x, y), src)
        except Exception as exc:
            logger.warning("Image load failed: %s", exc)

    if text:
        canvas = Image.new("RGBA", (SIZE, SIZE), (8, 8, 12, 255))
        draw = ImageDraw.Draw(canvas)

        base_size = 56 if len(text) < 30 else (44 if len(text) < 80 else 32)
        font = _load_font(base_size, font_path)
        max_w = SIZE - 60

        def measure(t: str, f: Any) -> int:
            try:
                bbox = draw.textbbox((0, 0), t, font=f)
                return bbox[2] - bbox[0]
            except Exception:
                return int(len(t) * base_size * 0.55)

        def wrap(t: str, f: Any) -> list[str]:
            out: list[str] = []
            for raw in t.split("\n"):
                cur = ""
                for w in raw.split():
                    test = (cur + " " + w).strip() if cur else w
                    if measure(test, f) <= max_w:
                        cur = test
                    else:
                        if cur:
                            out.append(cur)
                        cur = w
                if cur:
                    out.append(cur)
            return out or [""]

        lines = wrap(text, font)
        line_h = base_size + 14
        total_h = line_h * len(lines)
        safety = 0
        while total_h > SIZE - 100 and base_size > 22 and safety < 12:
            base_size -= 4
            font = _load_font(base_size, font_path)
            lines = wrap(text, font)
            line_h = base_size + 14
            total_h = line_h * len(lines)
            safety += 1

        start_y = (SIZE - total_h) // 2 - 10
        for i, line in enumerate(lines):
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = measure(line, font)
            draw.text(
                ((SIZE - tw) // 2, start_y + i * line_h),
                line, font=font, fill=(255, 255, 255, 255),
            )
    else:
        draw = ImageDraw.Draw(canvas)

    # Watermark: "via @BotUsername" bottom-right
    wm_font = _load_font(18, font_path)
    wm_text = f"via @{watermark}"
    try:
        bbox = draw.textbbox((0, 0), wm_text, font=wm_font)
        wm_w = bbox[2] - bbox[0]
        wm_h = bbox[3] - bbox[1]
    except Exception:
        wm_w = len(wm_text) * 11
        wm_h = 18

    pad = 6
    box_x1 = SIZE - wm_w - pad * 2 - 10
    box_y1 = SIZE - wm_h - pad * 2 - 10
    draw.rectangle(
        [box_x1, box_y1, SIZE - 6, SIZE - 6],
        fill=(0, 0, 0, 160),
    )
    draw.text(
        (SIZE - wm_w - pad - 12, SIZE - wm_h - pad - 12),
        wm_text, font=wm_font, fill=(225, 225, 240, 250),
    )

    buf = io.BytesIO()
    canvas.save(buf, format="WEBP", quality=95, method=6)
    return buf.getvalue()


async def generate_sticker(
    image_bytes: Optional[bytes],
    text: Optional[str],
    watermark: str,
) -> bytes:
    font_path = await ensure_font()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _generate_sticker_sync, image_bytes, text, watermark, font_path
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
                last_seen TEXT NOT NULL,
                tts_lang TEXT DEFAULT 'en'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_channels (
                chat_id TEXT PRIMARY KEY,
                title TEXT,
                invite_link TEXT NOT NULL,
                added_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0
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

        async def _stat(k: str) -> int:
            cur = await db.execute("SELECT value FROM stats WHERE key=?", (k,))
            row = await cur.fetchone()
            return row[0] if row else 0

        queries = await _stat("emoji_queries")
        visits = await _stat("visits")
        tts_queries = await _stat("tts_queries")
        stickers_made = await _stat("stickers_made")

    return {"total_users": total, "verified_users": verified,
            "emoji_queries": queries, "visits": visits,
            "tts_queries": tts_queries, "stickers_made": stickers_made}


async def all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        return [r[0] for r in await cur.fetchall()]


# ---- Promo DB ----

async def get_active_promos() -> list[dict[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT chat_id, title, invite_link FROM promo_channels WHERE active=1"
        )
        rows = await cur.fetchall()
    return [{"chat_id": r[0], "title": r[1] or "Sponsored Channel",
             "invite_link": r[2]} for r in rows]


async def add_promo(chat_id: str, title: str, invite_link: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO promo_channels (chat_id, title, invite_link, added_at, active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(chat_id) DO UPDATE SET
                title=excluded.title, invite_link=excluded.invite_link, active=1
        """, (chat_id, title, invite_link, now))
        await db.commit()


async def delete_promo(chat_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM promo_channels WHERE chat_id=?", (chat_id,))
        await db.commit()


async def list_promos() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT chat_id, title, invite_link, added_at, active "
            "FROM promo_channels ORDER BY added_at DESC"
        )
        rows = await cur.fetchall()
    return [{"chat_id": r[0], "title": r[1] or "Untitled",
             "invite_link": r[2], "added_at": r[3], "active": r[4]}
            for r in rows]


# ---- Feedback DB ----

async def add_feedback(user_id: int, username: str, message: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO feedbacks (user_id, username, message, created_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, message, now))
        await db.commit()
        return cur.lastrowid or 0


async def list_feedbacks(limit: int = 20) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, user_id, username, message, created_at, is_read
            FROM feedbacks ORDER BY id DESC LIMIT ?
        """, (limit,))
        rows = await cur.fetchall()
    return [{"id": r[0], "user_id": r[1], "username": r[2],
             "message": r[3], "created_at": r[4], "is_read": r[5]} for r in rows]


async def delete_feedback(fid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM feedbacks WHERE id=?", (fid,))
        await db.commit()


async def unread_feedback_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM feedbacks WHERE is_read=0")
        return (await cur.fetchone())[0]


# ============================================================
# MEMBERSHIP
# ============================================================

def _member_ok(member: Any) -> bool:
    if isinstance(member, (ChatMemberOwner, ChatMemberAdministrator, ChatMemberMember)):
        return True
    if isinstance(member, ChatMemberRestricted):
        return bool(getattr(member, "is_member", False))
    return False


async def is_member(bot: Bot, user_id: int, force: bool = False) -> tuple[bool, str]:
    now = time.monotonic()
    key = f"{user_id}_main"
    if not force:
        cached = _membership_cache.get(key)
        if cached and now - cached[0] < MEMBERSHIP_CACHE_TTL:
            return cached[1], cached[2]
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        ok = _member_ok(member)
        result = (ok, "member" if ok else "not_member")
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
    _membership_cache[key] = (now, result[0], result[1])
    return result


async def is_member_all(bot: Bot, user_id: int, force: bool = False) -> tuple[bool, list[dict[str, str]]]:
    now = time.monotonic()
    key = f"{user_id}_all"
    if not force:
        cached = _membership_cache.get(key)
        if cached and now - cached[0] < MEMBERSHIP_CACHE_TTL:
            return cached[1], cached[2]

    missing: list[dict[str, str]] = []

    ok_main, _ = await is_member(bot, user_id, force=force)
    if not ok_main:
        missing.append({"title": "Main Channel", "link": CHANNEL_LINK,
                        "chat_id": CHANNEL_ID, "type": "main"})

    promos = await get_active_promos()
    for p in promos:
        try:
            member = await bot.get_chat_member(chat_id=p["chat_id"], user_id=user_id)
            if not _member_ok(member):
                missing.append({"title": p["title"], "link": p["invite_link"],
                                "chat_id": p["chat_id"], "type": "promo"})
        except TelegramBadRequest:
            missing.append({"title": p["title"], "link": p["invite_link"],
                            "chat_id": p["chat_id"], "type": "promo"})
        except TelegramAPIError:
            pass

    result = (len(missing) == 0, missing)
    _membership_cache[key] = (now, result[0], result[1])
    return result


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


class TTSStates(StatesGroup):
    waiting_language = State()
    waiting_text = State()


class SearchStates(StatesGroup):
    waiting = State()


class FeedbackStates(StatesGroup):
    waiting = State()


class PromoStates(StatesGroup):
    waiting_chat_id = State()
    waiting_link = State()


class StickerStates(StatesGroup):
    waiting = State()


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
        if isinstance(event, CallbackQuery) and event.data in ("verify_join", "help"):
            return await handler(event, data)

        ok, missing = await is_member_all(bot, user.id)
        if ok:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("Join required channels first.", show_alert=True)
            return None

        if isinstance(event, Message):
            await safe_answer(
                event, force_join_text(missing),
                reply_markup=force_join_keyboard(missing),
                link_preview_options=NO_PREVIEW,
            )
            return None
        return None


# ============================================================
# KEYBOARDS
# ============================================================

def force_join_keyboard(missing: list[dict[str, str]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ch in missing:
        style = "success" if ch["type"] == "main" else "primary"
        icon = BTN_JOIN if ch["type"] == "main" else BTN_PROMO
        label = f"JOIN {ch['title'].upper()}"
        kb.row(mk_button(text=label, url=ch["link"],
                         icon_custom_emoji_id=icon, style=style))
    kb.row(mk_button(text="VERIFY ALL", callback_data="verify_join",
                     icon_custom_emoji_id=BTN_VERIFY, style="primary"))
    kb.row(mk_button(text="HELP", callback_data="help",
                     icon_custom_emoji_id=BTN_HELP, style="danger"))
    return kb.as_markup()


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(mk_button(text="GET EMOJI ID", callback_data="get_id_help",
                     icon_custom_emoji_id=BTN_GET_ID, style="primary"))
    kb.row(mk_button(text="PREMIUM COLLECTION", callback_data="collection:0",
                     icon_custom_emoji_id=BTN_COLLECTION, style="success"))
    kb.row(mk_button(text="STICKER MAKER", callback_data="sticker_start",
                     icon_custom_emoji_id=BTN_STICKER, style="success"))
    kb.row(
        mk_button(text="TEXT TO SPEECH", callback_data="tts_start",
                  icon_custom_emoji_id=BTN_TTS, style="primary"),
        mk_button(text="SEARCH ID", callback_data="search_start",
                  icon_custom_emoji_id=BTN_SEARCH, style="success"),
    )
    kb.row(mk_button(text="MAKE PREMIUM AD", callback_data="make_premium_ad",
                     icon_custom_emoji_id=BTN_CHANNEL, style="success"))
    kb.row(
        mk_button(text="HOW TO USE", callback_data="howto",
                  icon_custom_emoji_id=BTN_HOWTO, style="primary"),
        mk_button(text="FEEDBACK", callback_data="feedback_start",
                  icon_custom_emoji_id=BTN_FEEDBACK, style="primary"),
    )
    kb.row(
        mk_button(text="HELP", callback_data="help",
                  icon_custom_emoji_id=BTN_HELP, style="danger"),
        mk_button(text="CHANNEL", url=CHANNEL_LINK,
                  icon_custom_emoji_id=BTN_CHANNEL, style="success"),
    )
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
    kb.row(mk_button(text="BROADCAST", callback_data="admin_broadcast",
                     icon_custom_emoji_id=BTN_CHANNEL, style="primary"))
    kb.row(mk_button(text="RUN AD CAMPAIGN", callback_data="admin_ad",
                     icon_custom_emoji_id=BTN_CHANNEL, style="success"))
    kb.row(mk_button(text="MANAGE PROMOS", callback_data="promo_manage",
                     icon_custom_emoji_id=BTN_PROMO, style="primary"))
    kb.row(mk_button(text="VIEW FEEDBACK", callback_data="admin_feedbacks",
                     icon_custom_emoji_id=BTN_FEEDBACK, style="primary"))
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


def tts_language_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, name in TTS_LANGUAGES.items():
        kb.row(mk_button(text=name, callback_data=f"tts_lang:{code}",
                         icon_custom_emoji_id=BTN_TTS, style="primary"))
    kb.row(mk_button(text="BACK", callback_data="home",
                     icon_custom_emoji_id=BTN_HOME, style="success"))
    return kb.as_markup()


def promo_manage_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(mk_button(text="ADD PROMO CHANNEL", callback_data="promo_add",
                     icon_custom_emoji_id=BTN_PROMO, style="success"))
    kb.row(mk_button(text="LIST PROMOS", callback_data="promo_list",
                     icon_custom_emoji_id=BTN_COLLECTION, style="primary"))
    kb.row(mk_button(text="BACK TO ADMIN", callback_data="open_admin_panel",
                     icon_custom_emoji_id=BTN_HOME, style="primary"))
    return kb.as_markup()


# ============================================================
# TEXT BUILDERS
# ============================================================

def force_join_text(missing: list[dict[str, str]]) -> str:
    lines = [header('ᴘʀᴇᴍɪᴜᴍ ʙᴏᴛ'), "",
             f"{e(1)} <b>ᴀᴄᴄᴇꜱꜱ ʟᴏᴄᴋᴇᴅ</b>", ""]
    for ch in missing:
        icon = e(6) if ch["type"] == "main" else e(13)
        label = "ᴍᴀɪɴ ᴄʜᴀɴɴᴇʟ" if ch["type"] == "main" else "ꜱᴘᴏɴꜱᴏʀᴇᴅ"
        lines.append(f"▸ {icon} {label} · {html.escape(ch['title'])}")
    lines += ["", DIV_LIGHT, "",
              f"{e(11)} ᴛᴀᴘ ᴇᴀᴄʜ ᴊᴏɪɴ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ",
              f"{e(16)} ᴛʜᴇɴ ᴛᴀᴘ ᴠᴇʀɪꜰʏ ᴀʟʟ", "",
              footer('ᴊᴏɪɴ ᴀʟʟ ᴛᴏ ᴜɴʟᴏᴄᴋ')]
    return "\n".join(lines)


def force_join_reminder_text() -> str:
    return (
        f"{header('ᴀᴄᴄᴇꜱꜱ ʟᴏᴄᴋᴇᴅ')}\n\n"
        f"{e(2)} ᴊᴏɪɴ ʀᴇǫᴜɪʀᴇᴅ ᴄʜᴀɴɴᴇʟꜱ ꜰɪʀꜱᴛ\n\n"
        f"{e(7)} ᴛᴀᴘ ᴠᴇʀɪꜰʏ ᴀꜰᴛᴇʀ ᴊᴏɪɴɪɴɢ"
    )


def main_menu_text(is_admin: bool = False) -> str:
    admin_note = (
        f"\n\n{footer('ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ ᴀᴠᴀɪʟᴀʙʟᴇ')}"
        if is_admin else ""
    )
    return (
        f"{header('ᴘʀᴇᴍɪᴜᴍ ᴍᴜʟᴛɪ ᴛᴏᴏʟ ʙᴏᴛ')}\n\n"
        f"{e(0)} ᴘᴏᴡᴇʀꜰᴜʟ ᴛᴏᴏʟꜱ ɪɴ ᴏɴᴇ ʙᴏᴛ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(5)} ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ ɪᴅꜱ\n"
        f"{e(14)} ꜱᴛɪᴄᴋᴇʀ ᴍᴀᴋᴇʀ\n"
        f"{e(10)} ᴛᴇxᴛ ᴛᴏ ꜱᴘᴇᴇᴄʜ\n"
        f"{e(11)} ꜱᴇᴀʀᴄʜ ᴇᴍᴏᴊɪ ʙʏ ɪᴅ\n"
        f"{e(12)} ᴀᴇꜱᴛʜᴇᴛɪᴄ ᴀᴅ ᴍᴀᴋᴇʀ\n"
        f"{e(15)} ꜰᴇᴇᴅʙᴀᴄᴋ ꜱʏꜱᴛᴇᴍ"
        f"{admin_note}"
    )


def no_emoji_text() -> str:
    return (
        f"{header('ɴᴏ ᴇᴍᴏᴊɪ ꜰᴏᴜɴᴅ')}\n\n"
        f"{e(3)} ɴᴏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ᴅᴇᴛᴇᴄᴛᴇᴅ\n\n"
        f"{e(9)} ᴜꜱᴇ ᴛʜᴇ ᴍᴇɴᴜ ᴏʀ ꜱᴇɴᴅ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ\n\n"
        f"{footer('ᴏɴʟʏ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪꜱ ʜᴀᴠᴇ ɪᴅꜱ')}"
    )


def get_id_help_text() -> str:
    return (
        f"{header('ɢᴇᴛ ᴇᴍᴏᴊɪ ɪᴅ')}\n\n"
        f"{e(4)} 3 ꜱᴛᴇᴘꜱ:\n\n"
        f"▸ {e(9)} ꜱᴇɴᴅ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ\n"
        f"▸ {e(14)} ʙᴏᴛ ᴅᴇᴛᴇᴄᴛꜱ ɪᴛ\n"
        f"▸ {e(19)} ʀᴇᴄᴇɪᴠᴇ ᴛʜᴇ ɪᴅ\n\n"
        f"{footer('ᴛᴀᴘ ᴛʜᴇ ɪᴅ ᴛᴏ ᴄᴏᴘʏ')}"
    )


def how_to_text() -> str:
    return (
        f"{header('ʜᴏᴡ ᴛᴏ ᴜꜱᴇ')}\n\n"
        f"{e(7)} <b>1 · ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟꜱ</b>\n"
        "   ᴊᴏɪɴ ᴀʟʟ ʀᴇǫᴜɪʀᴇᴅ ᴀɴᴅ ᴠᴇʀɪꜰʏ\n\n"
        f"{e(14)} <b>2 · ꜱᴛɪᴄᴋᴇʀ ᴍᴀᴋᴇʀ</b>\n"
        "   ꜱᴇɴᴅ ᴘʜᴏᴛᴏ ᴏʀ ᴛᴇxᴛ → ɢᴇᴛ ꜱᴛɪᴄᴋᴇʀ\n\n"
        f"{e(12)} <b>3 · ɢᴇᴛ ᴇᴍᴏᴊɪ ɪᴅ</b>\n"
        "   ꜱᴇɴᴅ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ → ʙᴏᴛ ʀᴇᴘʟɪᴇꜱ ᴡɪᴛʜ ɪᴅ\n\n"
        f"{e(17)} <b>4 · ᴛᴇxᴛ ᴛᴏ ꜱᴘᴇᴇᴄʜ</b>\n"
        "   ᴄʜᴏᴏꜱᴇ ʟᴀɴɢᴜᴀɢᴇ → ꜱᴇɴᴅ ᴛᴇxᴛ → ɢᴇᴛ ᴠᴏɪᴄᴇ\n\n"
        f"{footer('ᴛᴀᴘ ᴍᴇɴᴜ ʙᴜᴛᴛᴏɴꜱ')}"
    )


def help_text() -> str:
    return (
        f"{header('ʜᴇʟᴘ ᴄᴇɴᴛᴇʀ')}\n\n"
        f"{e(8)} <b>· ɢᴇᴛ ᴇᴍᴏᴊɪ ɪᴅ</b>\n"
        "   ꜱᴇɴᴅ ᴀɴʏ ᴘʀᴇᴍɪᴜᴍ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ\n\n"
        f"{e(14)} <b>· ꜱᴛɪᴄᴋᴇʀ ᴍᴀᴋᴇʀ</b>\n"
        "   ꜱᴇɴᴅ ᴘʜᴏᴛᴏ ᴏʀ ᴛᴇxᴛ → ɢᴇᴛ ꜱᴛɪᴄᴋᴇʀ\n\n"
        "<b>· ᴛᴇxᴛ ᴛᴏ ꜱᴘᴇᴇᴄʜ</b>\n"
        "   ᴄʜᴏᴏꜱᴇ ʟᴀɴɢᴜᴀɢᴇ → ꜱᴇɴᴅ ᴛᴇxᴛ\n\n"
        "<b>· ꜱᴇᴀʀᴄʜ ʙʏ ɪᴅ</b>\n"
        "   ᴘᴀꜱᴛᴇ ᴛʜᴇ ɪᴅ → ɢᴇᴛ ᴇᴍᴏᴊɪ\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(13)} <b>ᴀᴅᴍɪɴ ᴄᴏɴᴛᴀᴄᴛ</b>\n"
        f"   @cytunn\n"
        f"   @R0syug\n\n"
        f"{e(18)} <b>ᴄʜᴀɴɴᴇʟ</b>\n"
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
             f"{e(0)} <b>ᴅᴇᴛᴇᴄᴛᴇᴅ {len(ids)}</b>", ""]
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
        fb = EMOJI_FALLBACKS[(number - 1) % len(EMOJI_FALLBACKS)]
        lines.append(f"{number:02d} · {custom_emoji(emoji_id, fb)} "
                     f"<code>{html.escape(emoji_id)}</code>")
    lines.append("")
    lines.append(footer("ᴛᴀᴘ ᴀɴ ɪᴅ ᴛᴏ ᴄᴏᴘʏ"))
    return "\n".join(lines)


def premium_ad_intro_text() -> str:
    return (
        f"{header('ᴍᴀᴋᴇ ᴘʀᴇᴍɪᴜᴍ ᴀᴅ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ʏᴏᴜʀ ᴀᴅ ᴛᴇxᴛ\n"
        "   (ɴᴏʀᴍᴀʟ ᴇᴍᴏᴊɪꜱ ꜰɪɴᴇ)\n\n"
        f"{DIV_LIGHT}\n\n"
        "<b>ᴇxᴀᴍᴘʟᴇ:</b>\n"
        "<i>Sell you GC here 👽 buy safe 🎀 sell safe 🌷</i>\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{e(6)} <b>ʙᴏᴛ ᴡɪʟʟ:</b>\n"
        "▸ ɴᴏʀᴍᴀʟ ᴇᴍᴏᴊɪꜱ → ᴘʀᴇᴍɪᴜᴍ\n"
        "▸ ᴛᴇxᴛ → ᴀᴇꜱᴛʜᴇᴛɪᴄ ꜰᴏɴᴛ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}"
    )


def premium_ad_preview_wrap(clean_html: str, style: int) -> str:
    style_name = "ꜱᴍᴀʟʟ ᴄᴀᴘꜱ" if style % 2 == 0 else "ʙᴏʟᴅ"
    return (
        f"{header('ᴘʀᴇᴍɪᴜᴍ ᴀᴅ ᴘʀᴇᴠɪᴇᴡ')}\n\n"
        f"{clean_html}\n\n"
        f"{DIV_LIGHT}\n"
        f"ꜱᴛʏʟᴇ · {style_name}\n\n"
        f"{footer('ꜰᴏʀᴡᴀʀᴅ · ᴄʜᴀɴɢᴇ · ᴘᴏꜱᴛ')}"
    )


def tts_intro_text() -> str:
    return (
        f"{header('ᴛᴇxᴛ ᴛᴏ ꜱᴘᴇᴇᴄʜ')}\n\n"
        f"{e(10)} ᴄʜᴏᴏꜱᴇ ʟᴀɴɢᴜᴀɢᴇ ʙᴇʟᴏᴡ\n\n"
        f"{footer('ᴀᴜᴅɪᴏ ᴡɪʟʟ ʙᴇ ꜱᴇɴᴛ ᴀꜱ ᴠᴏɪᴄᴇ')}"
    )


def tts_waiting_text(lang: str) -> str:
    lang_name = TTS_LANGUAGES.get(lang, lang)
    return (
        f"{header('ᴛᴛꜱ ʀᴇᴀᴅʏ')}\n\n"
        f"{e(10)} ʟᴀɴɢᴜᴀɢᴇ · {lang_name}\n\n"
        f"{e(11)} ꜱᴇɴᴅ ᴛʜᴇ ᴛᴇxᴛ ɴᴏᴡ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}"
    )


def search_intro_text() -> str:
    return (
        f"{header('ꜱᴇᴀʀᴄʜ ʙʏ ɪᴅ')}\n\n"
        f"{e(11)} ꜱᴇɴᴅ ᴛʜᴇ ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ ɪᴅ\n\n"
        f"{DIV_LIGHT}\n\n"
        "<b>ᴇxᴀᴍᴘʟᴇ:</b>\n"
        "<code>5357592447557848986</code>\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}"
    )


def feedback_intro_text() -> str:
    return (
        f"{header('ꜰᴇᴇᴅʙᴀᴄᴋ')}\n\n"
        f"{e(12)} ꜱᴇɴᴅ ʏᴏᴜʀ ꜰᴇᴇᴅʙᴀᴄᴋ, ꜱᴜɢɢᴇꜱᴛɪᴏɴ, ᴏʀ ʙᴜɢ ʀᴇᴘᴏʀᴛ\n\n"
        f"{e(17)} ᴡɪʟʟ ʙᴇ ꜱᴇɴᴛ ᴛᴏ ᴀᴅᴍɪɴ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}"
    )


def sticker_intro_text() -> str:
    return (
        f"{header('ꜱᴛɪᴄᴋᴇʀ ᴍᴀᴋᴇʀ')}\n\n"
        f"{e(14)} ꜱᴇɴᴅ ᴀɴ ɪᴍᴀɢᴇ ᴏʀ ᴛᴇxᴛ\n\n"
        f"{DIV_LIGHT}\n\n"
        "<b>ᴏᴘᴛɪᴏɴꜱ:</b>\n"
        "▸ ᴘʜᴏᴛᴏ → ꜱᴛɪᴄᴋᴇʀ\n"
        "▸ ᴛᴇxᴛ → ᴛᴇxᴛ ꜱᴛɪᴄᴋᴇʀ\n\n"
        f"{e(11)} ᴡᴀᴛᴇʀᴍᴀʀᴋ ᴀᴅᴅᴇᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}"
    )


# ============================================================
# EMOJI VALIDATION
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
# USER HANDLERS
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await upsert_user(message.from_user)
    await increment_stat("visits")
    ok, missing = await is_member_all(bot, message.from_user.id, force=True)
    is_admin = message.from_user.id in ADMIN_IDS
    if ok:
        await mark_verified(message.from_user.id)
        await safe_answer(message, main_menu_text(is_admin),
                          reply_markup=main_menu_keyboard(is_admin),
                          link_preview_options=NO_PREVIEW)
    else:
        await safe_answer(message, force_join_text(missing),
                          reply_markup=force_join_keyboard(missing),
                          link_preview_options=NO_PREVIEW)


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    uid = message.from_user.id
    is_admin = uid in ADMIN_IDS
    admins_str = ", ".join(str(x) for x in sorted(ADMIN_IDS)) or "(empty)"
    await message.answer(
        f"<b>Debug</b>\n\n"
        f"Your ID · <code>{uid}</code>\n"
        f"Is admin · <code>{'YES' if is_admin else 'NO'}</code>\n"
        f"Admins · <code>{admins_str}</code>"
    )


@router.callback_query(F.data == "verify_join")
async def cb_verify_join(callback: CallbackQuery, bot: Bot) -> None:
    ok, missing = await is_member_all(bot, callback.from_user.id, force=True)
    is_admin = callback.from_user.id in ADMIN_IDS
    if ok:
        await mark_verified(callback.from_user.id)
        await safe_edit(callback, main_menu_text(is_admin),
                        reply_markup=main_menu_keyboard(is_admin),
                        link_preview_options=NO_PREVIEW)
        await callback.answer("Verified.")
        return
    names = ", ".join(ch["title"] for ch in missing)
    await callback.answer(f"Still missing: {names}", show_alert=True)


@router.callback_query(F.data == "home")
async def cb_home(callback: CallbackQuery, bot: Bot) -> None:
    ok, _ = await is_member(bot, callback.from_user.id)
    if not ok:
        await callback.answer("Join channel first.", show_alert=True)
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
                    reply_markup=main_menu_keyboard(is_admin) if ok else force_join_keyboard([]),
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


# ============================================================
# STICKER MAKER HANDLERS
# ============================================================

@router.callback_query(F.data == "sticker_start")
async def cb_sticker_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(StickerStates.waiting)
    await safe_edit(callback, sticker_intro_text(),
                    reply_markup=None,
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.message(Command("sticker"))
async def cmd_sticker(message: Message, state: FSMContext) -> None:
    await state.set_state(StickerStates.waiting)
    await safe_answer(message, sticker_intro_text(), reply_markup=None,
                      link_preview_options=NO_PREVIEW)


@router.message(StateFilter(StickerStates.waiting))
async def do_sticker(message: Message, state: FSMContext, bot: Bot) -> None:
    user = message.from_user
    bot_me = await bot.get_me()
    watermark = bot_me.username or "PremiumBot"

    image_bytes: Optional[bytes] = None
    text: Optional[str] = None

    if message.photo:
        try:
            file_info = await bot.get_file(message.photo[-1].file_id)
            buf = io.BytesIO()
            await bot.download_file(file_info.file_path, buf)
            image_bytes = buf.getvalue()
        except TelegramAPIError as exc:
            logger.warning("Photo download failed: %s", exc)
            await safe_answer(message, "Could not read photo. Try again.")
            return
    elif message.document:
        try:
            file_info = await bot.get_file(message.document.file_id)
            buf = io.BytesIO()
            await bot.download_file(file_info.file_path, buf)
            image_bytes = buf.getvalue()
        except TelegramAPIError as exc:
            logger.warning("Document download failed: %s", exc)
            await safe_answer(message, "Could not read file. Try again.")
            return
    elif message.text and message.text.strip():
        text = message.text.strip()
        if len(text) > 300:
            await safe_answer(message, "Text too long (max 300 chars).")
            return
    else:
        await safe_answer(message, "Send a photo or text.")
        return

    wait_msg = await safe_answer(
        message, f"{e(14)} ɢᴇɴᴇʀᴀᴛɪɴɢ ꜱᴛɪᴄᴋᴇʀ...",
        link_preview_options=NO_PREVIEW,
    )

    try:
        webp_bytes = await generate_sticker(image_bytes, text, watermark)
    except Exception as exc:
        logger.exception("Sticker gen failed: %s", exc)
        if wait_msg:
            with contextlib.suppress(TelegramAPIError):
                await wait_msg.edit_text("❌ Failed. Try again.")
        return

    sent = False
    try:
        upload = BufferedInputFile(webp_bytes, filename="sticker.webp")
        uploaded = await bot.upload_sticker_file(
            user_id=user.id, sticker=upload, sticker_format="static"
        )
        await message.answer_sticker(uploaded.file_id)
        sent = True
    except TelegramAPIError as exc:
        logger.warning("Sticker upload failed: %s", exc)

    if not sent:
        try:
            await message.answer_document(
                BufferedInputFile(webp_bytes, filename="sticker.webp"),
                caption=f"{e(14)} ꜱᴀᴠᴇ ᴀꜱ ꜱᴛɪᴄᴋᴇʀ",
            )
        except TelegramAPIError:
            if wait_msg:
                with contextlib.suppress(TelegramAPIError):
                    await wait_msg.edit_text("❌ Could not send.")
            await state.clear()
            return

    await increment_stat("stickers_made")
    await state.clear()
    if wait_msg:
        with contextlib.suppress(TelegramAPIError):
            await wait_msg.delete()


@router.message(Command("cancel"), StateFilter(StickerStates.waiting))
async def cmd_cancel_sticker(message: Message, state: FSMContext) -> None:
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await safe_answer(message, main_menu_text(is_admin),
                      reply_markup=main_menu_keyboard(is_admin),
                      link_preview_options=NO_PREVIEW)


# ============================================================
# TTS HANDLERS
# ============================================================

@router.callback_query(F.data == "tts_start")
async def cb_tts_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TTSStates.waiting_language)
    await safe_edit(callback, tts_intro_text(),
                    reply_markup=tts_language_keyboard(),
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.message(Command("tts"))
async def cmd_tts(message: Message, state: FSMContext) -> None:
    await state.set_state(TTSStates.waiting_language)
    await safe_answer(message, tts_intro_text(),
                      reply_markup=tts_language_keyboard(),
                      link_preview_options=NO_PREVIEW)


@router.callback_query(F.data.startswith("tts_lang:"))
async def cb_tts_lang(callback: CallbackQuery, state: FSMContext) -> None:
    lang = callback.data.split(":", 1)[1]
    if lang not in TTS_LANGUAGES:
        await callback.answer("Invalid language.", show_alert=True)
        return
    await state.update_data(tts_lang=lang)
    await state.set_state(TTSStates.waiting_text)
    await safe_edit(callback, tts_waiting_text(lang),
                    reply_markup=None,
                    link_preview_options=NO_PREVIEW)
    await callback.answer(f"Language: {TTS_LANGUAGES[lang]}")


@router.message(StateFilter(TTSStates.waiting_text))
async def do_tts(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await safe_answer(message, "Send text message only.")
        return
    if len(text) > 2000:
        await safe_answer(message, "Text too long (max 2000).")
        return
    data = await state.get_data()
    lang = data.get("tts_lang", "en")

    wait_msg = await safe_answer(
        message, f"{e(10)} ɢᴇɴᴇʀᴀᴛɪɴɢ ᴀᴜᴅɪᴏ...",
        link_preview_options=NO_PREVIEW,
    )

    try:
        audio_bytes = await generate_tts_audio(text, lang=lang, slow=False)
    except Exception as exc:
        logger.exception("TTS failed: %s", exc)
        if wait_msg:
            with contextlib.suppress(TelegramAPIError):
                await wait_msg.edit_text(f"❌ TTS failed.")
        return

    sent = False
    try:
        await message.answer_voice(
            BufferedInputFile(audio_bytes, filename="tts.mp3"),
            caption=f"{e(10)} ᴠᴏɪᴄᴇ · {TTS_LANGUAGES.get(lang, lang)}",
        )
        sent = True
    except TelegramAPIError as exc:
        logger.warning("Voice send failed: %s", exc)

    if not sent:
        try:
            await message.answer_audio(
                BufferedInputFile(audio_bytes, filename="tts.mp3"),
                caption=f"{e(10)} ᴀᴜᴅɪᴏ · {TTS_LANGUAGES.get(lang, lang)}",
            )
        except TelegramAPIError:
            if wait_msg:
                with contextlib.suppress(TelegramAPIError):
                    await wait_msg.edit_text("❌ Could not send audio.")
            await state.clear()
            return

    await increment_stat("tts_queries")
    await state.clear()
    if wait_msg:
        with contextlib.suppress(TelegramAPIError):
            await wait_msg.delete()


@router.message(Command("cancel"),
                StateFilter(TTSStates.waiting_language, TTSStates.waiting_text))
async def cmd_cancel_tts(message: Message, state: FSMContext) -> None:
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await safe_answer(message, main_menu_text(is_admin),
                      reply_markup=main_menu_keyboard(is_admin),
                      link_preview_options=NO_PREVIEW)


# ============================================================
# SEARCH BY ID HANDLERS
# ============================================================

@router.callback_query(F.data == "search_start")
async def cb_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchStates.waiting)
    await safe_edit(callback, search_intro_text(),
                    reply_markup=None,
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await state.set_state(SearchStates.waiting)
        await safe_answer(message, search_intro_text(), reply_markup=None,
                          link_preview_options=NO_PREVIEW)
        return
    await _do_search(message, args[1].strip())


@router.message(StateFilter(SearchStates.waiting))
async def do_search_state(message: Message, state: FSMContext) -> None:
    query = (message.text or "").strip()
    await state.clear()
    await _do_search(message, query)


async def _do_search(message: Message, query: str) -> None:
    if not query.isdigit():
        await safe_answer(
            message,
            f"{e(3)} <b>ɪɴᴠᴀʟɪᴅ ɪᴅ</b>\n\nɪᴅ ᴍᴜꜱᴛ ʙᴇ ɴᴜᴍᴇʀɪᴄ\n\n"
            f"{footer('ᴛʀʏ ᴀɢᴀɪɴ')}",
            link_preview_options=NO_PREVIEW,
        )
        return
    in_collection = query in EMOJI_IDS
    emoji_markup = custom_emoji(query, "✨")
    if in_collection:
        idx = EMOJI_IDS.index(query) + 1
        text = (
            f"{header('ᴇᴍᴏᴊɪ ꜰᴏᴜɴᴅ')}\n\n"
            f"{emoji_markup} <b>ᴄᴜꜱᴛᴏᴍ ᴇᴍᴏᴊɪ</b>\n\n"
            f"{DIV_LIGHT}\n\n"
            f"ɪᴅ · <code>{html.escape(query)}</code>\n"
            f"ᴄᴏʟʟᴇᴄᴛɪᴏɴ · <code>#{idx:02d}</code>\n\n"
            f"{footer('ᴛᴀᴘ ᴛʜᴇ ɪᴅ ᴛᴏ ᴄᴏᴘʏ')}"
        )
    else:
        text = (
            f"{header('ɴᴏᴛ ɪɴ ᴄᴏʟʟᴇᴄᴛɪᴏɴ')}\n\n"
            f"{emoji_markup} <b>ᴀᴛᴛᴇᴍᴘᴛᴇᴅ ᴘʀᴇᴠɪᴇᴡ</b>\n\n"
            f"{DIV_LIGHT}\n\n"
            f"ɪᴅ · <code>{html.escape(query)}</code>\n\n"
            f"{footer('ɴᴏᴛ ɪɴ ᴏᴜʀ 25 ᴄᴏʟʟᴇᴄᴛɪᴏɴ')}"
        )
    await safe_answer(message, text, link_preview_options=NO_PREVIEW)


@router.message(Command("cancel"), StateFilter(SearchStates.waiting))
async def cmd_cancel_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await safe_answer(message, main_menu_text(is_admin),
                      reply_markup=main_menu_keyboard(is_admin),
                      link_preview_options=NO_PREVIEW)


# ============================================================
# FEEDBACK HANDLERS
# ============================================================

@router.callback_query(F.data == "feedback_start")
async def cb_feedback_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.waiting)
    await safe_edit(callback, feedback_intro_text(),
                    reply_markup=None,
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.waiting)
    await safe_answer(message, feedback_intro_text(), reply_markup=None,
                      link_preview_options=NO_PREVIEW)


@router.message(StateFilter(FeedbackStates.waiting))
async def do_feedback(message: Message, state: FSMContext, bot: Bot) -> None:
    text = (message.text or "").strip()
    if not text:
        await safe_answer(message, "Send text only.")
        return
    if len(text) > 2000:
        await safe_answer(message, "Too long (max 2000).")
        return
    await state.clear()
    user = message.from_user
    fid = await add_feedback(user.id, user.username or "", text)

    preview = text[:500]
    notif = (
        f"{header('ɴᴇᴡ ꜰᴇᴇᴅʙᴀᴄᴋ')}\n\n"
        f"#{fid} · @{user.username or user.id}\n"
        f"ɪᴅ · <code>{user.id}</code>\n\n"
        f"{DIV_LIGHT}\n\n"
        f"{html.escape(preview)}"
    )
    for admin_id in ADMIN_IDS:
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(admin_id, notif, link_preview_options=NO_PREVIEW)

    is_admin = user.id in ADMIN_IDS
    await safe_answer(
        message,
        f"{header('ᴛʜᴀɴᴋ ʏᴏᴜ')}\n\n"
        f"{e(19)} ꜰᴇᴇᴅʙᴀᴄᴋ #{fid} ꜱᴇɴᴛ\n\n"
        f"{footer('ᴛʜᴀɴᴋꜱ ꜰᴏʀ ʏᴏᴜʀ ɪɴᴘᴜᴛ')}",
        reply_markup=main_menu_keyboard(is_admin),
        link_preview_options=NO_PREVIEW,
    )


@router.message(Command("cancel"), StateFilter(FeedbackStates.waiting))
async def cmd_cancel_feedback(message: Message, state: FSMContext) -> None:
    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await safe_answer(message, main_menu_text(is_admin),
                      reply_markup=main_menu_keyboard(is_admin),
                      link_preview_options=NO_PREVIEW)


# ============================================================
# PREMIUM AD HANDLERS
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
    await safe_answer(message, premium_ad_intro_text(), reply_markup=None,
                      link_preview_options=NO_PREVIEW)


@router.message(StateFilter(PremiumAdStates.waiting_text,
                            PremiumAdStates.previewing))
async def receive_premium_ad_text(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await safe_answer(message, "Send text.")
        return
    original = message.text.strip()
    style = 0
    clean_html = generate_premium_variant(original, style)
    await state.update_data(original_text=original, clean_html=clean_html,
                            style_counter=style)
    await state.set_state(PremiumAdStates.previewing)
    is_admin = message.from_user.id in ADMIN_IDS
    await safe_answer(message,
        premium_ad_preview_wrap(clean_html, style),
        reply_markup=premium_ad_preview_keyboard(is_admin),
        link_preview_options=NO_PREVIEW)


@router.callback_query(F.data == "premium_change",
                       StateFilter(PremiumAdStates.previewing))
async def cb_premium_change(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    original = data.get("original_text", "")
    style = int(data.get("style_counter", 0)) + 1
    if not original:
        await callback.answer("No ad text.", show_alert=True)
        return
    clean_html = generate_premium_variant(original, style)
    await state.update_data(clean_html=clean_html, style_counter=style)
    is_admin = callback.from_user.id in ADMIN_IDS
    await safe_edit(callback, premium_ad_preview_wrap(clean_html, style),
                    reply_markup=premium_ad_preview_keyboard(is_admin),
                    link_preview_options=NO_PREVIEW)
    await callback.answer("Style changed")


@router.callback_query(F.data == "premium_forward",
                       StateFilter(PremiumAdStates.previewing))
async def cb_premium_forward(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    clean_html = data.get("clean_html", "")
    if not clean_html:
        await callback.answer("Nothing to forward.", show_alert=True)
        return
    try:
        await bot.send_message(chat_id=callback.from_user.id, text=clean_html,
                               parse_mode="HTML", link_preview_options=NO_PREVIEW)
    except TelegramAPIError as exc:
        await callback.answer(f"Failed: {exc}", show_alert=True)
        return
    await state.clear()
    is_admin = callback.from_user.id in ADMIN_IDS
    await safe_edit(callback,
        f"{header('ᴄʟᴇᴀɴ ᴀᴅ ꜱᴇɴᴛ')}\n\n"
        f"{e(19)} ʏᴏᴜʀ ᴄʟᴇᴀɴ ᴀᴅ ɪꜱ ʙᴇʟᴏᴡ\n\n"
        f"ʟᴏɴɢ-ᴘʀᴇꜱꜱ → ꜰᴏʀᴡᴀʀᴅ\n\n"
        f"{footer('ꜰᴏʀᴡᴀʀᴅ ᴛᴏ ᴀɴʏ ᴄʜᴀᴛ')}",
        reply_markup=admin_panel_keyboard() if is_admin else main_menu_keyboard(is_admin),
        link_preview_options=NO_PREVIEW)
    await callback.answer("Clean copy sent")


@router.callback_query(F.data == "premium_post_channel",
                       StateFilter(PremiumAdStates.previewing))
async def cb_premium_post_channel(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only.", show_alert=True)
        return
    data = await state.get_data()
    clean_html = data.get("clean_html", "")
    if not clean_html:
        await callback.answer("Nothing to post.", show_alert=True)
        return
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=clean_html,
                               parse_mode="HTML", link_preview_options=NO_PREVIEW)
    except TelegramAPIError as exc:
        await callback.answer(f"Failed: {exc}", show_alert=True)
        return
    await state.clear()
    await safe_edit(callback,
        f"{header('ᴀᴅ ᴘᴏꜱᴛᴇᴅ')}\n\n"
        f"{e(19)} ꜱᴇɴᴛ ᴛᴏ ᴄʜᴀɴɴᴇʟ\n\n"
        f"{footer('ᴛʜᴀɴᴋ ʏᴏᴜ')}",
        reply_markup=admin_panel_keyboard(),
        link_preview_options=NO_PREVIEW)
    await callback.answer("Posted")


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
# AUTO-DETECT: emoji ID in plain message
# ============================================================

@router.message(StateFilter(None), F.text.regexp(r"^\d{10,20}$"))
async def handle_id_in_message(message: Message) -> None:
    await _do_search(message, message.text.strip())


# ============================================================
# MAIN EMOJI EXTRACTION
# ============================================================

@router.message(StateFilter(None))
async def handle_any_message(message: Message, bot: Bot) -> None:
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
# ADMIN HELPERS
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


async def admin_panel_text(stats: dict[str, int]) -> str:
    ad_status = "ᴀᴄᴛɪᴠᴇ" if (_active_ad and not _active_ad.done()) else "ɪᴅʟᴇ"
    promos = await get_active_promos()
    unread = await unread_feedback_count()
    return (
        f"{header('ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ')}\n\n"
        f"{e(19)} <b>ᴜꜱᴇʀꜱ</b> · <code>{stats['total_users']}</code>\n"
        f"{e(20)} <b>ᴠᴇʀɪꜰɪᴇᴅ</b> · <code>{stats['verified_users']}</code>\n"
        f"{e(21)} <b>ᴠɪꜱɪᴛꜱ</b> · <code>{stats['visits']}</code>\n"
        f"{e(22)} <b>ᴇᴍᴏᴊɪ</b> · <code>{stats['emoji_queries']}</code>\n"
        f"{e(10)} <b>ᴛᴛꜱ</b> · <code>{stats['tts_queries']}</code>\n"
        f"{e(14)} <b>ꜱᴛɪᴄᴋᴇʀꜱ</b> · <code>{stats['stickers_made']}</code>\n"
        f"{e(24)} <b>ᴘʀᴏᴍᴏꜱ</b> · <code>{len(promos)}</code>\n"
        f"{e(12)} <b>ꜰᴇᴇᴅʙᴀᴄᴋ</b> · <code>{unread} new</code>\n"
        f"{e(0)} <b>ᴀᴅ</b> · <code>{ad_status}</code>\n"
        f"{e(1)} <b>ᴜᴘᴛɪᴍᴇ</b> · <code>{format_uptime()}</code>\n\n"
        f"{footer('ᴜꜱᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ')}"
    )


async def _show_admin_panel(event: Message | CallbackQuery, bot: Bot) -> None:
    stats = await get_stats()
    text = await admin_panel_text(stats)
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


@router.callback_query(F.data == "open_admin_panel", IsAdmin())
async def cb_open_admin_panel(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await _show_admin_panel(callback, bot)
    await callback.answer()


@router.message(Command("broadcast"), IsAdmin())
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting)
    await safe_answer(message,
        f"{header('ʙʀᴏᴀᴅᴄᴀꜱᴛ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴛʜᴇ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ\n\n"
        f"ɢᴏᴇꜱ ᴛᴏ ᴜꜱᴇʀꜱ + ᴄʜᴀɴɴᴇʟ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        link_preview_options=NO_PREVIEW)


@router.callback_query(F.data == "admin_broadcast", IsAdmin())
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting)
    await safe_edit(callback,
        f"{header('ʙʀᴏᴀᴅᴄᴀꜱᴛ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴛʜᴇ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ\n\n"
        f"ɢᴏᴇꜱ ᴛᴏ ᴜꜱᴇʀꜱ + ᴄʜᴀɴɴᴇʟ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.message(Command("ad"), IsAdmin())
async def cmd_ad(message: Message, state: FSMContext) -> None:
    if _active_ad and not _active_ad.done():
        await safe_answer(message, "Active ad running.")
        return
    await state.set_state(AdStates.waiting)
    await safe_answer(message,
        f"{header('ʀᴜɴ ᴀᴅ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴀᴅ ᴍᴇꜱꜱᴀɢᴇ\n\n"
        f"ᴄᴏᴜɴᴛ · {AD_SEND_COUNT} · ɢᴀᴘ · 10 ᴍɪɴ\n\n"
        f"{footer('/cancel ᴛᴏ ᴀʙᴏʀᴛ')}",
        link_preview_options=NO_PREVIEW)


@router.callback_query(F.data == "admin_ad", IsAdmin())
async def cb_admin_ad(callback: CallbackQuery, state: FSMContext) -> None:
    if _active_ad and not _active_ad.done():
        await callback.answer("Active ad running.", show_alert=True)
        return
    await state.set_state(AdStates.waiting)
    await safe_edit(callback,
        f"{header('ʀᴜɴ ᴀᴅ')}\n\n"
        f"{e(0)} ꜱᴇɴᴅ ᴀᴅ ᴍᴇꜱꜱᴀɢᴇ\n\n"
        f"ᴄᴏᴜɴᴛ · {AD_SEND_COUNT} · ɢᴀᴘ · 10 ᴍɪɴ\n\n"
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


# ---- Promo management ----

@router.callback_query(F.data == "promo_manage", IsAdmin())
async def cb_promo_manage(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    promos = await list_promos()
    text = (
        f"{header('ᴘʀᴏᴍᴏ ᴄʜᴀɴɴᴇʟꜱ')}\n\n"
        f"{e(13)} ᴀᴄᴛɪᴠᴇ · <code>{len(promos)}</code>\n\n"
        f"{DIV_LIGHT}\n\n"
        "ᴘᴀɪᴅ ᴘʀᴏᴍᴏᴛɪᴏɴꜱ · ᴜꜱᴇʀꜱ ᴍᴜꜱᴛ ᴊᴏɪɴ\n\n"
        f"{footer('ᴍᴀɴᴀɢᴇ ʙᴇʟᴏᴡ')}"
    )
    await safe_edit(callback, text, reply_markup=promo_manage_keyboard(),
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.callback_query(F.data == "promo_add", IsAdmin())
async def cb_promo_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoStates.waiting_chat_id)
    await safe_edit(callback,
        f"{header('ᴀᴅᴅ ᴘʀᴏᴍᴏ')}\n\n"
        f"{e(13)} ꜱᴛᴇᴘ 1 · ꜱᴇɴᴅ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴏʀ @ᴜꜱᴇʀɴᴀᴍᴇ\n\n"
        f"{DIV_LIGHT}\n\n"
        "ꜰᴏʀᴍᴀᴛꜱ:\n"
        "▸ <code>-1001234567890</code>\n"
        "▸ <code>@channelname</code>\n\n"
        f"{footer('ʙᴏᴛ ᴍᴜꜱᴛ ʙᴇ ᴀᴅᴍɪɴ')}",
        reply_markup=None,
        link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.message(StateFilter(PromoStates.waiting_chat_id), IsAdmin())
async def promo_got_chat(message: Message, state: FSMContext, bot: Bot) -> None:
    chat_id = (message.text or "").strip()
    if not chat_id:
        await safe_answer(message, "Send a channel ID or @username.")
        return
    try:
        chat = await bot.get_chat(chat_id)
        bot_member = await bot.get_chat_member(chat_id=chat.id, user_id=bot.id)
        if not isinstance(bot_member, (ChatMemberOwner, ChatMemberAdministrator)):
            await safe_answer(message,
                f"❌ ʙᴏᴛ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ {html.escape(chat.title or chat_id)}",
                link_preview_options=NO_PREVIEW)
            await state.clear()
            return
    except TelegramAPIError as exc:
        await safe_answer(message, f"❌ {exc}", link_preview_options=NO_PREVIEW)
        await state.clear()
        return

    await state.update_data(promo_chat_id=str(chat.id),
                            promo_title=chat.title or str(chat.id))
    await state.set_state(PromoStates.waiting_link)
    await safe_answer(message,
        f"{header('ꜱᴛᴇᴘ 2 · ɪɴᴠɪᴛᴇ ʟɪɴᴋ')}\n\n"
        f"{e(13)} ᴄʜᴀɴɴᴇʟ · <b>{html.escape(chat.title or str(chat.id))}</b>\n\n"
        f"ꜱᴇɴᴅ ɪɴᴠɪᴛᴇ ʟɪɴᴋ\n\n"
        f"{footer('ᴜꜱᴇ https://t.me/...')}",
        link_preview_options=NO_PREVIEW)


@router.message(StateFilter(PromoStates.waiting_link), IsAdmin())
async def promo_got_link(message: Message, state: FSMContext) -> None:
    link = (message.text or "").strip()
    if not link.startswith("http"):
        await safe_answer(message, "Send a valid URL.")
        return
    data = await state.get_data()
    chat_id = data.get("promo_chat_id", "")
    title = data.get("promo_title", "")
    await add_promo(chat_id, title, link)
    await state.clear()
    await safe_answer(message,
        f"{header('ᴘʀᴏᴍᴏ ᴀᴅᴅᴇᴅ')}\n\n"
        f"{e(19)} <b>{html.escape(title)}</b>\n"
        f"ɪᴅ · <code>{html.escape(chat_id)}</code>\n\n"
        f"{footer('ᴜꜱᴇʀꜱ ᴡɪʟʟ ʙᴇ ᴀꜱᴋᴇᴅ ᴛᴏ ᴊᴏɪɴ')}",
        reply_markup=promo_manage_keyboard(),
        link_preview_options=NO_PREVIEW)


@router.callback_query(F.data == "promo_list", IsAdmin())
async def cb_promo_list(callback: CallbackQuery) -> None:
    promos = await list_promos()
    if not promos:
        await safe_edit(callback,
            f"{header('ᴘʀᴏᴍᴏ ʟɪꜱᴛ')}\n\n"
            f"{e(3)} ɴᴏ ᴘʀᴏᴍᴏꜱ\n\n"
            f"{footer('ᴀᴅᴅ ᴀ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ')}",
            reply_markup=promo_manage_keyboard(),
            link_preview_options=NO_PREVIEW)
        await callback.answer()
        return
    lines = [header('ᴘʀᴏᴍᴏ ʟɪꜱᴛ'), ""]
    for i, p in enumerate(promos, 1):
        status = "✅" if p["active"] else "❌"
        lines.append(f"{status} {i}. <b>{html.escape(p['title'])}</b>")
        lines.append(f"   <code>{html.escape(p['chat_id'])}</code>")
    kb = InlineKeyboardBuilder()
    for p in promos:
        kb.row(mk_button(text=f"DELETE {p['title'][:20]}",
                         callback_data=f"promo_del:{p['chat_id']}",
                         icon_custom_emoji_id=BTN_HELP, style="danger"))
    kb.row(mk_button(text="BACK", callback_data="promo_manage",
                     icon_custom_emoji_id=BTN_HOME, style="primary"))
    await safe_edit(callback, "\n".join(lines),
                    reply_markup=kb.as_markup(),
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.callback_query(F.data.startswith("promo_del:"), IsAdmin())
async def cb_promo_del(callback: CallbackQuery) -> None:
    chat_id = callback.data.split(":", 1)[1]
    await delete_promo(chat_id)
    await callback.answer("Deleted.")
    await cb_promo_list(callback)


@router.message(Command("cancel"),
                StateFilter(PromoStates.waiting_chat_id, PromoStates.waiting_link))
async def cmd_cancel_promo(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await _show_admin_panel(message, bot)


# ---- Feedback viewing ----

@router.callback_query(F.data == "admin_feedbacks", IsAdmin())
async def cb_admin_feedbacks(callback: CallbackQuery) -> None:
    fbs = await list_feedbacks(limit=10)
    if not fbs:
        await safe_edit(callback,
            f"{header('ꜰᴇᴇᴅʙᴀᴄᴋ')}\n\n"
            f"{e(3)} ɴᴏ ꜰᴇᴇᴅʙᴀᴄᴋ ʏᴇᴛ\n\n"
            f"{footer('ᴜꜱᴇʀꜱ ᴄᴀɴ ꜱᴇɴᴅ ᴠɪᴀ ᴍᴇɴᴜ')}",
            reply_markup=admin_panel_keyboard(),
            link_preview_options=NO_PREVIEW)
        await callback.answer()
        return
    lines = [header('ʀᴇᴄᴇɴᴛ ꜰᴇᴇᴅʙᴀᴄᴋ'), ""]
    for fb in fbs:
        preview = fb["message"][:120]
        lines.append(f"#{fb['id']} · @{fb['username'] or fb['user_id']}")
        lines.append(f"<i>{html.escape(preview)}</i>")
        lines.append("")
    kb = InlineKeyboardBuilder()
    for fb in fbs[:5]:
        kb.row(mk_button(text=f"DELETE #{fb['id']}",
                         callback_data=f"fb_del:{fb['id']}",
                         icon_custom_emoji_id=BTN_HELP, style="danger"))
    kb.row(mk_button(text="BACK", callback_data="open_admin_panel",
                     icon_custom_emoji_id=BTN_HOME, style="primary"))
    await safe_edit(callback, "\n".join(lines),
                    reply_markup=kb.as_markup(),
                    link_preview_options=NO_PREVIEW)
    await callback.answer()


@router.callback_query(F.data.startswith("fb_del:"), IsAdmin())
async def cb_fb_del(callback: CallbackQuery) -> None:
    try:
        fid = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Invalid.")
        return
    await delete_feedback(fid)
    await callback.answer("Deleted.")
    await cb_admin_feedbacks(callback)


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
        f"{e(0)} ʙʀᴏᴀᴅᴄᴀꜱᴛɪɴɢ ᴛᴏ {len(user_ids)}...",
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
                f"ꜱᴇɴᴛ · <code>{sent}</code>\n"
                f"ꜰᴀɪʟᴇᴅ · <code>{failed}</code>\n"
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
            await bot.send_message(admin_id, f"Ad complete · {AD_SEND_COUNT}/{AD_SEND_COUNT}")
    except asyncio.CancelledError:
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(admin_id, "Ad cancelled.")
        raise
    finally:
        _active_ad = None


@router.message(StateFilter(AdStates.waiting), IsAdmin())
async def do_ad(message: Message, state: FSMContext, bot: Bot) -> None:
    global _active_ad
    await state.clear()
    if _active_ad and not _active_ad.done():
        await safe_answer(message, "Ad already running.",
                          reply_markup=admin_panel_keyboard())
        return
    _active_ad = asyncio.create_task(
        run_ad_task(bot=bot, admin_id=message.chat.id,
                    chat_id=message.chat.id, msg_id=message.message_id)
    )
    await safe_answer(message,
        f"{header('ᴀᴅ ꜱᴛᴀʀᴛᴇᴅ')}\n\n"
        f"{e(0)} {AD_SEND_COUNT} ᴛɪᴍᴇꜱ · 10 ᴍɪɴ ɢᴀᴘ\n"
        f"ᴛᴏᴛᴀʟ · 40 ᴍɪɴ\n\n"
        f"{footer('ᴄᴀɴᴄᴇʟ ᴠɪᴀ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ')}",
        reply_markup=admin_panel_keyboard(),
        link_preview_options=NO_PREVIEW)


@router.message(Command("cancel"),
                StateFilter(BroadcastStates.waiting, AdStates.waiting))
async def cmd_cancel_admin(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await _show_admin_panel(message, bot)


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
.container { max-width: 1200px; margin: 0 auto; }
header { text-align: center; margin-bottom: 50px; }
h1 {
  font-size: clamp(2rem, 5vw, 3.5rem); font-weight: 800;
  background: linear-gradient(135deg, #667eea, #764ba2, #f093fb);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.tagline { color: rgba(255,255,255,0.55); margin-top: 12px;
  font-size: 0.95rem; letter-spacing: 2px; text-transform: uppercase; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 22px; }
.card { background: rgba(255,255,255,0.05); backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.1); border-radius: 20px;
  padding: 30px; position: relative; overflow: hidden; }
.card::before { content: ''; position: absolute; top: 0; left: 0; right: 0;
  height: 3px; background: linear-gradient(90deg, #667eea, #764ba2, #f093fb); }
.value { font-size: 2.6rem; font-weight: 800;
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


async def render_dashboard_async() -> str:
    stats = await get_stats()
    promos = await get_active_promos()
    unread = await unread_feedback_count()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ad_state = "1 running" if (_active_ad and not _active_ad.done()) else "0"
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
<title>Premium Multi-Tool Bot · Dashboard</title>
<style>{DASHBOARD_STYLES}</style></head>
<body><div class="container">
<header><h1>Premium Multi-Tool Bot</h1>
<p class="tagline">Live Dashboard · Auto-refresh 30s</p></header>
<div class="grid">
<div class="card"><div class="value">{stats['total_users']}</div><div class="label">Total Users</div></div>
<div class="card"><div class="value">{stats['verified_users']}</div><div class="label">Verified</div></div>
<div class="card"><div class="value">{stats['visits']}</div><div class="label">Visits</div></div>
<div class="card"><div class="value">{stats['emoji_queries']}</div><div class="label">Emoji Queries</div></div>
<div class="card"><div class="value">{stats['tts_queries']}</div><div class="label">TTS Queries</div></div>
<div class="card"><div class="value">{stats['stickers_made']}</div><div class="label">Stickers Made</div></div>
<div class="card"><div class="value">{len(promos)}</div><div class="label">Promo Channels</div></div>
<div class="card"><div class="value">{unread}</div><div class="label">Unread Feedback</div></div>
<div class="card"><div class="value">{ad_state}</div><div class="label">Active Ads</div></div>
<div class="card"><div class="value">{format_uptime()}</div><div class="label">Uptime</div></div>
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
    html_out = await render_dashboard_async()
    return web.Response(text=html_out, content_type="text/html")


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
    asyncio.create_task(ensure_font())
    await validate_emoji_ids(bot)
    asyncio.create_task(start_http_server())
    logger.info("=== BOT STARTED ===")
    logger.info("Admins: %s", sorted(ADMIN_IDS) or "EMPTY")
    logger.info("Dashboard: %s", DASHBOARD_URL or "not set")
    promos = await get_active_promos()
    logger.info("Active promos: %s", len(promos))


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
