from __future__ import annotations

import re
import unicodedata

TRACE_MARKERS = {"", "-", "--", "tr", "trace", "微量", "na", "n/a"}
MASS_UNITS = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
    "mg": 0.001,
    "milligram": 0.001,
    "milligrams": 0.001,
}
VOLUME_UNITS = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
}
PIECE_UNITS = {"piece", "pieces", "個", "本", "袋", "pack", "packs"}
UNIT_ALIASES = {
    "グラム": "g",
    "ｇ": "g",
    "kg": "kg",
    "ｋｇ": "kg",
    "キログラム": "kg",
    "mg": "mg",
    "ｍｇ": "mg",
    "ミリグラム": "mg",
    "ml": "ml",
    "ｍｌ": "ml",
    "ミリリットル": "ml",
    "cc": "ml",
    "l": "l",
    "ｌ": "l",
    "リットル": "l",
    "個": "piece",
    "本": "piece",
    "袋": "piece",
}
MULTIPLIER_RE = re.compile(
    r"^\s*(?P<count>\d+(?:\.\d+)?)\s*[x×]\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z\u3040-\u30ff\u3400-\u9fff]+)\s*$"
)
SIMPLE_QUANTITY_RE = re.compile(
    r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z\u3040-\u30ff\u3400-\u9fff]+)\s*$"
)


def parse_number(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = text.replace(",", "")
    if text in TRACE_MARKERS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_unit(unit: object | None) -> str | None:
    if unit is None:
        return None
    text = unicodedata.normalize("NFKC", str(unit)).strip().lower()
    if not text:
        return None
    return UNIT_ALIASES.get(text, text)


def normalize_mass_to_g(value: float | int | None, unit: object | None) -> float | None:
    if value is None:
        return None
    normalized_unit = normalize_unit(unit)
    if normalized_unit not in MASS_UNITS:
        return None
    return float(value) * MASS_UNITS[normalized_unit]


def parse_quantity_text(text: object | None) -> tuple[float, str] | None:
    if text is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(text)).strip()
    if not normalized:
        return None
    multiplier_match = MULTIPLIER_RE.match(normalized)
    if multiplier_match:
        unit = normalize_unit(multiplier_match.group("unit"))
        if unit is None:
            return None
        count = float(multiplier_match.group("count"))
        value = float(multiplier_match.group("value"))
        return count * value, unit
    simple_match = SIMPLE_QUANTITY_RE.match(normalized)
    if simple_match:
        unit = normalize_unit(simple_match.group("unit"))
        if unit is None:
            return None
        return float(simple_match.group("value")), unit
    return None


def price_per_g(price_yen: float, quantity_value: float, quantity_unit: str) -> float | None:
    grams = normalize_mass_to_g(quantity_value, quantity_unit)
    if grams is None or grams <= 0:
        return None
    return price_yen / grams


def convert_unit(value: float, from_unit: object | None, to_unit: str) -> float | None:
    normalized_from = normalize_unit(from_unit)
    normalized_to = normalize_unit(to_unit)
    if normalized_from is None or normalized_to is None:
        return None
    if normalized_from == normalized_to:
        return value
    if normalized_from in MASS_UNITS and normalized_to in MASS_UNITS:
        grams = value * MASS_UNITS[normalized_from]
        return grams / MASS_UNITS[normalized_to]
    return None

