"""Хэндлер reply: когда юзер отвечает на пересланное ЛС, шлём текст/медиа в VK."""
from __future__ import annotations

import logging
import random
from typing import Optional

from aiogram import F, Router
from aiogram.types import Message, PhotoSize

from bot.sticker_converter import (
    convert_animated_sticker,
    convert_static_sticker,
    passthrough_video_sticker,
)
from core.manager import WorkerManager
from storage.db import Database
from vk.client import VKAPIError, VKClient
from vk.uploader import (
    UploadError,
    upload_document,
    upload_photo,
    upload_video,
    upload_voice,
)

logger = logging.getLogger(__name__)

router = Router()

TG_FILE_SIZE_LIMIT = 20 * 1024 * 1024  # bot API не качает >20 МБ


def _new_random_id() -> int:
    return random.randint(-(2**31), 2**31 - 1)


async def _download(message: Message, file_id: str) -> Optional[bytes]:
    bot = message.bot
    file = await bot.get_file(file_id)
    if file.file_size and file.file_size > TG_FILE_SIZE_LIMIT:
        return None
    buf = await bot.download_file(file.file_path)
    if buf is None:
        return None
    return buf.read()


def _largest_photo(photos: list[PhotoSize]) -> PhotoSize:
    return max(photos, key=lambda p: (p.width or 0) * (p.height or 0))


@router.message(F.reply_to_message)
async def on_reply(message: Message, db: Database, manager: WorkerManager) -> None:
    reply = message.reply_to_message
    if not reply:
        return
    target = await db.get_vk_target_for_message(message.chat.id, reply.message_id)
    if not target:
        return  # это reply не на пересланное ЛС — игнорим
    peer_id, vk_message_id = target

    user = await db.get_user(message.from_user.id)
    if not user or not user.enabled:
        await message.reply("⏸ Бот на паузе или аккаунт не подключён.")
        return

    client = manager.get_client(message.from_user.id)
    session = manager.get_session(message.from_user.id)
    if not client or not session:
        await message.reply("❌ Воркер VK не активен. /resume и повтори.")
        return

    try:
        await _dispatch(message, client, session, peer_id, vk_message_id)
    except UploadError as e:
        logger.warning("Upload failed: %s", e)
        await message.reply(f"❌ Не получилось загрузить вложение: {e}")
    except VKAPIError as e:
        logger.warning("VK send failed: %s", e)
        await message.reply(f"❌ VK отверг отправку: {e.message}")
    except Exception:
        logger.exception("Reply dispatch crashed")
        await message.reply("❌ Что-то сломалось при отправке. Подробности в логах.")


async def _send_with_attachment(
    client: VKClient,
    peer_id: int,
    text: str,
    attachment: str,
    reply_to: Optional[int] = None,
) -> None:
    await client.messages_send(
        peer_id=peer_id,
        message=text,
        attachment=attachment,
        random_id=_new_random_id(),
        reply_to=reply_to,
    )


async def _dispatch(
    message: Message,
    client: VKClient,
    session,
    peer_id: int,
    reply_to: Optional[int] = None,
) -> None:
    caption = (message.caption or "").strip()
    text = (message.text or "").strip()

    if message.photo:
        data = await _download(message, _largest_photo(message.photo).file_id)
        if data is None:
            await message.reply("❌ Файл слишком большой (>20 МБ).")
            return
        attachment = await upload_photo(client, session, peer_id, data)
        await _send_with_attachment(client, peer_id, caption, attachment, reply_to=reply_to)
        return

    if message.voice:
        data = await _download(message, message.voice.file_id)
        if data is None:
            await message.reply("❌ Файл слишком большой (>20 МБ).")
            return
        attachment = await upload_voice(client, session, peer_id, data)
        await _send_with_attachment(client, peer_id, caption, attachment, reply_to=reply_to)
        return

    if message.video or message.video_note:
        v = message.video or message.video_note
        data = await _download(message, v.file_id)
        if data is None:
            await message.reply("❌ Файл слишком большой (>20 МБ).")
            return
        ext = "mp4"
        ctype = "video/mp4"
        attachment = await upload_video(client, session, data, filename=f"video.{ext}", content_type=ctype)
        await _send_with_attachment(client, peer_id, caption, attachment, reply_to=reply_to)
        return

    if message.animation:  # GIF
        data = await _download(message, message.animation.file_id)
        if data is None:
            await message.reply("❌ Файл слишком большой (>20 МБ).")
            return
        attachment = await upload_document(
            client, session, peer_id, data,
            filename=message.animation.file_name or "animation.mp4",
            content_type=message.animation.mime_type or "video/mp4",
        )
        await _send_with_attachment(client, peer_id, caption, attachment, reply_to=reply_to)
        return

    if message.audio:
        data = await _download(message, message.audio.file_id)
        if data is None:
            await message.reply("❌ Файл слишком большой (>20 МБ).")
            return
        attachment = await upload_document(
            client, session, peer_id, data,
            filename=message.audio.file_name or "audio.mp3",
            content_type=message.audio.mime_type or "audio/mpeg",
            title=message.audio.title or "",
        )
        await _send_with_attachment(client, peer_id, caption, attachment, reply_to=reply_to)
        return

    if message.document:
        data = await _download(message, message.document.file_id)
        if data is None:
            await message.reply("❌ Файл слишком большой (>20 МБ).")
            return
        attachment = await upload_document(
            client, session, peer_id, data,
            filename=message.document.file_name or "file.bin",
            content_type=message.document.mime_type or "application/octet-stream",
        )
        await _send_with_attachment(client, peer_id, caption, attachment, reply_to=reply_to)
        return

    if message.sticker:
        await _handle_sticker(message, client, session, peer_id, reply_to=reply_to)
        return

    if text:
        await client.messages_send(
            peer_id=peer_id,
            message=text,
            random_id=_new_random_id(),
            reply_to=reply_to,
        )
        return

    await message.reply("❌ Этот тип сообщения пока не поддерживается.")


async def _handle_sticker(
    message: Message,
    client: VKClient,
    session,
    peer_id: int,
    reply_to: Optional[int] = None,
) -> None:
    sticker = message.sticker
    emoji = sticker.emoji or ""
    data = await _download(message, sticker.file_id)
    if data is None:
        await message.reply("❌ Стикер слишком большой.")
        return

    converted = None
    if sticker.is_animated:
        # tgs
        converted = await convert_animated_sticker(data)
        if converted is None:
            # fallback: текстом
            fallback = f"🌟 {emoji}".strip() or "🌟"
            await client.messages_send(
                peer_id=peer_id,
                message=fallback,
                random_id=_new_random_id(),
                reply_to=reply_to,
            )
            return
    elif sticker.is_video:
        # webm
        converted = await passthrough_video_sticker(data)
    else:
        # webp
        converted = await convert_static_sticker(data)

    if converted.kind == "photo":
        attachment = await upload_photo(
            client, session, peer_id, converted.data,
            filename=converted.filename, content_type=converted.content_type,
        )
    else:
        attachment = await upload_document(
            client, session, peer_id, converted.data,
            filename=converted.filename, content_type=converted.content_type,
        )
    await _send_with_attachment(client, peer_id, "", attachment, reply_to=reply_to)
