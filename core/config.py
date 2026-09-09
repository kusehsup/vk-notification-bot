import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from vk.rate_limit import FloodPolicy

# Позволяем переопределить путь: ENV_FILE=.env.dev python -m bot.main
_env_file = os.getenv("ENV_FILE", ".env")
load_dotenv(_env_file)


@dataclass(frozen=True)
class Config:
    bot_token: str
    fernet_key: str
    db_path: Path
    notifications_poll_interval: int
    vkid_poll_interval: int
    log_level: str
    flood_policy: FloodPolicy


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    fernet_key = os.getenv("FERNET_KEY", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN не задан в .env")
    if not fernet_key:
        raise RuntimeError("FERNET_KEY не задан в .env")

    db_path = Path(os.getenv("DB_PATH", "data/bot.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        bot_token=bot_token,
        fernet_key=fernet_key,
        db_path=db_path,
        notifications_poll_interval=int(os.getenv("NOTIFICATIONS_POLL_INTERVAL", "90")),
        vkid_poll_interval=int(os.getenv("VKID_POLL_INTERVAL", "60")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        flood_policy=FloodPolicy(
            min_interval=float(os.getenv("VK_API_MIN_INTERVAL", "0.7")),
            flood_initial=float(os.getenv("VK_FLOOD_COOLDOWN", "900")),
            global_trip_seconds=float(os.getenv("VK_GLOBAL_FLOOD_COOLDOWN", "1800")),
            startup_cooldown=float(os.getenv("VK_STARTUP_COOLDOWN", "0")),
        ),
    )
