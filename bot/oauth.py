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
    "Cookie remixsid с сайта <b>нельзя</b> использовать с сервера бота: VK привязывает "
    "их к твоему IP.\n\n"
    "Нужен токен из заголовка Authorization:\n"
    "1. Открой <a href=\"https://vk.ru\">vk.ru</a>, F12 → Network, обнови ленту\n"
    "2. Найди запрос <code>api.vk.ru/method/batch.call</code> "
    "(client_id=6287487)\n"
    "3. Скопируй <code>Authorization: Bearer vk1.a....</code> и пришли мне\n\n"
    "Не присылай один Cookie — бот его отклонит.\n\n"
    "⚠️ Токен даёт доступ к сообщениям. Храню зашифрованным, сообщение удаляю. "
    "Отключить: /stop.\n\n"
    "Команды:\n"
    "/settings — категории уведомлений\n"
    "/pause — пауза\n"
    "/resume — возобновить\n"
    "/stop — удалить аккаунт и сессию\n"
    "/auth — снова показать инструкцию"
)


REAUTH_TEXT = (
    "⚠️ <b>Нужен токен сайта ВК</b>\n\n"
    "Cookie с твоего IP бот использовать не может.\n"
    "F12 → Network → <code>api.vk.ru/method/batch.call</code> → "
    "<code>Authorization: Bearer vk1.a....</code> — пришли эту строку. /stop не нужен."
)


ALREADY_CONNECTED_TEXT = (
    "Ты уже подключён. /settings, /pause, /resume или /stop.\n\n"
    "Если уведомления пропали — пришли свежий <code>Authorization: Bearer vk1.a....</code> "
    "из Network на batch.call. /stop не нужен."
)
