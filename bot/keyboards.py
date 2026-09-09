from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from storage.models import SETTING_LABELS


def settings_keyboard(settings: dict[str, bool], enabled: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key, label in SETTING_LABELS.items():
        mark = "✅" if settings.get(key, False) else "⬜️"
        rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"toggle:{key}")])

    pause_label = "⏸ Поставить на паузу" if enabled else "▶️ Возобновить"
    rows.append([InlineKeyboardButton(text=pause_label, callback_data="toggle_enabled")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data="delete_confirm")])
    rows.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да, удалить", callback_data="delete_yes"),
            InlineKeyboardButton(text="Отмена", callback_data="delete_no"),
        ]
    ])
