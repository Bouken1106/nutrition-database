from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone

SPACE_RE = re.compile(r"\s+")
IDENTIFIER_RE = re.compile(r"_+")


def normalize_name(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = re.sub(r"[()（）\[\]［］{}｛｝/／,，.。・･\-]+", " ", text)
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def conservative_name_key(value: object) -> str:
    return normalize_name(value).replace(" ", "")


def safe_identifier(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    chars: list[str] = []
    for char in text:
        if char.isascii() and (char.isalnum() or char in {"_", "-"}):
            chars.append(char.lower())
        else:
            chars.append("_")
    collapsed = IDENTIFIER_RE.sub("_", "".join(chars)).strip("_")
    if collapsed:
        return collapsed[:48]
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def build_source_key(name: str, code: object | None = None) -> str:
    if code is not None and str(code).strip():
        return unicodedata.normalize("NFKC", str(code)).strip()
    normalized = normalize_name(name)
    if normalized:
        return normalized
    return hashlib.sha1(str(name).encode("utf-8")).hexdigest()[:12]


def build_food_id(source_type: str, source_key: str) -> str:
    return f"{source_type}_{safe_identifier(source_key)}"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def coerce_iso8601(value: object | None) -> str:
    if value is None or str(value).strip() == "":
        return iso_now()
    if isinstance(value, datetime):
        normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if "T" in text and (text.endswith("Z") or "+" in text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text}T00:00:00Z"
    if re.fullmatch(r"\d{4}/\d{2}/\d{2}", text):
        return f"{text.replace('/', '-')}T00:00:00Z"
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return f"{text}-01T00:00:00Z"
    if re.fullmatch(r"\d{4}/\d{2}", text):
        return f"{text.replace('/', '-')}-01T00:00:00Z"
    return iso_now()

