from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"(password\s*=\s*)\S+", re.IGNORECASE),
    re.compile(r"(['\"]?(?:motherduck_)?token['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9_.\-+/=]{8,}", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(authorization\s*[:=]\s*)\S+(?:\s+\S+)?", re.IGNORECASE),
    re.compile(r"(bearer\s+)\S+", re.IGNORECASE),
    re.compile(r"(https?://[^/@\s:]+:)[^@\s]+(?=@)"),
    re.compile(r"(hooks\.slack\.com/services/)[A-Za-z0-9/_-]+"),
]


def redact_secrets(text: str) -> str:
    if not isinstance(text, str):
        return ""
    out = text
    for pat in _PATTERNS:
        out = pat.sub(r"\1[redacted]", out)
    return out


def format_error(e: BaseException, max_len: int = 200) -> str:
    raw = f"{type(e).__name__}: {str(e)[:max_len]}"
    return redact_secrets(raw)
