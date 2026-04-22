from __future__ import annotations

from pathlib import Path

import sqlite3

from src.ingest.common import write_csv
from src.normalize.pipeline import build_candidate_dataset, build_unmatched_mapping_candidates


def export_all_csv(conn: sqlite3.Connection, output_dir: str | Path) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    dataset = build_candidate_dataset(conn)
    normalized_rows = dataset["normalized_rows"]
    unmatched_rows = build_unmatched_mapping_candidates(conn)
    foods_path = output / "normalized_foods.csv"
    prices_path = output / "normalized_prices.csv"
    nutrients_path = output / "normalized_nutrients.csv"
    unmatched_path = output / "unmatched_mapping_candidates.csv"
    write_csv(
        foods_path,
        [
            "food_id",
            "name",
            "source_type",
            "canonical_name",
            "default_unit",
            "is_eligible",
            "exclusion_reason",
            "price_per_g",
            "observed_at",
        ],
        (
            {
                "food_id": row["food_id"],
                "name": row["name"],
                "source_type": row["source_type"],
                "canonical_name": row["canonical_name"],
                "default_unit": row["default_unit"],
                "is_eligible": int(bool(row["is_eligible"])),
                "exclusion_reason": row["exclusion_reason"],
                "price_per_g": row["price_per_g"],
                "observed_at": row["observed_at"],
            }
            for row in normalized_rows
        ),
    )
    write_csv(
        prices_path,
        [
            "food_id",
            "effective_price_food_id",
            "price_yen",
            "quantity_value",
            "quantity_unit",
            "price_per_g",
            "observed_at",
            "source_detail",
            "mapped_source_key",
        ],
        (
            {
                "food_id": row["food_id"],
                "effective_price_food_id": row["effective_price_food_id"],
                "price_yen": row["price_yen"],
                "quantity_value": row["quantity_value"],
                "quantity_unit": row["quantity_unit"],
                "price_per_g": row["price_per_g"],
                "observed_at": row["observed_at"],
                "source_detail": row["source_detail"],
                "mapped_source_key": row["mapped_source_key"],
            }
            for row in normalized_rows
        ),
    )
    nutrient_rows = []
    for row in normalized_rows:
        for nutrient_id, amount in sorted(dict(row["nutrients"]).items()):
            nutrient_rows.append(
                {
                    "food_id": row["food_id"],
                    "name": row["name"],
                    "nutrient_id": nutrient_id,
                    "amount_per_100g": amount,
                }
            )
    write_csv(
        nutrients_path,
        ["food_id", "name", "nutrient_id", "amount_per_100g"],
        nutrient_rows,
    )
    write_csv(
        unmatched_path,
        ["food_id", "from_source_type", "from_source_key", "name", "normalized_name", "conservative_key"],
        unmatched_rows,
    )
    return {
        "normalized_foods": foods_path,
        "normalized_prices": prices_path,
        "normalized_nutrients": nutrients_path,
        "unmatched_mapping_candidates": unmatched_path,
    }


def export_unmatched_csv(conn: sqlite3.Connection, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(
        output,
        ["food_id", "from_source_type", "from_source_key", "name", "normalized_name", "conservative_key"],
        build_unmatched_mapping_candidates(conn),
    )
    return output

