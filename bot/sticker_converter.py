"""Конвертация Telegram-стикеров в форматы, понятные VK.

- static (.webp) → PNG (через Pillow)
- animated (.tgs) → GIF (через python-lottie + cairosvg + ffmpeg) — может упасть, тогда None
- video (.webm) → проксируется как есть, VK принимает как документ
"""
from __future__ import annotations

import asyncio
import io
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ConvertedSticker:
    data: bytes
    filename: str
    content_type: str
    kind: str  # "photo" | "doc"


def _convert_webp_to_png(webp_bytes: bytes) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(webp_bytes))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def convert_static_sticker(webp_bytes: bytes) -> ConvertedSticker:
    png = await asyncio.to_thread(_convert_webp_to_png, webp_bytes)
    return ConvertedSticker(
        data=png,
        filename="sticker.png",
        content_type="image/png",
        kind="photo",
    )


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _convert_tgs_to_gif_sync(tgs_bytes: bytes) -> Optional[bytes]:
    """Возвращает GIF-байты или None при любой ошибке."""
    if not _has_ffmpeg():
        logger.warning("ffmpeg not found, tgs conversion disabled")
        return None
    try:
        from lottie.parsers.tgs import parse_tgs
        from lottie.exporters.gif import export_gif
    except ImportError:
        logger.warning("python-lottie not installed, tgs conversion disabled")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tgs_path = tmp_path / "sticker.tgs"
        gif_path = tmp_path / "sticker.gif"
        tgs_path.write_bytes(tgs_bytes)
        try:
            animation = parse_tgs(str(tgs_path))
            export_gif(animation, str(gif_path), skip_frames=2)
        except Exception:
            logger.exception("tgs → gif failed")
            return None
        if not gif_path.exists():
            return None
        return gif_path.read_bytes()


async def convert_animated_sticker(tgs_bytes: bytes) -> Optional[ConvertedSticker]:
    gif = await asyncio.to_thread(_convert_tgs_to_gif_sync, tgs_bytes)
    if not gif:
        return None
    return ConvertedSticker(
        data=gif,
        filename="sticker.gif",
        content_type="image/gif",
        kind="doc",
    )


async def passthrough_video_sticker(webm_bytes: bytes) -> ConvertedSticker:
    return ConvertedSticker(
        data=webm_bytes,
        filename="sticker.webm",
        content_type="video/webm",
        kind="doc",
    )
