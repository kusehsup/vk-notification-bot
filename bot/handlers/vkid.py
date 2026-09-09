"""Хэндлеры для VK ID — доступны только владельцу (tg_id=OWNER_TG_ID).

Флоу:
1. /vkid_setup — начинается диалог: пришли access_token → пришли cookies
2. Проверяем цепочку web_token → activity, если всё ок — сохраняем в БД
3. /vkid_snapshot — показывает все сессии по одной с кнопками «моё / не моё / игнорить»
4. /vkid_status — показывает есть ли активная сессия, срок токена, кол-во устройств
5. /vkid_stop — удаляет всё
"""
from __future__ import annotations

import json
import logging
from contextlib import suppress

import aiohttp
from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from storage.db import Database
from vk.vkid_client import (
    ActivityItem,
    VKIDClient,
    VKIDError,
    VKIDSession,
    VKIDUnauthorized,
)

logger = logging.getLogger(__name__)

OWNER_TG_ID = 952766753  # только этот юзер видит команды

router = Router()


class SetupStates(StatesGroup):
    waiting_token = State()
    waiting_cookies = State()


def _owner_only(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id == OWNER_TG_ID


def _owner_only_cb(cb: CallbackQuery) -> bool:
    return cb.from_user is not None and cb.from_user.id == OWNER_TG_ID


# --- /vkid_setup ---

SETUP_INTRO = (
    "🔐 <b>Настройка VK ID мониторинга</b>\n\n"
    "Пришлём цепочку из двух сообщений:\n"
    "1. <b>access_token</b> из тела запроса <code>login.vk.com/?act=web_token</code>\n"
    "2. <b>cookie header</b> целиком — сообщением или <b>.txt файлом</b> (если не влезает)\n\n"
    "Всё удаляется из чата сразу после получения. Пришли <b>access_token</b> следующим сообщением. "
    "Или <code>/cancel</code> чтобы отменить."
)


@router.message(Command("vkid_setup"))
async def cmd_vkid_setup(message: Message, state: FSMContext) -> None:
    if not _owner_only(message):
        return
    await state.set_state(SetupStates.waiting_token)
    await message.answer(SETUP_INTRO, parse_mode=ParseMode.HTML)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if not _owner_only(message):
        return
    current = await state.get_state()
    if current is None:
        return
    await state.clear()
    await message.answer("Отменено.")


@router.message(SetupStates.waiting_token, F.text)
async def receive_token(message: Message, state: FSMContext) -> None:
    if not _owner_only(message):
        return
    token = (message.text or "").strip()
    with suppress(Exception):
        await message.delete()
    if not token.startswith("vk1."):
        await message.answer("❌ Не похоже на VK ID токен (должен начинаться с <code>vk1.</code>). Попробуй ещё раз или /cancel.", parse_mode=ParseMode.HTML)
        return
    await state.update_data(access_token=token)
    await state.set_state(SetupStates.waiting_cookies)
    await message.answer("✅ Токен принят. Теперь пришли строку <b>Cookie</b> целиком (можно с DevTools → скопировать значение заголовка Cookie).", parse_mode=ParseMode.HTML)


@router.message(SetupStates.waiting_cookies, F.text | F.document)
async def receive_cookies(message: Message, state: FSMContext, db: Database) -> None:
    if not _owner_only(message):
        return

    cookies: str = ""
    if message.document:
        # cookies пришли файлом
        doc = message.document
        MAX = 100_000  # 100 KB — с большим запасом
        if doc.file_size and doc.file_size > MAX:
            await message.answer("❌ Файл слишком большой (>100 KB), это не cookie header.")
            return
        try:
            file = await message.bot.get_file(doc.file_id)
            buf = await message.bot.download_file(file.file_path)
            if buf is None:
                await message.answer("❌ Не смог скачать файл. Попробуй ещё раз или /cancel.")
                return
            cookies = buf.read().decode("utf-8", errors="replace").strip()
        except Exception:
            logger.exception("failed to read cookies file")
            await message.answer("❌ Ошибка чтения файла. Попробуй ещё раз или /cancel.")
            return
    else:
        cookies = (message.text or "").strip()

    with suppress(Exception):
        await message.delete()

    if "remixsid=" not in cookies:
        await message.answer("❌ В строке нет <code>remixsid</code> — это не то что нужно. Пришли Cookie целиком или /cancel.", parse_mode=ParseMode.HTML)
        return

    data = await state.get_data()
    access_token: str = data["access_token"]

    status = await message.answer("⏳ Проверяю цепочку через VK ID…")

    vkid_session = VKIDSession(access_token=access_token, cookies=cookies, expires_at=0)
    client = VKIDClient(vkid_session)
    try:
        async with aiohttp.ClientSession() as http:
            await client.refresh_token(http)
            items = await client.get_activity(http)
    except VKIDUnauthorized as e:
        await status.edit_text(f"❌ VK ID отверг: {e}. Токен или cookies недействительны.")
        await state.clear()
        return
    except VKIDError as e:
        await status.edit_text(f"❌ Ошибка VK ID: {e}")
        await state.clear()
        return
    except Exception:
        logger.exception("VK ID setup crashed")
        await status.edit_text("❌ Сломалось. Подробности в логах.")
        await state.clear()
        return

    # Сохраняем
    await db.upsert_vkid_session(
        tg_id=message.from_user.id,
        access_token=vkid_session.access_token,
        cookies=vkid_session.cookies,
        expires_at=vkid_session.expires_at,
        logout_hash=vkid_session.logout_hash,
    )
    # Заносим все trust_key'и как unknown (пока не размечены)
    for it in items:
        await db.upsert_vkid_trust(
            tg_id=message.from_user.id,
            trust_key=it.trust_key(),
            device_name=it.device_name,
            device_os=it.device_os,
            app_name=it.app_name,
            city=it.city,
            ip=it.ip,
            trust="unknown",
        )
    # Все текущие сессии помечаем как "виденные" — не хотим уведомлять о том что было ДО настройки
    for it in items:
        await db.mark_seen_vkid_session(message.from_user.id, it.fingerprint())

    await state.clear()
    await status.edit_text(
        f"✅ Готово. Найдено сессий: <b>{len(items)}</b>.\n\n"
        "Открой <code>/vkid_snapshot</code> — размечу каждое устройство «моё / не моё», "
        "чтобы бот знал кого игнорировать, а о ком уведомлять.",
        parse_mode=ParseMode.HTML,
    )


# --- /vkid_status ---

@router.message(Command("vkid_status"))
async def cmd_vkid_status(message: Message, db: Database) -> None:
    if not _owner_only(message):
        return
    sess = await db.get_vkid_session(message.from_user.id)
    if not sess:
        await message.answer("VK ID не настроен. Используй /vkid_setup.")
        return
    import time as _t
    now = int(_t.time())
    remaining = sess["expires_at"] - now
    remaining_str = f"{remaining // 60}м {remaining % 60}с" if remaining > 0 else "истёк"

    last_ok = sess.get("last_success_at") or 0
    if last_ok == 0:
        last_ok_str = "ещё ни разу"
    else:
        idle = now - last_ok
        if idle < 60:
            last_ok_str = f"{idle}с назад"
        elif idle < 3600:
            last_ok_str = f"{idle // 60}м назад"
        else:
            last_ok_str = f"{idle // 3600}ч {(idle % 3600) // 60}м назад"

    await message.answer(
        f"🔐 <b>VK ID</b> активен.\n"
        f"• Токен истекает через: <b>{remaining_str}</b>\n"
        f"• Последний успешный опрос: <b>{last_ok_str}</b>",
        parse_mode=ParseMode.HTML,
    )


# --- /vkid_stop ---

@router.message(Command("vkid_stop"))
async def cmd_vkid_stop(message: Message, db: Database) -> None:
    if not _owner_only(message):
        return
    await db.delete_vkid_session(message.from_user.id)
    await message.answer("🗑 VK ID мониторинг отключён, данные удалены.")


# --- /vkid_snapshot ---

TRUST_LABELS = {
    "mine": "✅ моё",
    "not_mine": "⚠️ чужое",
    "ignore": "🔕 игнор",
    "unknown": "❓ не размечено",
}


def _card(item: ActivityItem, trust: str) -> str:
    mark = TRUST_LABELS.get(trust, TRUST_LABELS["unknown"])
    inactive = " (неактивна)" if item.is_inactive else ""
    return (
        f"<b>{item.app_name}</b> — {mark}\n"
        f"📱 {item.device_name} · {item.device_os}\n"
        f"📍 {item.city or '—'}\n"
        f"🌐 <code>{item.ip}</code>  <i>(подсеть {item.ip_prefix()}.*)</i>\n"
        f"🕐 {item.created_at}{inactive}"
    )


def _short_key(trust_key: str) -> str:
    """Короткий id для callback_data — TG ограничивает 64 байтами."""
    import hashlib
    return hashlib.sha1(trust_key.encode()).hexdigest()[:16]


# in-memory кэш short_key → trust_key на процесс
_KEY_CACHE: dict[str, str] = {}


def _register_key(trust_key: str) -> str:
    sk = _short_key(trust_key)
    _KEY_CACHE[sk] = trust_key
    return sk


def _card_keyboard(short: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Моё", callback_data=f"vkid_mine:{short}"),
            InlineKeyboardButton(text="⚠️ Не моё", callback_data=f"vkid_not:{short}"),
        ],
        [InlineKeyboardButton(text="🔕 Игнорировать", callback_data=f"vkid_ign:{short}")],
    ])


@router.message(Command("vkid_snapshot"))
async def cmd_vkid_snapshot(message: Message, db: Database) -> None:
    if not _owner_only(message):
        return
    sess = await db.get_vkid_session(message.from_user.id)
    if not sess:
        await message.answer("VK ID не настроен. Используй /vkid_setup.")
        return

    vkid = VKIDClient(VKIDSession(
        access_token=sess["access_token"],
        cookies=sess["cookies"],
        expires_at=sess["expires_at"],
        logout_hash=sess["logout_hash"],
    ))
    try:
        async with aiohttp.ClientSession() as http:
            if vkid.token_needs_refresh():
                await vkid.refresh_token(http)
                await db.update_vkid_token(message.from_user.id, vkid.session.access_token, vkid.session.expires_at)
            items = await vkid.get_activity(http)
    except VKIDUnauthorized as e:
        await message.answer(f"❌ VK ID сессия невалидна: {e}. Настрой заново через /vkid_setup.")
        return
    except VKIDError as e:
        await message.answer(f"❌ Ошибка VK ID: {e}")
        return

    # Уникальные trust_key (устройство+подсеть+приложение). Одному ключу может соответствовать
    # несколько записей за разные дни/города — берём самую свежую (первую в списке).
    seen: set[str] = set()
    unique: list[ActivityItem] = []
    for it in items:
        tk = it.trust_key()
        if tk in seen:
            continue
        seen.add(tk)
        unique.append(it)

    await message.answer(f"Найдено уникальных «сессий» (устройство+подсеть+приложение): <b>{len(unique)}</b>.\nРазмечай кнопками — метка применяется ко всей подсети <code>x.y.*</code>.", parse_mode=ParseMode.HTML)

    for it in unique:
        tk = it.trust_key()
        trust = await db.get_vkid_trust(message.from_user.id, tk) or "unknown"
        short = _register_key(tk)
        await message.answer(
            _card(it, trust),
            reply_markup=_card_keyboard(short),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def _mark_and_refresh(cb: CallbackQuery, db: Database, short: str, trust: str, toast: str) -> None:
    tk = _KEY_CACHE.get(short)
    if not tk:
        await cb.answer("Устарело, вызови /vkid_snapshot заново", show_alert=True)
        return
    await db.set_vkid_trust(cb.from_user.id, tk, trust)
    await cb.answer(toast)

    # Перерисовать метку в тексте карточки
    text = cb.message.html_text or ""
    lines = text.split("\n")
    if lines and "—" in lines[0]:
        before, _, _ = lines[0].rpartition("—")
        lines[0] = f"{before.rstrip()} — {TRUST_LABELS.get(trust, TRUST_LABELS['unknown'])}"
    new_text = "\n".join(lines)
    with suppress(TelegramBadRequest):
        await cb.message.edit_text(
            new_text,
            reply_markup=_card_keyboard(short),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


@router.callback_query(F.data.startswith("vkid_mine:"))
async def cb_vkid_mine(cb: CallbackQuery, db: Database) -> None:
    if not _owner_only_cb(cb):
        await cb.answer()
        return
    await _mark_and_refresh(cb, db, cb.data.split(":", 1)[1], "mine", "✅ Отмечено как «моё»")


@router.callback_query(F.data.startswith("vkid_not:"))
async def cb_vkid_not_mine(cb: CallbackQuery, db: Database) -> None:
    if not _owner_only_cb(cb):
        await cb.answer()
        return
    await _mark_and_refresh(cb, db, cb.data.split(":", 1)[1], "not_mine", "⚠️ Отмечено как «чужое»")


@router.callback_query(F.data.startswith("vkid_ign:"))
async def cb_vkid_ignore(cb: CallbackQuery, db: Database) -> None:
    if not _owner_only_cb(cb):
        await cb.answer()
        return
    await _mark_and_refresh(cb, db, cb.data.split(":", 1)[1], "ignore", "🔕 Игнорирую")


# --- Быстрая разметка из уведомления watcher'а ---

@router.callback_query(F.data.startswith("vkid_alert_mine:"))
async def cb_alert_mine(cb: CallbackQuery, db: Database) -> None:
    if not _owner_only_cb(cb):
        await cb.answer()
        return
    short = cb.data.split(":", 1)[1]
    tk = _KEY_CACHE.get(short)
    if not tk:
        await cb.answer("Устарело", show_alert=True)
        return
    await db.set_vkid_trust(cb.from_user.id, tk, "mine")
    await cb.answer("✅ Помечено как «моё» — больше не будет уведомлять о подсети")
    with suppress(TelegramBadRequest):
        await cb.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("vkid_alert_not:"))
async def cb_alert_not_mine(cb: CallbackQuery, db: Database) -> None:
    if not _owner_only_cb(cb):
        await cb.answer()
        return
    short = cb.data.split(":", 1)[1]
    tk = _KEY_CACHE.get(short)
    if not tk:
        await cb.answer("Устарело", show_alert=True)
        return
    await db.set_vkid_trust(cb.from_user.id, tk, "not_mine")
    await cb.answer("⚠️ Помечено как «чужое»")
    with suppress(TelegramBadRequest):
        await cb.message.edit_reply_markup(reply_markup=None)


# доступ к кэшу для manager'а (уведомления watcher'а тоже добавляют ключи)
def register_key_for_alert(trust_key: str) -> str:
    return _register_key(trust_key)
