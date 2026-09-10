import logging
import re
from contextlib import suppress

import aiohttp
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.types import Message

from bot.oauth import auth_keyboard
from core.manager import WorkerManager
from storage.db import Database
from vk.client import VKAPIError, VKClient

logger = logging.getLogger(__name__)

router = Router()

TOKEN_RE = re.compile(r"vk1\.a\.[A-Za-z0-9_\-]+|[a-f0-9]{85,}", re.IGNORECASE)

NO_MESSAGES_TEXT = (
    "❌ У токена нет доступа к сообщениям ВК.\n\n"
    "Так бывает, если авторизоваться не тем приложением. "
    "Нажми <b>Войти через VK Admin</b>, разреши доступ и пришли новый токен."
)

FLOOD_TEXT = (
    "❌ ВК отклонил этот токен (Flood control) — так сейчас режутся ключи Kate Mobile.\n\n"
    "Получи <b>новый</b> токен кнопкой VK Admin ниже и пришли его сюда."
)


def extract_token(text: str) -> str | None:
    text = text.strip()
    m = re.search(r"access_token=([^&\s#]+)", text)
    if m:
        return m.group(1)
    m = TOKEN_RE.search(text)
    if m:
        return m.group(0)
    return None


@router.message(F.text & ~F.text.startswith("/"))
async def receive_token(message: Message, db: Database, manager: WorkerManager) -> None:
    existing = await db.get_user(message.from_user.id)
    if existing:
        await message.answer(
            "Ты уже подключён. Чтобы сменить токен (например, уйти с Kate Mobile) — "
            "сначала /stop, потом пришли новый токен.",
            reply_markup=auth_keyboard(),
        )
        return

    token = extract_token(message.text or "")
    if not token:
        await message.answer(
            "Не похоже на токен. Пришли строку <code>access_token=...</code> или сам токен. "
            "Кнопки входа — ниже, подробности в /start.",
            reply_markup=auth_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    with suppress(Exception):
        await message.delete()

    status = await message.answer("Проверяю токен…")

    async with aiohttp.ClientSession() as session:
        client = VKClient(token, session)
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

    user = await db.upsert_user(message.from_user.id, token, vk_user_id)
    await manager.start_user(user)

    await status.edit_text(
        f"✅ Подключено к аккаунту <b>{name}</b> (id{vk_user_id}).\n\n"
        "Уведомления уже приходят. Настроить категории: /settings",
        parse_mode=ParseMode.HTML,
    )
