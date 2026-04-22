from src.db.connection import get_connection
from src.db.schema import NUTRIENT_DEFINITIONS, create_schema


def test_schema_creation(tmp_path):
    db_path = tmp_path / "nutrition.db"
    with get_connection(db_path) as conn:
        create_schema(conn)
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {
            "foods",
            "nutrients",
            "food_nutrients",
            "food_prices",
            "food_mapping",
            "nutrient_targets",
        }.issubset(tables)
        nutrient_count = conn.execute("SELECT COUNT(*) AS c FROM nutrients").fetchone()["c"]
        assert nutrient_count == len(NUTRIENT_DEFINITIONS)

