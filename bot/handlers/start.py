from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.oauth import ALREADY_CONNECTED_TEXT, START_TEXT, auth_keyboard
from storage.db import Database

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    user = await db.get_user(message.from_user.id)
    if user:
        await message.answer(
            ALREADY_CONNECTED_TEXT,
            reply_markup=auth_keyboard(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return
    await message.answer(
        START_TEXT,
        reply_markup=auth_keyboard(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        START_TEXT,
        reply_markup=auth_keyboard(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.message(Command("auth"))
async def cmd_auth(message: Message) -> None:
    await message.answer(
        START_TEXT,
        reply_markup=auth_keyboard(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
