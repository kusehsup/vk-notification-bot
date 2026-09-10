"""Тексты подключения: сессия vk.com вместо мёртвого OAuth.

Kate Mobile, VK Admin и официальный Android-клиент больше не отдают
messages через oauth.vk.com (blocked / direct auth only).
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

VK_SITE = "https://vk.ru"
# Публичный IPv4 сервера, с которого бот ходит в VK (WireGuard NAT на этот же адрес).
BOT_PUBLIC_IP = "5.129.227.157"


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
    "Включи WireGuard VPN сервера бота, проверь что IP "
    f"<code>{BOT_PUBLIC_IP}</code>, зайди на vk.ru заново и пришли свежий Bearer. "
    "Старый токен больше не присылай.\n\n"
    "Подробности: /vpn"
)


VPN_OWNER_TEXT = (
    "🔌 <b>Как выписать токен на IP бота</b>\n\n"
    f"Бот снова на нидерландском сервере и ходит в ВК с <code>{BOT_PUBLIC_IP}</code>. "
    "Клиенты WireGuard выходят в интернет с того же адреса.\n\n"
    "1. Включи уже существующий WireGuard этого сервера "
    "(полный туннель, не split: трафик vk.ru тоже через VPN).\n\n"
    "2. Проверь IP: <a href=\"https://ifconfig.me\">ifconfig.me</a> должен показать "
    f"<code>{BOT_PUBLIC_IP}</code>. Если другой — ВК снова привяжет токен не туда.\n\n"
    "3. Через VPN открой <a href=\"https://vk.ru\">vk.ru</a>, "
    "<b>выйди и зайди снова</b>.\n\n"
    "4. F12 → Network → <code>api.vk.ru/method/batch.call</code> "
    "(client_id=6287487) → "
    "<code>Authorization: Bearer vk1.a....</code> — пришли строку боту.\n\n"
    "5. VPN после этого можно выключить: токен уже привязан к IP сервера.\n\n"
    "Не используй Bearer, снятый без VPN."
)


START_TEXT = (
    "👋 Привет! Я ретранслирую уведомления из ВКонтакте в Telegram.\n\n"
    "<b>Что я умею пересылать:</b>\n"
    "• Личные сообщения (мгновенно)\n"
    "• Лайки, комментарии, упоминания\n"
    "• Заявки в друзья, репосты, приглашения\n\n"
    "<b>Как подключить аккаунт</b>\n"
    "Токен сайта ВК привязан к <b>IP браузера</b>. С домашнего Wi‑Fi бот его "
    "не примет: <i>access_token was given to another ip address</i>.\n\n"
    "Зайди на vk.ru через WireGuard VPN сервера бота и скопируй токен уже оттуда:\n"
    "1. Включи VPN (если сервер твой — /vpn). IP должен быть "
    f"<code>{BOT_PUBLIC_IP}</code>\n"
    "2. Открой <a href=\"https://vk.ru\">vk.ru</a> и войди заново\n"
    "3. F12 → Network → <code>api.vk.ru/method/batch.call</code> "
    "(client_id=6287487)\n"
    "4. Пришли <code>Authorization: Bearer vk1.a....</code>\n"
    "5. VPN можно выключить\n\n"
    "Один Cookie без VPN бот отклонит.\n\n"
    "⚠️ Токен даёт доступ к сообщениям. Храню зашифрованным, сообщение удаляю. "
    "Отключить: /stop.\n\n"
    "Команды:\n"
    "/settings — категории уведомлений\n"
    "/pause — пауза\n"
    "/resume — возобновить\n"
    "/stop — удалить аккаунт и сессию\n"
    "/auth — снова показать инструкцию\n"
    "/vpn — как зайти в ВК через VPN сервера"
)


REAUTH_TEXT = (
    "⚠️ <b>Нужен свежий токен сайта ВК с IP бота</b>\n\n"
    "Снимать Bearer дома бесполезно — он привязан к твоему IP. "
    "Включи WireGuard сервера (/vpn), зайди на vk.ru и скопируй "
    "<code>Authorization: Bearer vk1.a....</code> из "
    "<code>api.vk.ru/method/batch.call</code>. /stop не нужен."
)


ALREADY_CONNECTED_TEXT = (
    "Ты уже подключён. /settings, /pause, /resume или /stop.\n\n"
    "Если уведомления пропали — нужен свежий Bearer, выписанный "
    "<b>через WireGuard на IP бота</b> (/vpn), из Network на batch.call. "
    "/stop не нужен."
)
