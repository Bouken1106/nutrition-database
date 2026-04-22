from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from src.db.repository import upsert_mapping
from src.ingest.common import read_csv_rows
from src.normalize.names import conservative_name_key, normalize_name
from src.normalize.units import parse_number

MAPPING_PRIORITY = {"manual": 0, "exact": 1, "heuristic": 2}


def resolve_effective_mappings(
    conn: sqlite3.Connection,
    from_source_type: str | None = None,
) -> dict[tuple[str, str], sqlite3.Row]:
    query = """
        SELECT mapping_id, from_source_type, from_source_key, to_food_id, mapping_confidence, mapping_method
        FROM food_mapping
    """
    params: tuple[object, ...] = ()
    if from_source_type is not None:
        query += " WHERE from_source_type = ?"
        params = (from_source_type,)
    rows = conn.execute(query, params).fetchall()
    ordered = sorted(
        rows,
        key=lambda row: (
            row["from_source_type"],
            row["from_source_key"],
            MAPPING_PRIORITY.get(row["mapping_method"], 99),
            -row["mapping_confidence"],
            row["mapping_id"],
        ),
    )
    resolved: dict[tuple[str, str], sqlite3.Row] = {}
    for row in ordered:
        key = (row["from_source_type"], row["from_source_key"])
        resolved.setdefault(key, row)
    return resolved


def auto_map_foods(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        DELETE FROM food_mapping
        WHERE from_source_type = 'estat' AND mapping_method IN ('exact', 'heuristic')
        """
    )
    manual_mappings = resolve_effective_mappings(conn, "estat")
    mext_rows = conn.execute(
        """
        SELECT food_id, name, canonical_name
        FROM foods
        WHERE source_type = 'mext' AND is_active = 1
        """
    ).fetchall()
    exact_index: dict[str, list[str]] = {}
    conservative_index: dict[str, list[str]] = {}
    for row in mext_rows:
        basis_name = row["canonical_name"] or row["name"]
        exact_key = normalize_name(basis_name)
        conservative_key = conservative_name_key(basis_name)
        exact_index.setdefault(exact_key, []).append(row["food_id"])
        conservative_index.setdefault(conservative_key, []).append(row["food_id"])
    imported = 0
    estat_rows = conn.execute(
        """
        SELECT source_key, name
        FROM foods
        WHERE source_type = 'estat' AND is_active = 1
        """
    ).fetchall()
    for row in estat_rows:
        source_key = row["source_key"]
        if ("estat", source_key) in manual_mappings:
            continue
        exact_candidates = sorted(set(exact_index.get(normalize_name(row["name"]), [])))
        if len(exact_candidates) == 1:
            upsert_mapping(
                conn,
                from_source_type="estat",
                from_source_key=source_key,
                to_food_id=exact_candidates[0],
                mapping_confidence=1.0,
                mapping_method="exact",
            )
            imported += 1
            continue
        heuristic_candidates = sorted(set(conservative_index.get(conservative_name_key(row["name"]), [])))
        if len(heuristic_candidates) == 1:
            upsert_mapping(
                conn,
                from_source_type="estat",
                from_source_key=source_key,
                to_food_id=heuristic_candidates[0],
                mapping_confidence=0.8,
                mapping_method="heuristic",
            )
            imported += 1
    conn.commit()
    return imported


def manual_map_foods(conn: sqlite3.Connection, mapping_csv_path: str | Path) -> int:
    rows = read_csv_rows(mapping_csv_path)
    imported = 0
    for raw in rows:
        from_source_type = str(raw.get("from_source_type") or "estat").strip()
        from_source_key = str(raw.get("from_source_key") or "").strip()
        to_food_id = str(raw.get("to_food_id") or "").strip()
        if not from_source_key or not to_food_id:
            raise ValueError("manual mapping CSV must include from_source_key and to_food_id")
        if conn.execute("SELECT 1 FROM foods WHERE food_id = ?", (to_food_id,)).fetchone() is None:
            raise ValueError(f"manual mapping target does not exist: {to_food_id}")
        mapping_confidence = parse_number(raw.get("mapping_confidence"))
        upsert_mapping(
            conn,
            from_source_type=from_source_type,
            from_source_key=from_source_key,
            to_food_id=to_food_id,
            mapping_confidence=1.0 if mapping_confidence is None else mapping_confidence,
            mapping_method="manual",
        )
        imported += 1
    conn.commit()
    return imported

