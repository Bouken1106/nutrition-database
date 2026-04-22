from src.db.connection import get_connection
from src.db.repository import insert_price, replace_food_nutrients, upsert_food, upsert_mapping
from src.db.schema import create_schema
from src.normalize.pipeline import build_candidate_dataset
from src.optimize.solver import solve_diet
from src.optimize.targets import NutrientTarget


def test_exclusion_logic(tmp_path):
    db_path = tmp_path / "nutrition.db"
    with get_connection(db_path) as conn:
        create_schema(conn)
        upsert_food(
            conn,
            food_id="mext_a",
            name="価格なし食品",
            source_type="mext",
            source_key="m1",
            canonical_name="価格なし食品",
            default_unit="g",
        )
        replace_food_nutrients(conn, "mext_a", {"protein_g": 10})

        upsert_food(
            conn,
            food_id="off_b",
            name="栄養なし食品",
            source_type="off",
            source_key="4900000000001",
            canonical_name=None,
            default_unit="g",
        )
        insert_price(
            conn,
            food_id="off_b",
            price_yen=100,
            quantity_value=100,
            quantity_unit="g",
            price_per_g=1.0,
            observed_at="2026-04-01T00:00:00Z",
            source_detail="test:1",
        )

        upsert_food(
            conn,
            food_id="off_c",
            name="個数価格食品",
            source_type="off",
            source_key="4900000000002",
            canonical_name=None,
            default_unit="piece",
        )
        replace_food_nutrients(conn, "off_c", {"protein_g": 5})
        insert_price(
            conn,
            food_id="off_c",
            price_yen=120,
            quantity_value=1,
            quantity_unit="piece",
            price_per_g=None,
            observed_at="2026-04-01T00:00:00Z",
            source_detail="test:2",
        )
        conn.commit()

        dataset = build_candidate_dataset(conn)
        assert dataset["excluded_foods_count"] == 3
        assert dataset["candidates"] == []
        assert "price missing foods excluded" in dataset["notes"]
        assert "nutrient missing foods excluded" in dataset["notes"]
        assert "non-gram price foods excluded" in dataset["notes"]


def test_feasible_optimization_case(tmp_path):
    db_path = tmp_path / "nutrition.db"
    with get_connection(db_path) as conn:
        create_schema(conn)
        upsert_food(
            conn,
            food_id="off_oats",
            name="オーツ",
            source_type="off",
            source_key="4900000000003",
            canonical_name=None,
            default_unit="g",
        )
        replace_food_nutrients(conn, "off_oats", {"protein_g": 10, "energy_kcal": 200})
        insert_price(
            conn,
            food_id="off_oats",
            price_yen=100,
            quantity_value=100,
            quantity_unit="g",
            price_per_g=1.0,
            observed_at="2026-04-01T00:00:00Z",
            source_detail="test:3",
        )
        conn.commit()

        result = solve_diet(
            conn,
            [
                NutrientTarget("target_1_protein_g", "protein_g", 10.0, None),
                NutrientTarget("target_2_energy_kcal", "energy_kcal", 200.0, None),
            ],
        )
        assert result["status"] == "optimal"
        assert result["foods"][0]["food_id"] == "off_oats"
        assert result["foods"][0]["amount_g"] == 100.0
        assert result["total_cost_yen"] == 100.0


def test_infeasible_optimization_case(tmp_path):
    db_path = tmp_path / "nutrition.db"
    with get_connection(db_path) as conn:
        create_schema(conn)
        upsert_food(
            conn,
            food_id="off_plain",
            name="平食品",
            source_type="off",
            source_key="4900000000004",
            canonical_name=None,
            default_unit="g",
        )
        replace_food_nutrients(conn, "off_plain", {"protein_g": 1})
        insert_price(
            conn,
            food_id="off_plain",
            price_yen=50,
            quantity_value=100,
            quantity_unit="g",
            price_per_g=0.5,
            observed_at="2026-04-01T00:00:00Z",
            source_detail="test:4",
        )
        conn.commit()

        result = solve_diet(
            conn,
            [NutrientTarget("target_1_vitamin_c_mg", "vitamin_c_mg", 10.0, None)],
        )
        assert result["status"] == "infeasible"
        assert result["foods"] == []

