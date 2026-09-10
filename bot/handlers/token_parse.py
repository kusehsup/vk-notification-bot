import re

TOKEN_RE = re.compile(r"vk1\.a\.[A-Za-z0-9_\-]+|[a-f0-9]{85,}", re.IGNORECASE)


def extract_token(text: str) -> str | None:
    text = text.strip()
    m = re.search(r"access_token=([^&\s#]+)", text)
    if m:
        return m.group(1)
    m = TOKEN_RE.search(text)
    if m:
        return m.group(0)
    return None
