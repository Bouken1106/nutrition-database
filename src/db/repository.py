from __future__ import annotations

import hashlib
import sqlite3
from typing import Iterable


def upsert_food(
    conn: sqlite3.Connection,
    *,
    food_id: str,
    name: str,
    source_type: str,
    source_key: str,
    canonical_name: str | None,
    default_unit: str,
    edible_ratio: float = 1.0,
    is_active: int = 1,
) -> None:
    conn.execute(
        """
        INSERT INTO foods (
            food_id, name, source_type, source_key, canonical_name, default_unit, edible_ratio, is_active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(food_id) DO UPDATE SET
            name = excluded.name,
            source_type = excluded.source_type,
            source_key = excluded.source_key,
            canonical_name = excluded.canonical_name,
            default_unit = excluded.default_unit,
            edible_ratio = excluded.edible_ratio,
            is_active = excluded.is_active
        """,
        (
            food_id,
            name,
            source_type,
            source_key,
            canonical_name,
            default_unit,
            edible_ratio,
            is_active,
        ),
    )


def replace_food_nutrients(
    conn: sqlite3.Connection,
    food_id: str,
    nutrient_amounts: dict[str, float],
) -> None:
    conn.execute("DELETE FROM food_nutrients WHERE food_id = ?", (food_id,))
    for nutrient_id, amount in nutrient_amounts.items():
        conn.execute(
            """
            INSERT INTO food_nutrients (food_id, nutrient_id, amount_per_100g)
            VALUES (?, ?, ?)
            ON CONFLICT(food_id, nutrient_id) DO UPDATE SET
                amount_per_100g = excluded.amount_per_100g
            """,
            (food_id, nutrient_id, amount),
        )


def insert_price(
    conn: sqlite3.Connection,
    *,
    food_id: str,
    price_yen: float,
    quantity_value: float,
    quantity_unit: str,
    price_per_g: float | None,
    observed_at: str | None,
    source_detail: str,
) -> None:
    conn.execute(
        """
        INSERT INTO food_prices (
            food_id, price_yen, quantity_value, quantity_unit, price_per_g, observed_at, source_detail
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(food_id, observed_at, source_detail) DO UPDATE SET
            price_yen = excluded.price_yen,
            quantity_value = excluded.quantity_value,
            quantity_unit = excluded.quantity_unit,
            price_per_g = excluded.price_per_g
        """,
        (
            food_id,
            price_yen,
            quantity_value,
            quantity_unit,
            price_per_g,
            observed_at,
            source_detail,
        ),
    )


def mapping_id_for(
    from_source_type: str,
    from_source_key: str,
    to_food_id: str,
    mapping_method: str,
) -> str:
    raw = "::".join((from_source_type, from_source_key, to_food_id, mapping_method))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def upsert_mapping(
    conn: sqlite3.Connection,
    *,
    from_source_type: str,
    from_source_key: str,
    to_food_id: str,
    mapping_confidence: float,
    mapping_method: str,
) -> str:
    mapping_id = mapping_id_for(from_source_type, from_source_key, to_food_id, mapping_method)
    conn.execute(
        """
        DELETE FROM food_mapping
        WHERE from_source_type = ?
          AND from_source_key = ?
          AND mapping_method = ?
          AND mapping_id <> ?
        """,
        (from_source_type, from_source_key, mapping_method, mapping_id),
    )
    conn.execute(
        """
        INSERT INTO food_mapping (
            mapping_id, from_source_type, from_source_key, to_food_id, mapping_confidence, mapping_method
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(mapping_id) DO UPDATE SET
            mapping_confidence = excluded.mapping_confidence
        """,
        (
            mapping_id,
            from_source_type,
            from_source_key,
            to_food_id,
            mapping_confidence,
            mapping_method,
        ),
    )
    return mapping_id


def store_targets(
    conn: sqlite3.Connection,
    targets: Iterable[tuple[str, str, float | None, float | None]],
) -> None:
    conn.execute("DELETE FROM nutrient_targets")
    conn.executemany(
        """
        INSERT INTO nutrient_targets (target_id, nutrient_id, min_value, max_value)
        VALUES (?, ?, ?, ?)
        """,
        list(targets),
    )
