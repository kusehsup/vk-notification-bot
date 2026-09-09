from dataclasses import dataclass, field


DEFAULT_SETTINGS: dict[str, bool] = {
    "messages": True,
    "likes": True,
    "comments": True,
    "mentions": True,
    "friends": True,
    "reposts": True,
    "invites": True,
    "wall_posts": False,
}

SETTING_LABELS: dict[str, str] = {
    "messages": "Личные сообщения",
    "likes": "Лайки",
    "comments": "Комментарии",
    "mentions": "Упоминания",
    "friends": "Заявки в друзья",
    "reposts": "Репосты",
    "invites": "Приглашения в сообщества/беседы",
    "wall_posts": "Новые записи друзей на стене",
}


@dataclass
class User:
    tg_id: int
    vk_token: str
    vk_user_id: int
    enabled: bool = True
    settings: dict[str, bool] = field(default_factory=lambda: DEFAULT_SETTINGS.copy())
    last_notification_ts: int = 0
