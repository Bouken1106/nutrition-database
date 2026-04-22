from __future__ import annotations

import sqlite3

NUTRIENT_DEFINITIONS = [
    ("energy_kcal", "Energy", "kcal"),
    ("protein_g", "Protein", "g"),
    ("fat_g", "Fat", "g"),
    ("carb_g", "Carbohydrate", "g"),
    ("fiber_g", "Fiber", "g"),
    ("calcium_mg", "Calcium", "mg"),
    ("iron_mg", "Iron", "mg"),
    ("vitamin_a_ug", "Vitamin A", "ug"),
    ("vitamin_b1_mg", "Vitamin B1", "mg"),
    ("vitamin_b2_mg", "Vitamin B2", "mg"),
    ("vitamin_c_mg", "Vitamin C", "mg"),
]

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS foods (
        food_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        source_type TEXT NOT NULL CHECK (source_type IN ('estat', 'mext', 'off')),
        source_key TEXT NOT NULL,
        canonical_name TEXT,
        default_unit TEXT NOT NULL CHECK (default_unit IN ('g', 'ml', 'piece')),
        edible_ratio REAL DEFAULT 1.0,
        is_active INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_foods_source
    ON foods (source_type, source_key)
    """,
    """
    CREATE TABLE IF NOT EXISTS nutrients (
        nutrient_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        unit TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS food_nutrients (
        food_id TEXT NOT NULL,
        nutrient_id TEXT NOT NULL,
        amount_per_100g REAL NOT NULL,
        PRIMARY KEY (food_id, nutrient_id),
        FOREIGN KEY (food_id) REFERENCES foods(food_id) ON DELETE CASCADE,
        FOREIGN KEY (nutrient_id) REFERENCES nutrients(nutrient_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS food_prices (
        food_id TEXT NOT NULL,
        price_yen REAL NOT NULL,
        quantity_value REAL NOT NULL,
        quantity_unit TEXT NOT NULL,
        price_per_g REAL,
        observed_at TEXT,
        source_detail TEXT,
        PRIMARY KEY (food_id, observed_at, source_detail),
        FOREIGN KEY (food_id) REFERENCES foods(food_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS food_mapping (
        mapping_id TEXT PRIMARY KEY,
        from_source_type TEXT NOT NULL,
        from_source_key TEXT NOT NULL,
        to_food_id TEXT NOT NULL,
        mapping_confidence REAL NOT NULL,
        mapping_method TEXT NOT NULL CHECK (mapping_method IN ('exact', 'manual', 'heuristic')),
        FOREIGN KEY (to_food_id) REFERENCES foods(food_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_food_mapping_source
    ON food_mapping (from_source_type, from_source_key)
    """,
    """
    CREATE TABLE IF NOT EXISTS nutrient_targets (
        target_id TEXT PRIMARY KEY,
        nutrient_id TEXT NOT NULL,
        min_value REAL,
        max_value REAL,
        FOREIGN KEY (nutrient_id) REFERENCES nutrients(nutrient_id) ON DELETE CASCADE
    )
    """,
]


def create_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    seed_nutrients(conn)
    conn.commit()


def seed_nutrients(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT INTO nutrients (nutrient_id, name, unit)
        VALUES (?, ?, ?)
        ON CONFLICT(nutrient_id) DO UPDATE SET
            name = excluded.name,
            unit = excluded.unit
        """,
        NUTRIENT_DEFINITIONS,
    )

