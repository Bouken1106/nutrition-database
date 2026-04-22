from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.normalize.mapping import resolve_effective_mappings
from src.normalize.names import conservative_name_key, normalize_name


@dataclass
class CandidateFood:
    food_id: str
    name: str
    price_per_g: float
    nutrients: dict[str, float]
    observed_at: str | None
    source_detail: str | None


def build_candidate_dataset(conn: sqlite3.Connection) -> dict[str, object]:
    foods = conn.execute(
        """
        SELECT food_id, name, source_type, source_key, canonical_name, default_unit, edible_ratio
        FROM foods
        WHERE is_active = 1
        """
    ).fetchall()
    nutrients_by_food = load_nutrients_by_food(conn)
    latest_prices = load_latest_prices(conn)
    mappings = resolve_effective_mappings(conn, "estat")
    estat_foods = [row for row in foods if row["source_type"] == "estat"]
    estat_by_key = {row["source_key"]: row for row in estat_foods}
    normalized_rows: list[dict[str, object]] = []
    for food in foods:
        if food["source_type"] not in {"mext", "off"}:
            continue
        nutrient_map = nutrients_by_food.get(food["food_id"], {})
        price_row = None
        mapped_source_key = None
        if food["source_type"] == "off":
            price_row = latest_prices.get(food["food_id"])
        elif food["source_type"] == "mext":
            candidate_rows = []
            for (source_type, source_key), mapping in mappings.items():
                if source_type != "estat" or mapping["to_food_id"] != food["food_id"]:
                    continue
                source_food = estat_by_key.get(source_key)
                if source_food is None:
                    continue
                direct_price = latest_prices.get(source_food["food_id"])
                if direct_price is not None:
                    candidate_rows.append((source_key, direct_price))
            if candidate_rows:
                mapped_source_key, price_row = max(
                    candidate_rows,
                    key=lambda item: (
                        item[1]["observed_at"] or "",
                        item[1]["source_detail"] or "",
                        item[0],
                    ),
                )
        reasons: list[str] = []
        if not nutrient_map:
            reasons.append("nutrient_missing")
        if price_row is None:
            reasons.append("price_missing")
        elif price_row["price_per_g"] is None:
            reasons.append("non_gram_price")
        normalized_rows.append(
            {
                "food_id": food["food_id"],
                "name": food["canonical_name"] or food["name"],
                "source_type": food["source_type"],
                "canonical_name": food["canonical_name"],
                "default_unit": food["default_unit"],
                "mapped_source_key": mapped_source_key,
                "effective_price_food_id": None if price_row is None else price_row["food_id"],
                "price_yen": None if price_row is None else price_row["price_yen"],
                "quantity_value": None if price_row is None else price_row["quantity_value"],
                "quantity_unit": None if price_row is None else price_row["quantity_unit"],
                "price_per_g": None if price_row is None else price_row["price_per_g"],
                "observed_at": None if price_row is None else price_row["observed_at"],
                "source_detail": None if price_row is None else price_row["source_detail"],
                "is_eligible": not reasons,
                "exclusion_reason": ";".join(reasons),
                "nutrients": nutrient_map,
            }
        )
    candidates = [
        CandidateFood(
            food_id=row["food_id"],
            name=str(row["name"]),
            price_per_g=float(row["price_per_g"]),
            nutrients=dict(row["nutrients"]),
            observed_at=row["observed_at"],
            source_detail=row["source_detail"],
        )
        for row in normalized_rows
        if row["is_eligible"]
    ]
    notes = build_notes(normalized_rows)
    return {
        "normalized_rows": normalized_rows,
        "candidates": candidates,
        "excluded_foods_count": sum(1 for row in normalized_rows if not row["is_eligible"]),
        "notes": notes,
    }


def build_unmatched_mapping_candidates(conn: sqlite3.Connection) -> list[dict[str, object]]:
    mappings = resolve_effective_mappings(conn, "estat")
    estat_rows = conn.execute(
        """
        SELECT food_id, source_key, name
        FROM foods
        WHERE source_type = 'estat' AND is_active = 1
        ORDER BY source_key
        """
    ).fetchall()
    unmatched: list[dict[str, object]] = []
    for row in estat_rows:
        if ("estat", row["source_key"]) in mappings:
            continue
        unmatched.append(
            {
                "food_id": row["food_id"],
                "from_source_type": "estat",
                "from_source_key": row["source_key"],
                "name": row["name"],
                "normalized_name": normalize_name(row["name"]),
                "conservative_key": conservative_name_key(row["name"]),
            }
        )
    return unmatched


def load_nutrients_by_food(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    rows = conn.execute(
        """
        SELECT food_id, nutrient_id, amount_per_100g
        FROM food_nutrients
        """
    ).fetchall()
    grouped: dict[str, dict[str, float]] = {}
    for row in rows:
        grouped.setdefault(row["food_id"], {})[row["nutrient_id"]] = row["amount_per_100g"]
    return grouped


def load_latest_prices(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT food_id, price_yen, quantity_value, quantity_unit, price_per_g, observed_at, source_detail
        FROM food_prices
        ORDER BY food_id, observed_at DESC, source_detail DESC
        """
    ).fetchall()
    latest: dict[str, sqlite3.Row] = {}
    for row in rows:
        latest.setdefault(row["food_id"], row)
    return latest


def build_notes(normalized_rows: list[dict[str, object]]) -> list[str]:
    reason_map = {
        "price_missing": "price missing foods excluded",
        "nutrient_missing": "nutrient missing foods excluded",
        "non_gram_price": "non-gram price foods excluded",
    }
    seen: set[str] = set()
    notes: list[str] = []
    for row in normalized_rows:
        raw_reasons = str(row["exclusion_reason"] or "")
        for reason in filter(None, raw_reasons.split(";")):
            if reason not in seen:
                seen.add(reason)
                notes.append(reason_map.get(reason, reason))
    return notes

