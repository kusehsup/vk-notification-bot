"""OAuth-ссылки для пользовательского токена ВК.

Kate Mobile (2685278) с сентября 2026 заблокирован: oauth.vk.com отвечает
«Сервис заблокирован». Для messages + notifications + offline берём живые
Standalone-приложения с vkhost: VK Admin и официальный VK для Android.
"""
from __future__ import annotations

from urllib.parse import urlencode

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

VK_ADMIN_APP_ID = 6121396
VK_ANDROID_APP_ID = 2274003
KATE_MOBILE_APP_ID = 2685278

# Нужны ЛС, уведомления и постоянный ключ. Остальное — чтобы форматировать
# имена/группы и отвечать вложениями.
OAUTH_SCOPE = (
    "notify,friends,photos,video,docs,notes,pages,status,"
    "wall,groups,messages,notifications,offline"
)
OAUTH_API_VERSION = "5.199"
OAUTH_REDIRECT = "https://oauth.vk.com/blank.html"


def oauth_url(client_id: int) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "display": "page",
            "redirect_uri": OAUTH_REDIRECT,
            "scope": OAUTH_SCOPE,
            "response_type": "token",
            "v": OAUTH_API_VERSION,
            "revoke": 1,
        }
    )
    return f"https://oauth.vk.com/authorize?{query}"


def auth_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Войти через VK Admin", url=oauth_url(VK_ADMIN_APP_ID))],
            [InlineKeyboardButton(text="Запасной вариант: VK для Android", url=oauth_url(VK_ANDROID_APP_ID))],
        ]
    )


START_TEXT = (
    "👋 Привет! Я ретранслирую уведомления из ВКонтакте в Telegram.\n\n"
    "<b>Что я умею пересылать:</b>\n"
    "• Личные сообщения (мгновенно)\n"
    "• Лайки, комментарии, упоминания\n"
    "• Заявки в друзья, репосты, приглашения\n\n"
    "<b>Чтобы начать, нужен токен ВК.</b> Kate Mobile больше не работает "
    "(VK его заблокировал) — берём токен через <b>VK Admin</b>.\n\n"
    "1. Нажми кнопку <b>Войти через VK Admin</b>\n"
    "2. Разреши доступ (войди в аккаунт ВК, если попросит)\n"
    "3. Откроется почти пустая страница. В адресной строке будет длинная ссылка "
    "вида <code>https://oauth.vk.com/blank.html#access_token=...</code>\n"
    "4. Скопируй значение между <code>access_token=</code> и <code>&amp;</code> "
    "и пришли его мне следующим сообщением\n\n"
    "Если VK пишет «сервис заблокирован» — попробуй запасную кнопку "
    "<b>VK для Android</b>.\n\n"
    "⚠️ Токен даёт доступ к сообщениям и уведомлениям. "
    "Храню его зашифрованным и использую только для ретрансляции. "
    "Отозвать можно в настройках безопасности ВК.\n\n"
    "Команды:\n"
    "/settings — категории уведомлений\n"
    "/pause — пауза\n"
    "/resume — возобновить\n"
    "/stop — удалить аккаунт и токен\n"
    "/auth — снова показать кнопки входа"
)


REAUTH_TEXT = (
    "⚠️ <b>Нужен новый токен ВК</b>\n\n"
    "VK заблокировал Kate Mobile, старые токены больше не читают сообщения "
    "(ошибка Flood control / «Сервис заблокирован»).\n\n"
    "1. Нажми <b>Войти через VK Admin</b>\n"
    "2. Разреши доступ и скопируй <code>access_token=...</code> из адресной строки\n"
    "3. Пришли сюда <code>/stop</code>, затем токен следующим сообщением\n\n"
    "Если VK Admin тоже пишет «сервис заблокирован» — запасная кнопка "
    "<b>VK для Android</b>."
)
