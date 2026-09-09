from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from storage.db import Database

router = Router()


START_TEXT = (
    "👋 Привет! Я ретранслирую уведомления из ВКонтакте в Telegram.\n\n"
    "<b>Что я умею пересылать:</b>\n"
    "• Личные сообщения (мгновенно)\n"
    "• Лайки, комментарии, упоминания\n"
    "• Заявки в друзья, репосты, приглашения\n\n"
    "<b>Чтобы начать, нужен токен ВК.</b>\n"
    "Получить его можно так:\n"
    "1. Открой <a href=\"https://vkhost.github.io/\">vkhost.github.io</a>\n"
    "2. Выбери <b>Kate Mobile</b> и войди в свой аккаунт\n"
    "3. После авторизации тебя перебросит на страницу с длинной ссылкой в адресной строке. "
    "Скопируй из неё значение <code>access_token=...</code> (между <code>access_token=</code> и <code>&amp;</code>)\n"
    "4. Пришли этот токен мне следующим сообщением\n\n"
    "⚠️ <b>Важно:</b> токен даёт полный доступ к твоему аккаунту ВК. "
    "Я храню его в зашифрованном виде и использую только для получения уведомлений. "
    "Если что — можешь отозвать токен в настройках безопасности ВК.\n\n"
    "Команды:\n"
    "/settings — настройка категорий уведомлений\n"
    "/pause — поставить на паузу\n"
    "/resume — возобновить\n"
    "/stop — удалить аккаунт и токен из бота"
)


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    user = await db.get_user(message.from_user.id)
    if user:
        await message.answer(
            "Ты уже подключён. Используй /settings, /pause, /resume или /stop.",
            parse_mode=ParseMode.HTML,
        )
        return
    await message.answer(START_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(START_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
