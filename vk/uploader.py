"""Загрузка медиа в VK для отправки в ЛС.

Все методы возвращают строку attachment вида `photo{owner}_{id}` /
`doc{owner}_{id}` / `video{owner}_{id}`, готовую к передаче в messages.send.
"""
from __future__ import annotations

import json
import logging

import aiohttp

from vk.client import VKAPIError, VKClient

logger = logging.getLogger(__name__)


class UploadError(Exception):
    pass


async def _upload_file(
    session: aiohttp.ClientSession,
    upload_url: str,
    field_name: str,
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> dict:
    form = aiohttp.FormData()
    form.add_field(field_name, file_bytes, filename=filename, content_type=content_type)
    async with session.post(upload_url, data=form, timeout=aiohttp.ClientTimeout(total=120)) as resp:
        text = await resp.text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise UploadError(f"Upload server returned non-JSON: {text[:200]}") from e
    return data


async def upload_photo(
    client: VKClient,
    session: aiohttp.ClientSession,
    peer_id: int,
    file_bytes: bytes,
    filename: str = "photo.jpg",
    content_type: str = "image/jpeg",
) -> str:
    server_info = await client.photos_get_messages_upload_server(peer_id)
    upload_url = server_info["upload_url"]

    uploaded = await _upload_file(session, upload_url, "photo", file_bytes, filename, content_type)
    if not uploaded.get("photo") or uploaded.get("photo") == "[]":
        raise UploadError(f"Empty photo upload response: {uploaded}")

    saved = await client.photos_save_messages_photo(
        photo=uploaded["photo"],
        server=uploaded["server"],
        hash_=uploaded["hash"],
    )
    if not saved:
        raise UploadError("photos.saveMessagesPhoto returned empty")
    item = saved[0]
    return f"photo{item['owner_id']}_{item['id']}"


async def _upload_doc_generic(
    client: VKClient,
    session: aiohttp.ClientSession,
    peer_id: int,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    doc_type: str,  # "doc" / "audio_message" / "graffiti"
    title: str = "",
) -> tuple[str, str]:
    server_info = await client.docs_get_messages_upload_server(peer_id, doc_type)
    upload_url = server_info["upload_url"]
    uploaded = await _upload_file(session, upload_url, "file", file_bytes, filename, content_type)
    if not uploaded.get("file"):
        raise UploadError(f"Empty doc upload response: {uploaded}")

    saved = await client.docs_save(file=uploaded["file"], title=title or filename)
    # docs.save возвращает {type: 'doc'|'audio_message'|..., doc: {...} | audio_message: {...}}
    if isinstance(saved, dict):
        kind = saved.get("type", "doc")
        item = saved.get(kind) or saved.get("doc") or {}
    else:
        raise UploadError(f"Unexpected docs.save response: {saved}")
    if not item.get("id"):
        raise UploadError(f"docs.save: missing id in {saved}")
    return kind, f"doc{item['owner_id']}_{item['id']}"


async def upload_voice(
    client: VKClient,
    session: aiohttp.ClientSession,
    peer_id: int,
    file_bytes: bytes,
    filename: str = "voice.ogg",
) -> str:
    _, attachment = await _upload_doc_generic(
        client, session, peer_id, file_bytes, filename, "audio/ogg",
        doc_type="audio_message",
    )
    return attachment


async def upload_document(
    client: VKClient,
    session: aiohttp.ClientSession,
    peer_id: int,
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    title: str = "",
) -> str:
    _, attachment = await _upload_doc_generic(
        client, session, peer_id, file_bytes, filename, content_type,
        doc_type="doc", title=title,
    )
    return attachment


async def upload_video(
    client: VKClient,
    session: aiohttp.ClientSession,
    file_bytes: bytes,
    filename: str = "video.mp4",
    content_type: str = "video/mp4",
    name: str = "",
) -> str:
    try:
        info = await client.video_save(name=name)
    except VKAPIError as e:
        raise UploadError(f"video.save failed: {e}") from e

    upload_url = info["upload_url"]
    uploaded = await _upload_file(session, upload_url, "video_file", file_bytes, filename, content_type)
    # uploaded содержит size/video_id, но id/owner_id берём из video.save
    return f"video{info['owner_id']}_{info['video_id']}"
