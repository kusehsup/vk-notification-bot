"""Тексты подключения: сессия vk.com вместо мёртвого OAuth.

Kate Mobile, VK Admin и официальный Android-клиент больше не отдают
messages через oauth.vk.com (blocked / direct auth only).
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

VK_SITE = "https://vk.ru"


def auth_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть vk.com", url=VK_SITE)],
        ]
    )


START_TEXT = (
    "👋 Привет! Я ретранслирую уведомления из ВКонтакте в Telegram.\n\n"
    "<b>Что я умею пересылать:</b>\n"
    "• Личные сообщения (мгновенно)\n"
    "• Лайки, комментарии, упоминания\n"
    "• Заявки в друзья, репосты, приглашения\n\n"
    "<b>Как подключить аккаунт</b>\n"
    "Нужна cookie <code>remixsid</code> с сайта vk.ru. Весь заголовок Cookie из Network "
    "слать не надо — Telegram его обрезает.\n\n"
    "1. Открой <a href=\"https://vk.ru\">vk.ru</a> и войди\n"
    "2. F12 → вкладка <b>Application</b> (Приложение) → Cookies → <code>https://vk.ru</code>\n"
    "3. Кликни <code>remixsid</code>, скопируй <b>Value</b>\n"
    "4. Пришли одной строкой: <code>remixsid=значение</code>\n\n"
    "Не копируй <code>document.cookie</code> из консоли: там нет HttpOnly "
    "<code>remixsid</code>.\n\n"
    "⚠️ remixsid — полный вход в аккаунт. Храню зашифрованным, сообщение сразу удаляю. "
    "Отключить: /stop, плюс «Выйти на всех устройствах» в настройках VK.\n\n"
    "Команды:\n"
    "/settings — категории уведомлений\n"
    "/pause — пауза\n"
    "/resume — возобновить\n"
    "/stop — удалить аккаунт и сессию\n"
    "/auth — снова показать инструкцию"
)


REAUTH_TEXT = (
    "⚠️ <b>Нужна cookie remixsid</b>\n\n"
    "1. Открой <a href=\"https://vk.ru\">vk.ru</a>\n"
    "2. F12 → Application → Cookies → vk.ru → <code>remixsid</code>\n"
    "3. Скопируй Value и пришли: <code>remixsid=...</code>\n"
    "4. /stop не нужен. Не присылай весь заголовок Cookie из Network."
)


ALREADY_CONNECTED_TEXT = (
    "Ты уже подключён. /settings, /pause, /resume или /stop.\n\n"
    "Если уведомления пропали — пришли свежий <code>remixsid=...</code> "
    "(F12 → Application → Cookies на vk.ru). /stop не нужен."
)
