import re

TOKEN_RE = re.compile(r"vk1\.a\.[A-Za-z0-9_\-]+|[a-f0-9]{85,}", re.IGNORECASE)
BEARER_RE = re.compile(
    r"(?:Authorization:\s*)?Bearer\s+(vk1\.a\.[A-Za-z0-9_\-]+)",
    re.IGNORECASE,
)


def extract_token(text: str) -> str | None:
    explicit = extract_explicit_token(text)
    if explicit:
        return explicit
    m = TOKEN_RE.search(text.strip())
    if m:
        return m.group(0)
    return None


def extract_explicit_token(text: str) -> str | None:
    """Bearer / access_token= — не vk1.a из remixhttphash в Cookie."""
    m = BEARER_RE.search(text)
    if m:
        return m.group(1)
    m = re.search(r"access_token=([^&\s#]+)", text)
    if m:
        return m.group(1)
    return None
