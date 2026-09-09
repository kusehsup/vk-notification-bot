from vk.client import parse_vk_error
from vk.formatters import format_longpoll_message


def test_parse_flood_error() -> None:
    err = parse_vk_error({"error_code": 9, "error_msg": "Flood control", "retry_after": 12})
    assert err.code == 9
    assert err.is_flood
    assert not err.is_auth
    assert err.retry_after == 12.0
    assert "Flood control" in str(err)


def test_parse_auth_error() -> None:
    err = parse_vk_error({"error_code": 5, "error_msg": "User authorization failed"})
    assert err.is_auth
    assert not err.is_flood
    assert err.retry_after is None


def test_format_direct_message() -> None:
    text = format_longpoll_message(621881490, "привет", {"from": "621881490"})
    assert "привет" in text
    assert "id621881490" in text
    assert "💬" in text


def test_format_chat_with_attachments() -> None:
    extras = {
        "from": "123",
        "attach1_type": "photo",
        "attach2_type": "audio_message",
        "fwd": "1",
    }
    text = format_longpoll_message(2_000_000_015, "файл", extras, chat_title="Работа")
    assert "файл" in text
    assert "Работа" in text
    assert "фото" in text
    assert "голосовое" in text
    assert "пересланные" in text
