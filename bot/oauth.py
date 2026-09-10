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


IP_BOUND_TEXT = (
    "❌ Этот токен ВК выписан <b>другому IP</b>, не серверу бота.\n\n"
    "Сайт vk.ru привязывает <code>Authorization: Bearer</code> (и Cookie) к IP браузера. "
    "Скопированный дома токен с сервера не заработает — тот же ответ: "
    "<i>access_token was given to another ip address</i>.\n\n"
    "Нужно зайти на vk.ru <b>через SOCKS5 на IP сервера бота</b>, войти в аккаунт "
    "заново и скопировать свежий Bearer уже оттуда. Старый токен больше не присылай.\n\n"
    "Если это твой сервер — команда /socks (SSH-туннель). "
    "После отправки токена прокси можно выключить."
)


SOCKS_OWNER_TEXT = (
    "🔌 <b>Как выписать токен на IP бота</b>\n\n"
    "Бот ходит в ВК с <code>195.133.25.66</code>. Браузер должен открыть vk.ru "
    "с того же адреса.\n\n"
    "1. На своём компьютере оставь окно открытым:\n"
    "<code>ssh -D 1080 -N root@195.133.25.66</code>\n\n"
    "2. Firefox: Настройки → Параметры сети → Ручная настройка прокси\n"
    "SOCKS Host <code>127.0.0.1</code>, порт <code>1080</code>, SOCKS v5, "
    "включи «Прокси DNS при использовании SOCKS v5».\n"
    "Chrome: <code>google-chrome --proxy-server=socks5://127.0.0.1:1080</code>\n\n"
    "3. Через этот прокси открой <a href=\"https://vk.ru\">vk.ru</a>, "
    "<b>выйди и зайди снова</b> (старая сессия привязана к домашнему IP).\n\n"
    "4. F12 → Network → запрос <code>api.vk.ru/method/batch.call</code> "
    "(client_id=6287487) → заголовок "
    "<code>Authorization: Bearer vk1.a....</code> — пришли эту строку боту.\n\n"
    "5. Прокси и SSH можно закрыть: токен уже привязан к IP сервера.\n\n"
    "Не используй Bearer, снятый без прокси — ВК его отвергнет."
)


START_TEXT = (
    "👋 Привет! Я ретранслирую уведомления из ВКонтакте в Telegram.\n\n"
    "<b>Что я умею пересылать:</b>\n"
    "• Личные сообщения (мгновенно)\n"
    "• Лайки, комментарии, упоминания\n"
    "• Заявки в друзья, репосты, приглашения\n\n"
    "<b>Как подключить аккаунт</b>\n"
    "Токен и Cookie сайта ВК привязаны к <b>IP браузера</b>. Если скопировать "
    "Bearer дома, а бот крутится на сервере — ВК ответит "
    "<i>access_token was given to another ip address</i>.\n\n"
    "Поэтому vk.ru нужно открыть через SOCKS5 на IP сервера бота, войти заново "
    "и только потом копировать токен:\n"
    "1. Включи SOCKS5 на IP бота (если сервер твой — /socks)\n"
    "2. Открой <a href=\"https://vk.ru\">vk.ru</a> через прокси и войди в аккаунт\n"
    "3. F12 → Network → <code>api.vk.ru/method/batch.call</code> "
    "(client_id=6287487)\n"
    "4. Пришли <code>Authorization: Bearer vk1.a....</code>\n"
    "5. Прокси можно выключить\n\n"
    "Один Cookie без прокси бот отклонит.\n\n"
    "⚠️ Токен даёт доступ к сообщениям. Храню зашифрованным, сообщение удаляю. "
    "Отключить: /stop.\n\n"
    "Команды:\n"
    "/settings — категории уведомлений\n"
    "/pause — пауза\n"
    "/resume — возобновить\n"
    "/stop — удалить аккаунт и сессию\n"
    "/auth — снова показать инструкцию\n"
    "/socks — SOCKS через IP бота (если это твой сервер)"
)


REAUTH_TEXT = (
    "⚠️ <b>Нужен свежий токен сайта ВК с IP бота</b>\n\n"
    "Снимать Bearer дома бесполезно — он привязан к твоему IP. "
    "Зайди на vk.ru через SOCKS на сервер бота (/socks), скопируй "
    "<code>Authorization: Bearer vk1.a....</code> из "
    "<code>api.vk.ru/method/batch.call</code>. /stop не нужен."
)


ALREADY_CONNECTED_TEXT = (
    "Ты уже подключён. /settings, /pause, /resume или /stop.\n\n"
    "Если уведомления пропали — нужен свежий Bearer, выписанный "
    "<b>через SOCKS на IP бота</b> (/socks), из Network на batch.call. "
    "/stop не нужен."
)
