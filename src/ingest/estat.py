from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from src.db.repository import insert_price, upsert_food
from src.ingest.common import read_csv_rows, read_excel_sheets
from src.normalize.names import build_food_id, build_source_key, coerce_iso8601, normalize_name
from src.normalize.units import parse_number, parse_quantity_text, price_per_g

LOGGER = logging.getLogger(__name__)

HEADER_ALIASES = {
    "name": ["品目", "品名", "食品名", "商品名", "name", "item"],
    "code": ["コード", "code", "品目コード"],
    "price": ["価格", "price", "代表価格", "retail price"],
    "observed_at": ["年月", "date", "observed", "調査年月", "month"],
    "quantity_value": ["内容量", "quantity value", "quantity", "weight"],
    "quantity_unit": ["単位", "quantity unit", "unit"],
    "quantity_text": ["内容量表示", "quantity text", "package size", "content"],
}


def import_estat(conn: sqlite3.Connection, input_path: str | Path) -> int:
    path = Path(input_path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        records = read_csv_records(path)
    elif suffix in {".xlsx", ".xlsm"}:
        records = read_excel_records(path)
    else:
        raise ValueError("ingest-estat supports .csv, .xlsx, and .xlsm files")
    imported = 0
    for index, record in enumerate(records, start=1):
        name = record.get("name")
        price_value = parse_number(record.get("price"))
        if not name or price_value is None:
            continue
        code = record.get("code")
        source_key = build_source_key(str(name), code)
        food_id = build_food_id("estat", source_key)
        quantity_value = parse_number(record.get("quantity_value"))
        quantity_unit = record.get("quantity_unit")
        if quantity_value is None or not quantity_unit:
            parsed_quantity = parse_quantity_text(record.get("quantity_text"))
            if parsed_quantity is not None:
                quantity_value, quantity_unit = parsed_quantity
        if quantity_value is None or not quantity_unit:
            LOGGER.info("Skipping e-Stat row with missing quantity for %s", name)
            continue
        default_unit = "piece"
        normalized_unit = str(quantity_unit).strip().lower()
        if normalized_unit in {"g", "kg", "mg"}:
            default_unit = "g"
        elif normalized_unit in {"ml", "l"}:
            default_unit = "ml"
        upsert_food(
            conn,
            food_id=food_id,
            name=str(name).strip(),
            source_type="estat",
            source_key=source_key,
            canonical_name=None,
            default_unit=default_unit,
            edible_ratio=1.0,
        )
        observed_at = coerce_iso8601(record.get("observed_at"))
        source_detail = f"{path.name}:row{index}"
        insert_price(
            conn,
            food_id=food_id,
            price_yen=float(price_value),
            quantity_value=float(quantity_value),
            quantity_unit=str(quantity_unit),
            price_per_g=price_per_g(float(price_value), float(quantity_value), str(quantity_unit)),
            observed_at=observed_at,
            source_detail=source_detail,
        )
        imported += 1
    conn.commit()
    return imported


def read_csv_records(path: Path) -> list[dict[str, object]]:
    rows = read_csv_rows(path)
    return [normalize_record(row) for row in rows]


def read_excel_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for sheet_name, rows in read_excel_sheets(path):
        header_idx, header_map = detect_header(rows)
        if header_idx is None:
            LOGGER.info("Skipping sheet without recognizable e-Stat headers: %s", sheet_name)
            continue
        for row in rows[header_idx + 1 :]:
            mapped: dict[str, object] = {}
            for key, idx in header_map.items():
                if idx < len(row):
                    mapped[key] = row[idx]
            if mapped:
                records.append(mapped)
    return records


def detect_header(rows: list[tuple[object, ...]]) -> tuple[int | None, dict[str, int]]:
    best_index: int | None = None
    best_map: dict[str, int] = {}
    best_score = -1
    for index, row in enumerate(rows[:25]):
        mapping = {}
        for idx, cell in enumerate(row):
            header = normalize_name(cell)
            if not header:
                continue
            for logical_name, aliases in HEADER_ALIASES.items():
                if logical_name not in mapping and any(alias in header for alias in aliases):
                    mapping[logical_name] = idx
        score = len(mapping)
        if "name" in mapping and "price" in mapping and score > best_score:
            best_index = index
            best_map = mapping
            best_score = score
    return best_index, best_map


def normalize_record(row: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in row.items():
        header = normalize_name(key)
        for logical_name, aliases in HEADER_ALIASES.items():
            if logical_name not in normalized and any(alias in header for alias in aliases):
                normalized[logical_name] = value
    if not normalized and row:
        normalized = dict(row)
    return normalized

