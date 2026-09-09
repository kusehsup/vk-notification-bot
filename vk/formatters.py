from html import escape
from typing import Any


def _vk_user_link(user_id: int, name: str) -> str:
    return f'<a href="https://vk.com/id{user_id}">{escape(name)}</a>'


def _vk_group_link(group_id: int, name: str) -> str:
    return f'<a href="https://vk.com/club{abs(group_id)}">{escape(name)}</a>'


def _resolve_actor(actor_id: int, profiles: dict[int, dict], groups: dict[int, dict]) -> str:
    if actor_id > 0:
        prof = profiles.get(actor_id)
        if prof:
            name = f"{prof.get('first_name', '')} {prof.get('last_name', '')}".strip()
            return _vk_user_link(actor_id, name or f"id{actor_id}")
        return _vk_user_link(actor_id, f"id{actor_id}")
    gid = -actor_id
    grp = groups.get(gid)
    if grp:
        return _vk_group_link(gid, grp.get("name", f"club{gid}"))
    return _vk_group_link(gid, f"club{gid}")


def format_longpoll_message(
    peer_id: int,
    text: str,
    extras: dict[str, Any] | None = None,
    chat_title: str | None = None,
) -> str:
    """Форматирует входящее ЛС из сырого Long Poll, без messages.getById.

    Нужен как fallback, когда VK отвечает Flood control и API-обогащение недоступно.
    """
    extras = extras or {}
    from_raw = extras.get("from") or extras.get("from_id")
    try:
        from_id = int(from_raw) if from_raw else (peer_id if peer_id < 2_000_000_000 else 0)
    except (TypeError, ValueError):
        from_id = peer_id if peer_id < 2_000_000_000 else 0

    sender_name = extras.get("source_name") or (f"id{from_id}" if from_id else "сообщение")
    sender = _vk_user_link(from_id, str(sender_name)) if from_id > 0 else escape(str(sender_name))

    is_chat = peer_id > 2_000_000_000
    if is_chat:
        title = escape(chat_title) if chat_title else "беседе"
        chat_url = f"https://vk.com/im?sel=c{peer_id - 2_000_000_000}"
        header = f'💬 <b>{sender}</b> в <a href="{chat_url}">«{title}»</a>:'
    else:
        header = f"💬 <b>{sender}</b>:"

    parts: list[str] = [header]
    if text:
        parts.append(escape(text))

    attach_lines = _format_longpoll_attachments(extras)
    if attach_lines:
        parts.append("\n".join(attach_lines))
    if extras.get("fwd") or extras.get("fwd_count"):
        parts.append("📎 <i>есть пересланные сообщения</i>")
    if extras.get("reply") or extras.get("reply_id"):
        parts.append("↩️ <i>ответ на сообщение</i>")
    return "\n".join(parts)


def _format_longpoll_attachments(extras: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for i in range(1, 11):
        kind = extras.get(f"attach{i}_type") or extras.get(f"attach{i}_kind")
        if not kind:
            continue
        kind = str(kind)
        if kind == "photo":
            lines.append("🖼 фото")
        elif kind == "video":
            lines.append("🎬 видео")
        elif kind == "audio":
            lines.append("🎵 аудио")
        elif kind in ("audio_message", "doc_voice"):
            lines.append("🎙 голосовое сообщение")
        elif kind == "doc":
            lines.append("📄 документ")
        elif kind == "sticker":
            lines.append("🌟 стикер")
        elif kind == "link":
            url = extras.get(f"attach{i}_url") or extras.get(f"attach{i}")
            if url:
                lines.append(f'🔗 <a href="{escape(str(url))}">{escape(str(url))}</a>')
            else:
                lines.append("🔗 ссылка")
        elif kind == "wall":
            lines.append("📰 запись со стены")
        elif kind == "gift":
            lines.append("🎁 подарок")
        else:
            lines.append(f"📎 {escape(kind)}")
    return lines


def format_message_event(
    message: dict[str, Any],
    profiles: dict[int, dict],
    groups: dict[int, dict],
    chat_title: str | None = None,
) -> str:
    """Форматирует входящее ЛС из messages.getById."""
    from_id = message.get("from_id", 0)
    peer_id = message.get("peer_id", 0)
    text = message.get("text", "") or ""
    attachments = message.get("attachments", []) or []
    fwd = message.get("fwd_messages", []) or []
    reply = message.get("reply_message")

    sender = _resolve_actor(from_id, profiles, groups)

    is_chat = peer_id > 2000000000
    if is_chat:
        title = escape(chat_title) if chat_title else "беседе"
        chat_url = f"https://vk.com/im?sel=c{peer_id - 2000000000}"
        header = f'💬 <b>{sender}</b> в <a href="{chat_url}">«{title}»</a>:'
    else:
        header = f"💬 <b>{sender}</b>:"

    parts: list[str] = [header]
    if text:
        parts.append(escape(text))

    attach_lines = _format_attachments(attachments)
    if attach_lines:
        parts.append("\n".join(attach_lines))

    if reply:
        parts.append("↩️ <i>ответ на сообщение</i>")
    if fwd:
        parts.append(f"📎 <i>пересланных сообщений: {len(fwd)}</i>")

    return "\n".join(parts)


def _format_attachments(attachments: list[dict]) -> list[str]:
    lines: list[str] = []
    for att in attachments:
        kind = att.get("type", "")
        if kind == "photo":
            lines.append("🖼 фото")
        elif kind == "video":
            v = att.get("video", {})
            title = v.get("title", "видео")
            lines.append(f"🎬 видео: {escape(title)}")
        elif kind == "audio":
            a = att.get("audio", {})
            artist = a.get("artist", "")
            title = a.get("title", "")
            lines.append(f"🎵 {escape(artist)} — {escape(title)}".strip())
        elif kind == "audio_message":
            lines.append("🎙 голосовое сообщение")
        elif kind == "doc":
            d = att.get("doc", {})
            title = d.get("title", "документ")
            lines.append(f"📄 {escape(title)}")
        elif kind == "sticker":
            lines.append("🌟 стикер")
        elif kind == "link":
            lk = att.get("link", {})
            url = lk.get("url", "")
            title = lk.get("title", url)
            if url:
                lines.append(f'🔗 <a href="{escape(url)}">{escape(title)}</a>')
        elif kind == "wall":
            lines.append("📰 запись со стены")
        elif kind == "gift":
            lines.append("🎁 подарок")
        else:
            lines.append(f"📎 {escape(kind)}")
    return lines


NOTIFICATION_ICONS = {
    "follow": "👤",
    "friend_accepted": "✅",
    "mention": "📣",
    "mention_comments": "📣",
    "mention_comment_photo": "📣",
    "mention_comment_video": "📣",
    "wall": "📝",
    "wall_publish": "📝",
    "comment_post": "💭",
    "comment_photo": "💭",
    "comment_video": "💭",
    "reply_comment": "↩️",
    "reply_comment_photo": "↩️",
    "reply_comment_video": "↩️",
    "reply_topic": "↩️",
    "like_post": "❤️",
    "like_comment": "❤️",
    "like_photo": "❤️",
    "like_video": "❤️",
    "like_comment_photo": "❤️",
    "like_comment_video": "❤️",
    "like_comment_topic": "❤️",
    "copy_post": "🔁",
    "copy_photo": "🔁",
    "copy_video": "🔁",
    "invite_app": "📨",
    "invite_group": "📨",
    "invite_chat": "📨",
}


NOTIFICATION_CATEGORIES = {
    "follow": "friends",
    "friend_accepted": "friends",
    "mention": "mentions",
    "mention_comments": "mentions",
    "mention_comment_photo": "mentions",
    "mention_comment_video": "mentions",
    "wall": "wall_posts",
    "wall_publish": "wall_posts",
    "comment_post": "comments",
    "comment_photo": "comments",
    "comment_video": "comments",
    "reply_comment": "comments",
    "reply_comment_photo": "comments",
    "reply_comment_video": "comments",
    "reply_topic": "comments",
    "like_post": "likes",
    "like_comment": "likes",
    "like_photo": "likes",
    "like_video": "likes",
    "like_comment_photo": "likes",
    "like_comment_video": "likes",
    "like_comment_topic": "likes",
    "copy_post": "reposts",
    "copy_photo": "reposts",
    "copy_video": "reposts",
    "invite_app": "invites",
    "invite_group": "invites",
    "invite_chat": "invites",
}


NOTIFICATION_VERBS = {
    "follow": "подписался на вас",
    "friend_accepted": "принял заявку в друзья",
    "mention": "упомянул вас в записи",
    "mention_comments": "упомянул вас в комментарии",
    "mention_comment_photo": "упомянул вас в комментарии к фото",
    "mention_comment_video": "упомянул вас в комментарии к видео",
    "wall": "оставил запись на вашей стене",
    "wall_publish": "опубликовал предложенную запись",
    "comment_post": "прокомментировал вашу запись",
    "comment_photo": "прокомментировал ваше фото",
    "comment_video": "прокомментировал ваше видео",
    "reply_comment": "ответил на ваш комментарий",
    "reply_comment_photo": "ответил на ваш комментарий к фото",
    "reply_comment_video": "ответил на ваш комментарий к видео",
    "reply_topic": "ответил в обсуждении",
    "like_post": "оценил вашу запись",
    "like_comment": "оценил ваш комментарий",
    "like_photo": "оценил ваше фото",
    "like_video": "оценил ваше видео",
    "like_comment_photo": "оценил ваш комментарий к фото",
    "like_comment_video": "оценил ваш комментарий к видео",
    "like_comment_topic": "оценил ваш комментарий в обсуждении",
    "copy_post": "поделился вашей записью",
    "copy_photo": "поделился вашим фото",
    "copy_video": "поделился вашим видео",
    "invite_app": "приглашает в приложение",
    "invite_group": "приглашает в сообщество",
    "invite_chat": "приглашает в беседу",
}


def notification_category(ntype: str) -> str:
    return NOTIFICATION_CATEGORIES.get(ntype, "")


def format_notification(
    notification: dict[str, Any],
    profiles: dict[int, dict],
    groups: dict[int, dict],
) -> str:
    ntype = notification.get("type", "")
    icon = NOTIFICATION_ICONS.get(ntype, "🔔")
    verb = NOTIFICATION_VERBS.get(ntype, ntype)

    feedback = notification.get("feedback") or {}
    parent = notification.get("parent") or {}

    actors: list[int] = []
    if isinstance(feedback, dict):
        if "from_id" in feedback:
            actors.append(feedback["from_id"])
        for item in feedback.get("items", []) or []:
            if isinstance(item, dict) and "from_id" in item:
                actors.append(item["from_id"])

    if not actors:
        return f"{icon} {verb}"

    unique_actors = list(dict.fromkeys(actors))
    actor_strs = [_resolve_actor(a, profiles, groups) for a in unique_actors[:3]]
    actors_text = ", ".join(actor_strs)
    if len(unique_actors) > 3:
        actors_text += f" и ещё {len(unique_actors) - 3}"

    lines = [f"{icon} <b>{actors_text}</b> {verb}"]

    text_snippet = ""
    if isinstance(feedback, dict):
        text_snippet = feedback.get("text", "") or ""
    if not text_snippet and isinstance(parent, dict):
        text_snippet = parent.get("text", "") or ""
    if text_snippet:
        snippet = text_snippet[:300]
        lines.append(f"<i>{escape(snippet)}</i>")

    return "\n".join(lines)
