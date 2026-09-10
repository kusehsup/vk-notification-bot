import logging
from contextlib import suppress

import aiohttp
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.types import Message

from bot.handlers.token_parse import extract_token
from bot.oauth import auth_keyboard
from core.manager import WorkerManager
from storage.db import Database
from vk.client import VKAPIError, VKClient
from vk.web_token import (
    WebTokenError,
    WebTokenUnauthorized,
    cookies_to_header,
    exchange_cookies_for_api,
    parse_cookie_blob,
)

logger = logging.getLogger(__name__)

router = Router()

MAX_COOKIE_FILE_BYTES = 100_000

NO_MESSAGES_TEXT = (
    "❌ У этой сессии нет доступа к сообщениям ВК.\n\n"
    "Пришли <b>полный</b> заголовок Cookie с открытого vk.com "
    "(F12 → Network → Cookie, внутри должен быть <code>remixsid=</code>)."
)

FLOOD_TEXT = (
    "❌ ВК ответил Flood control на эту сессию.\n\n"
    "Подожди и пришли свежий Cookie с vk.com. Не используй старые токены Kate Mobile."
)

COOKIE_BAD_TEXT = (
    "Не похоже на сессию vk.com.\n\n"
    "Нужен заголовок <code>Cookie</code> с <code>remixsid=</code> "
    "(F12 → Network на vk.com) — текстом или .txt файлом.\n"
    "Старые кнопки VK Admin / Android больше не работают."
)


async def _payload_text(message: Message) -> str:
    if message.document:
        doc = message.document
        if doc.file_size and doc.file_size > MAX_COOKIE_FILE_BYTES:
            return ""
        try:
            file = await message.bot.get_file(doc.file_id)
            buf = await message.bot.download_file(file.file_path)
            if buf is None:
                return message.caption or ""
            return buf.read().decode("utf-8", errors="replace")
        except Exception:
            logger.exception("Failed to download cookie file")
            return message.caption or ""
    return message.text or message.caption or ""


@router.message((F.text & ~F.text.startswith("/")) | F.document)
async def receive_session(message: Message, db: Database, manager: WorkerManager) -> None:
    raw = await _payload_text(message)
    cookies = parse_cookie_blob(raw)
    token = extract_token(raw) if not cookies else None

    if not cookies and not token:
        await message.answer(
            COOKIE_BAD_TEXT,
            reply_markup=auth_keyboard(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    with suppress(Exception):
        await message.delete()

    status = await message.answer("Проверяю сессию ВК…")

    if cookies:
        await _connect_cookies(status, message.from_user.id, cookies, token, db, manager)
        return
    await _connect_token(status, message.from_user.id, token or "", db, manager)


async def _connect_cookies(
    status,
    tg_id: int,
    cookies: dict[str, str],
    extra_token: str | None,
    db: Database,
    manager: WorkerManager,
) -> None:
    async with aiohttp.ClientSession() as session:
        try:
            web = await exchange_cookies_for_api(
                session,
                cookies,
                limiter=manager.limiter,
                extra_token=extra_token,
            )
        except WebTokenUnauthorized:
            await status.edit_text(
                "❌ Cookie не принят (сессия истекла или это не remixsid с vk.com).\n\n"
                "Открой vk.com заново, скопируй Cookie из Network и пришли ещё раз.",
                reply_markup=auth_keyboard(),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return
        except VKAPIError as e:
            logger.warning("Cookie session API failed: %s", e)
            if e.is_flood:
                await status.edit_text(
                    FLOOD_TEXT,
                    reply_markup=auth_keyboard(),
                    parse_mode=ParseMode.HTML,
                )
                return
            if e.code in (7, 15, 20, 21, 27, 28):
                await status.edit_text(
                    NO_MESSAGES_TEXT,
                    reply_markup=auth_keyboard(),
                    parse_mode=ParseMode.HTML,
                )
                return
            await status.edit_text(
                f"❌ ВК отклонил сессию: {e.message}",
                reply_markup=auth_keyboard(),
            )
            return
        except WebTokenError as e:
            logger.warning("web_token failed: %s", e)
            await status.edit_text(
                f"❌ Не удалось обменять Cookie на токен ВК: {e}",
                reply_markup=auth_keyboard(),
            )
            return
        except Exception:
            logger.exception("Cookie validation crashed")
            await status.edit_text("❌ Не удалось проверить сессию. Попробуй ещё раз.")
            return

    users = web.users
    if not users:
        await status.edit_text("❌ ВК не вернул профиль. Пришли Cookie ещё раз.")
        return

    vk_user = users[0]
    vk_user_id = vk_user["id"]
    name = f"{vk_user.get('first_name', '')} {vk_user.get('last_name', '')}".strip()

    user = await db.upsert_user(
        tg_id,
        web.access_token,
        vk_user_id,
        vk_cookies=cookies_to_header(web.cookies),
        vk_token_expires_at=web.expires_at,
        vk_app_id=web.app_id,
    )
    await manager.start_user(user)
    await status.edit_text(
        f"✅ Подключено к аккаунту <b>{name}</b> (id{vk_user_id}).\n\n"
        "Уведомления уже приходят. Настроить категории: /settings",
        parse_mode=ParseMode.HTML,
    )


async def _connect_token(
    status,
    tg_id: int,
    token: str,
    db: Database,
    manager: WorkerManager,
) -> None:
    async with aiohttp.ClientSession() as session:
        client = VKClient(token, session, limiter=manager.limiter)
        try:
            users = await client.users_get()
            await client.messages_get_long_poll_server()
        except VKAPIError as e:
            logger.warning("Token validation failed: %s", e)
            if e.is_flood:
                await status.edit_text(
                    FLOOD_TEXT,
                    reply_markup=auth_keyboard(),
                    parse_mode=ParseMode.HTML,
                )
                return
            if e.code in (7, 15, 20, 21, 27, 28):
                await status.edit_text(
                    NO_MESSAGES_TEXT,
                    reply_markup=auth_keyboard(),
                    parse_mode=ParseMode.HTML,
                )
                return
            await status.edit_text(
                f"❌ Токен не работает: {e.message}",
                reply_markup=auth_keyboard(),
            )
            return
        except Exception:
            logger.exception("Token validation crashed")
            await status.edit_text("❌ Не удалось проверить токен. Попробуй ещё раз.")
            return

    if not users:
        await status.edit_text("❌ ВК не вернул профиль. Возможно, токен некорректный.")
        return

    vk_user = users[0]
    vk_user_id = vk_user["id"]
    name = f"{vk_user.get('first_name', '')} {vk_user.get('last_name', '')}".strip()

    user = await db.upsert_user(tg_id, token, vk_user_id)
    await manager.start_user(user)
    await status.edit_text(
        f"✅ Подключено к аккаунту <b>{name}</b> (id{vk_user_id}).\n\n"
        "Это обычный токен без Cookie — он не обновится сам. "
        "Надёжнее прислать Cookie с vk.com.\n"
        "Настроить категории: /settings",
        parse_mode=ParseMode.HTML,
    )
