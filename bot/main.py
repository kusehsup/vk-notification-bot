import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.handlers import reply as reply_handlers
from bot.handlers import settings as settings_handlers
from bot.handlers import start as start_handlers
from bot.handlers import token as token_handlers
from bot.handlers import vkid as vkid_handlers
from core.config import load_config
from core.manager import WorkerManager
from storage.crypto import TokenCipher
from storage.db import Database


async def main() -> None:
    config = load_config()
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    cipher = TokenCipher(config.fernet_key)
    db = Database(config.db_path, cipher)
    await db.init()

    bot = Bot(token=config.bot_token)
    manager = WorkerManager(
        bot,
        db,
        config.notifications_poll_interval,
        vkid_owner_tg_id=vkid_handlers.OWNER_TG_ID,
        vkid_poll_interval=config.vkid_poll_interval,
        flood_policy=config.flood_policy,
    )

    dp = Dispatcher()
    dp["db"] = db
    dp["manager"] = manager

    # Порядок: команды/FSM/callback'и раньше свободного текста, иначе токен-хендлер съест ввод VK ID setup
    dp.include_router(start_handlers.router)
    dp.include_router(vkid_handlers.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(reply_handlers.router)
    dp.include_router(token_handlers.router)

    await manager.start_all()
    logger.info("Bot started")

    try:
        await dp.start_polling(bot, db=db, manager=manager)
    finally:
        logger.info("Shutting down…")
        await manager.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
