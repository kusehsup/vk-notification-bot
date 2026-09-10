from bot.handlers.token import extract_token
from bot.oauth import (
    KATE_MOBILE_APP_ID,
    VK_ADMIN_APP_ID,
    VK_ANDROID_APP_ID,
    oauth_url,
)


def test_oauth_urls_use_live_apps_not_kate() -> None:
    admin = oauth_url(VK_ADMIN_APP_ID)
    android = oauth_url(VK_ANDROID_APP_ID)
    assert "client_id=6121396" in admin
    assert "client_id=2274003" in android
    assert str(KATE_MOBILE_APP_ID) not in admin
    assert "messages" in admin
    assert "offline" in admin
    assert "notifications" in admin
    assert admin.startswith("https://oauth.vk.com/authorize?")
    assert "blank.html" in admin


def test_extract_token_from_blank_redirect() -> None:
    url = (
        "https://oauth.vk.com/blank.html#access_token=vk1.a.ABC_def-123"
        "&expires_in=0&user_id=1"
    )
    assert extract_token(url) == "vk1.a.ABC_def-123"


def test_extract_token_bare() -> None:
    assert extract_token("vk1.a.Hello-World_99") == "vk1.a.Hello-World_99"
