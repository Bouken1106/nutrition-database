from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from src.db.repository import replace_food_nutrients, upsert_food
from src.ingest.common import read_excel_sheets
from src.normalize.names import build_food_id, build_source_key, normalize_name
from src.normalize.units import parse_number

LOGGER = logging.getLogger(__name__)

HEADER_ALIASES = {
    "name": ["食品名", "食品 名", "food name", "name"],
    "code": ["食品番号", "番号", "code", "食品番号 "],
    "edible_ratio": ["可食部", "edible ratio"],
    "refuse_percent": ["廃棄率", " refuse ", "refuse", "廃棄 部"],
}
NUTRIENT_ALIASES = {
    "energy_kcal": ["エネルギー", "energy", "kcal"],
    "protein_g": ["たんぱく質", "タンパク質", "protein"],
    "fat_g": ["脂質", "fat"],
    "carb_g": ["炭水化物", "carbohydrate", "carb"],
    "fiber_g": ["食物繊維", "fiber"],
    "calcium_mg": ["カルシウム", "calcium"],
    "iron_mg": ["鉄", "iron"],
    "vitamin_a_ug": ["ビタミンa", "vitamin a"],
    "vitamin_b1_mg": ["ビタミンb1", "vitamin b1"],
    "vitamin_b2_mg": ["ビタミンb2", "vitamin b2"],
    "vitamin_c_mg": ["ビタミンc", "vitamin c"],
}


def import_mext(conn: sqlite3.Connection, input_path: str | Path) -> int:
    imported = 0
    for sheet_name, rows in read_excel_sheets(input_path):
        header_idx, header_map = detect_header(rows)
        if header_idx is None:
            LOGGER.info("Skipping sheet without recognizable MEXT headers: %s", sheet_name)
            continue
        for row in rows[header_idx + 1 :]:
            name = value_at(row, header_map.get("name"))
            if not name:
                continue
            code = value_at(row, header_map.get("code"))
            source_key = build_source_key(name, code)
            food_id = build_food_id("mext", source_key)
            edible_ratio = 1.0
            edible_value = parse_number(value_at(row, header_map.get("edible_ratio")))
            refuse_value = parse_number(value_at(row, header_map.get("refuse_percent")))
            if edible_value is not None:
                edible_ratio = edible_value / 100.0 if edible_value > 1 else edible_value
            elif refuse_value is not None:
                ratio = refuse_value / 100.0 if refuse_value > 1 else refuse_value
                edible_ratio = max(0.0, 1.0 - ratio)
            upsert_food(
                conn,
                food_id=food_id,
                name=str(name).strip(),
                source_type="mext",
                source_key=source_key,
                canonical_name=str(name).strip(),
                default_unit="g",
                edible_ratio=edible_ratio,
            )
            nutrient_amounts: dict[str, float] = {}
            for nutrient_id in NUTRIENT_ALIASES:
                amount = parse_number(value_at(row, header_map.get(nutrient_id)))
                if amount is not None:
                    nutrient_amounts[nutrient_id] = amount
            if nutrient_amounts:
                replace_food_nutrients(conn, food_id, nutrient_amounts)
            imported += 1
    conn.commit()
    return imported


def detect_header(rows: list[tuple[object, ...]]) -> tuple[int | None, dict[str, int]]:
    best_index: int | None = None
    best_map: dict[str, int] = {}
    best_score = -1
    for index, row in enumerate(rows[:25]):
        mapping = header_map_from_row(row)
        score = len(mapping)
        if "name" in mapping and score > best_score:
            best_index = index
            best_map = mapping
            best_score = score
    return best_index, best_map


def header_map_from_row(row: tuple[object, ...]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(row):
        header = normalize_name(cell)
        if not header:
            continue
        for logical_name, aliases in HEADER_ALIASES.items():
            if logical_name not in mapping and any(alias in header for alias in aliases):
                mapping[logical_name] = idx
        for nutrient_id, aliases in NUTRIENT_ALIASES.items():
            if nutrient_id not in mapping and any(alias in header for alias in aliases):
                mapping[nutrient_id] = idx
    return mapping


def value_at(row: tuple[object, ...], idx: int | None) -> object | None:
    if idx is None or idx >= len(row):
        return None
    return row[idx]

