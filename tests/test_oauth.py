from bot.handlers.token_parse import extract_token
from bot.oauth import START_TEXT, auth_keyboard
from vk.web_token import looks_like_cookies, parse_cookie_blob


def test_auth_keyboard_opens_vk_site() -> None:
    kb = auth_keyboard()
    url = kb.inline_keyboard[0][0].url
    assert url in {"https://vk.com", "https://vk.ru"}
    assert "oauth.vk.com" not in START_TEXT
    assert "remixsid" in START_TEXT
    assert "VK Admin" not in START_TEXT or "больше не" in START_TEXT.lower() or "закрыл" in START_TEXT


def test_extract_token_from_blank_redirect() -> None:
    url = (
        "https://oauth.vk.com/blank.html#access_token=vk1.a.ABC_def-123"
        "&expires_in=0&user_id=1"
    )
    assert extract_token(url) == "vk1.a.ABC_def-123"


def test_extract_token_bare() -> None:
    assert extract_token("vk1.a.Hello-World_99") == "vk1.a.Hello-World_99"


def test_parse_cookie_header() -> None:
    raw = "remixsid=abc123; p=secret; remixlang=0"
    parsed = parse_cookie_blob(raw)
    assert parsed is not None
    assert parsed["remixsid"] == "abc123"
    assert parsed["p"] == "secret"
    assert looks_like_cookies(raw)


def test_parse_cookie_prefixed_header() -> None:
    raw = "Cookie: remixsid=tok; remixnsid=n"
    parsed = parse_cookie_blob(raw)
    assert parsed is not None
    assert parsed["remixsid"] == "tok"


def test_parse_cookie_curl() -> None:
    raw = "curl 'https://vk.com' -H 'Cookie: remixsid=fromcurl; p=1' --compressed"
    parsed = parse_cookie_blob(raw)
    assert parsed is not None
    assert parsed["remixsid"] == "fromcurl"


def test_parse_cookie_json_editor() -> None:
    raw = '[{"name": "remixsid", "value": "jval"}, {"name": "p", "value": "q"}]'
    parsed = parse_cookie_blob(raw)
    assert parsed == {"remixsid": "jval", "p": "q"}


def test_parse_cookie_netscape() -> None:
    raw = (
        "# Netscape HTTP Cookie File\n"
        ".vk.com\tTRUE\t/\tTRUE\t0\tremixsid\tnsid\n"
        ".vk.com\tTRUE\t/\tFALSE\t0\tp\tpp\n"
    )
    parsed = parse_cookie_blob(raw)
    assert parsed is not None
    assert parsed["remixsid"] == "nsid"
    assert parsed["p"] == "pp"


def test_parse_cookie_rejects_random_text() -> None:
    assert parse_cookie_blob("hello world") is None
    assert not looks_like_cookies("access_token=vk1.a.xxx")


def test_parse_wrapped_remixsid() -> None:
    raw = (
        "Cookie: remixlang=0; remixhttphash=vk1.a.AAAA\n"
        "BBBBCCCC; remixsid=1_abcDEF-ghi_jklmnopqrstuvwxyz0123456789ABCD\n"
        "Origin: https://vk.ru"
    )
    parsed = parse_cookie_blob(raw)
    assert parsed is not None
    assert parsed["remixsid"].startswith("1_abcDEF")
    assert parsed.get("remixhttphash", "").replace("\n", "").startswith("vk1.a")


def test_parse_bare_remixsid_value() -> None:
    sid = "1_CfljRp89_FhhCpAFlkT_F2v-Uvn5mihvOzuTipken3q3HRFC7dluiQGkQ3vAvO98f4NDd"
    parsed = parse_cookie_blob(sid)
    assert parsed == {"remixsid": sid}


def test_extract_bearer_not_httphash() -> None:
    from bot.handlers.token_parse import extract_explicit_token

    dump = (
        "Authorization: Bearer vk1.a.REALTOKEN\n"
        "Cookie: remixhttphash=vk1.a.HASHHASH; remixsid=1_abc"
    )
    assert extract_explicit_token(dump) == "vk1.a.REALTOKEN"
    parsed = parse_cookie_blob(dump)
    assert parsed is not None
    assert parsed["remixsid"] == "1_abc"
