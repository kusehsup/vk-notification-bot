"""Тексты подключения: сессия vk.com вместо мёртвого OAuth.

Kate Mobile, VK Admin и официальный Android-клиент больше не отдают
messages через oauth.vk.com (blocked / direct auth only).
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

VK_SITE = "https://vk.com"


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
    "VK закрыл вход через Kate Mobile, VK Admin и приложение для Android. "
    "Нужна сессия с сайта vk.com — тот же Cookie, с которым открыт ВК в браузере.\n\n"
    "1. Открой <a href=\"https://vk.com\">vk.com</a> и войди в аккаунт\n"
    "2. Нажми F12 → вкладка <b>Network</b> (Сеть) → обнови страницу (F5)\n"
    "3. Кликни любой запрос к vk.com\n"
    "4. В <b>Request Headers</b> найди <code>Cookie</code> и скопируй значение целиком "
    "(должна быть строка с <code>remixsid=</code>)\n"
    "5. Пришли её мне следующим сообщением. Если Telegram ругается на длину — "
    "сохрани в <code>cookies.txt</code> и пришли <b>файлом</b>.\n\n"
    "Не копируй <code>document.cookie</code> из консоли: там нет HttpOnly "
    "<code>remixsid</code>, без него вход не сработает.\n\n"
    "⚠️ Cookie — полный вход в аккаунт. Храню зашифрованным, сообщение сразу удаляю, "
    "использую только чтобы читать уведомления. Отключить: /stop, плюс "
    "«Выйти на всех устройствах» в настройках VK.\n\n"
    "Команды:\n"
    "/settings — категории уведомлений\n"
    "/pause — пауза\n"
    "/resume — возобновить\n"
    "/stop — удалить аккаунт и сессию\n"
    "/auth — снова показать инструкцию"
)


REAUTH_TEXT = (
    "⚠️ <b>Нужна новая сессия vk.com</b>\n\n"
    "Kate Mobile, VK Admin и официальный Android больше не отдают доступ к сообщениям "
    "(«application is blocked» / «Unavailable for apps with direct auth»).\n\n"
    "1. Открой <a href=\"https://vk.com\">vk.com</a> в браузере\n"
    "2. F12 → Network → обнови страницу\n"
    "3. Скопируй заголовок <code>Cookie</code> (внутри должен быть <code>remixsid=</code>)\n"
    "4. Пришли его сюда — <b>/stop не нужен</b>. Если не влезает, пришли .txt файлом.\n\n"
    "Сообщение с cookie сразу удалю."
)


ALREADY_CONNECTED_TEXT = (
    "Ты уже подключён. /settings, /pause, /resume или /stop.\n\n"
    "Если уведомления пропали — пришли свежий <code>Cookie</code> с "
    "<a href=\"https://vk.com\">vk.com</a> (F12 → Network). /stop для смены сессии не нужен."
)
