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
            [InlineKeyboardButton(text="Открыть vk.ru", url=VK_SITE)],
        ]
    )


START_TEXT = (
    "👋 Привет! Я ретранслирую уведомления из ВКонтакте в Telegram.\n\n"
    "<b>Что я умею пересылать:</b>\n"
    "• Личные сообщения (мгновенно)\n"
    "• Лайки, комментарии, упоминания\n"
    "• Заявки в друзья, репосты, приглашения\n\n"
    "<b>Как подключить аккаунт</b>\n"
    "Нужен <b>полный</b> заголовок Cookie с vk.ru (не одна remixsid — VK её одной не принимает).\n\n"
    "1. Открой <a href=\"https://vk.ru\">vk.ru</a> и войди\n"
    "2. F12 → <b>Network</b> → обнови страницу → кликни запрос <code>/feed</code>\n"
    "3. Request Headers → <code>Cookie</code> → Copy value\n"
    "4. Сохрани в <code>cookies.txt</code> и пришли <b>файлом</b>\n\n"
    "Внутри должны быть <code>remixsid</code> и <code>remixwsid</code>. "
    "Не копируй <code>document.cookie</code> из консоли.\n\n"
    "⚠️ Это полный вход в аккаунт. Храню зашифрованным, файл/сообщение сразу удаляю. "
    "Отключить: /stop, плюс «Выйти на всех устройствах» в настройках VK.\n\n"
    "Команды:\n"
    "/settings — категории уведомлений\n"
    "/pause — пауза\n"
    "/resume — возобновить\n"
    "/stop — удалить аккаунт и сессию\n"
    "/auth — снова показать инструкцию"
)


REAUTH_TEXT = (
    "⚠️ <b>Нужна сессия vk.ru</b>\n\n"
    "Одного remixsid мало. Пришли <b>файлом</b> полный Cookie с vk.ru/feed "
    "(F12 → Network → Cookie), внутри должны быть remixsid и remixwsid. /stop не нужен."
)


ALREADY_CONNECTED_TEXT = (
    "Ты уже подключён. /settings, /pause, /resume или /stop.\n\n"
    "Если уведомления пропали — пришли <code>cookies.txt</code> с полным Cookie "
    "с vk.ru/feed. /stop не нужен."
)
