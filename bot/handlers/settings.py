from contextlib import suppress

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards import delete_confirm_keyboard, settings_keyboard
from core.manager import WorkerManager
from storage.db import Database
from storage.models import SETTING_LABELS

router = Router()


def _settings_text(enabled: bool) -> str:
    status = "🟢 активен" if enabled else "⏸ на паузе"
    return f"<b>Настройки уведомлений</b>\nСтатус: {status}\n\nНажми, чтобы включить/выключить категорию:"


@router.message(Command("settings"))
async def cmd_settings(message: Message, db: Database) -> None:
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала подключи аккаунт через /start.")
        return
    await message.answer(
        _settings_text(user.enabled),
        reply_markup=settings_keyboard(user.settings, user.enabled),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(callback: CallbackQuery, db: Database) -> None:
    key = callback.data.split(":", 1)[1]
    if key not in SETTING_LABELS:
        await callback.answer()
        return
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала /start", show_alert=True)
        return
    user.settings[key] = not user.settings.get(key, False)
    await db.update_settings(user.tg_id, user.settings)
    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(
            reply_markup=settings_keyboard(user.settings, user.enabled),
        )
    await callback.answer("Сохранено")


@router.callback_query(F.data == "toggle_enabled")
async def cb_toggle_enabled(callback: CallbackQuery, db: Database, manager: WorkerManager) -> None:
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала /start", show_alert=True)
        return
    new_enabled = not user.enabled
    await db.set_enabled(user.tg_id, new_enabled)
    user.enabled = new_enabled

    if new_enabled:
        await manager.start_user(user)
    else:
        await manager.stop_user(user.tg_id)

    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            _settings_text(user.enabled),
            reply_markup=settings_keyboard(user.settings, user.enabled),
            parse_mode=ParseMode.HTML,
        )
    await callback.answer("Готово")


@router.callback_query(F.data == "close")
async def cb_close(callback: CallbackQuery) -> None:
    with suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "delete_confirm")
async def cb_delete_confirm(callback: CallbackQuery) -> None:
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            "Точно удалить аккаунт? Токен и настройки будут стёрты. "
            "Не забудь отозвать токен в настройках безопасности ВК.",
            reply_markup=delete_confirm_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "delete_yes")
async def cb_delete_yes(callback: CallbackQuery, db: Database, manager: WorkerManager) -> None:
    await manager.stop_user(callback.from_user.id)
    await db.delete_user(callback.from_user.id)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("Аккаунт удалён. Возвращайся через /start.")
    await callback.answer()


@router.callback_query(F.data == "delete_no")
async def cb_delete_no(callback: CallbackQuery, db: Database) -> None:
    user = await db.get_user(callback.from_user.id)
    if not user:
        with suppress(TelegramBadRequest):
            await callback.message.delete()
        await callback.answer()
        return
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            _settings_text(user.enabled),
            reply_markup=settings_keyboard(user.settings, user.enabled),
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@router.message(Command("pause"))
async def cmd_pause(message: Message, db: Database, manager: WorkerManager) -> None:
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала /start.")
        return
    if not user.enabled:
        await message.answer("Уже на паузе.")
        return
    await db.set_enabled(user.tg_id, False)
    await manager.stop_user(user.tg_id)
    await message.answer("⏸ Поставил на паузу. /resume — возобновить.")


@router.message(Command("resume"))
async def cmd_resume(message: Message, db: Database, manager: WorkerManager) -> None:
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала /start.")
        return
    if user.enabled:
        await message.answer("Уже активен.")
        return
    await db.set_enabled(user.tg_id, True)
    user.enabled = True
    await manager.start_user(user)
    await message.answer("▶️ Возобновил.")


@router.message(Command("stop"))
async def cmd_stop(message: Message, db: Database, manager: WorkerManager) -> None:
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Аккаунт и так не подключён.")
        return
    await manager.stop_user(user.tg_id)
    await db.delete_user(user.tg_id)
    await message.answer(
        "Аккаунт удалён. Не забудь отозвать токен в настройках безопасности ВК."
    )
