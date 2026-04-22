from src.db.connection import get_connection
from src.db.repository import upsert_food
from src.db.schema import create_schema
from src.normalize.mapping import manual_map_foods


def test_mapping_override_behavior(tmp_path):
    db_path = tmp_path / "nutrition.db"
    with get_connection(db_path) as conn:
        create_schema(conn)
        upsert_food(
            conn,
            food_id="mext_rice",
            name="白米",
            source_type="mext",
            source_key="1001",
            canonical_name="白米",
            default_unit="g",
        )
        upsert_food(
            conn,
            food_id="estat_rice",
            name="白米",
            source_type="estat",
            source_key="rice_estat",
            canonical_name=None,
            default_unit="g",
        )
        conn.commit()
        mapping_csv = tmp_path / "mapping.csv"
        mapping_csv.write_text(
            "from_source_type,from_source_key,to_food_id,mapping_confidence\n"
            "estat,rice_estat,mext_rice,1.0\n",
            encoding="utf-8",
        )
        imported = manual_map_foods(conn, mapping_csv)
        assert imported == 1
        row = conn.execute("SELECT * FROM food_mapping").fetchone()
        assert row["from_source_key"] == "rice_estat"
        assert row["to_food_id"] == "mext_rice"
        assert row["mapping_method"] == "manual"

