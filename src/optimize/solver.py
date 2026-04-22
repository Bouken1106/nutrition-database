from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pulp

from src.db.repository import store_targets
from src.normalize.pipeline import build_candidate_dataset
from src.optimize.targets import NutrientTarget, load_targets


def solve_diet(
    conn: sqlite3.Connection,
    targets: list[NutrientTarget],
) -> dict[str, object]:
    store_targets(
        conn,
        ((target.target_id, target.nutrient_id, target.min_value, target.max_value) for target in targets),
    )
    conn.commit()
    dataset = build_candidate_dataset(conn)
    candidates = dataset["candidates"]
    normalized_rows = dataset["normalized_rows"]
    if not candidates:
        return {
            "status": "infeasible",
            "total_cost_yen": None,
            "foods": [],
            "nutrients": [
                {
                    "nutrient_id": target.nutrient_id,
                    "actual": None,
                    "target_min": target.min_value,
                    "target_max": target.max_value,
                }
                for target in targets
            ],
            "excluded_foods_count": dataset["excluded_foods_count"],
            "notes": dataset["notes"] + ["no eligible foods available"],
        }
    problem = pulp.LpProblem("cheapest_daily_diet", pulp.LpMinimize)
    variables = {
        candidate.food_id: pulp.LpVariable(f"x_{index}", lowBound=0)
        for index, candidate in enumerate(candidates, start=1)
    }
    problem += pulp.lpSum(candidate.price_per_g * variables[candidate.food_id] for candidate in candidates)
    for target in targets:
        expr = pulp.lpSum(
            (candidate.nutrients.get(target.nutrient_id, 0.0) / 100.0) * variables[candidate.food_id]
            for candidate in candidates
        )
        if target.min_value is not None:
            problem += expr >= target.min_value, f"min_{target.nutrient_id}"
        if target.max_value is not None:
            problem += expr <= target.max_value, f"max_{target.nutrient_id}"
    solver = pulp.PULP_CBC_CMD(msg=False)
    problem.solve(solver)
    status_name = pulp.LpStatus.get(problem.status, "Undefined")
    if status_name == "Optimal":
        foods = []
        for candidate in sorted(candidates, key=lambda item: item.food_id):
            amount = variables[candidate.food_id].value()
            if amount is None or amount <= 1e-6:
                continue
            foods.append(
                {
                    "food_id": candidate.food_id,
                    "name": candidate.name,
                    "amount_g": round(amount, 4),
                    "cost_yen": round(amount * candidate.price_per_g, 4),
                }
            )
        nutrients = []
        for target in targets:
            actual = sum(
                (candidate.nutrients.get(target.nutrient_id, 0.0) / 100.0) * (variables[candidate.food_id].value() or 0.0)
                for candidate in candidates
            )
            nutrients.append(
                {
                    "nutrient_id": target.nutrient_id,
                    "actual": round(actual, 4),
                    "target_min": target.min_value,
                    "target_max": target.max_value,
                }
            )
        total_cost = sum(item["cost_yen"] for item in foods)
        return {
            "status": "optimal",
            "total_cost_yen": round(total_cost, 4),
            "foods": foods,
            "nutrients": nutrients,
            "excluded_foods_count": dataset["excluded_foods_count"],
            "notes": dataset["notes"],
        }
    if status_name == "Infeasible":
        return {
            "status": "infeasible",
            "total_cost_yen": None,
            "foods": [],
            "nutrients": [
                {
                    "nutrient_id": target.nutrient_id,
                    "actual": None,
                    "target_min": target.min_value,
                    "target_max": target.max_value,
                }
                for target in targets
            ],
            "excluded_foods_count": dataset["excluded_foods_count"],
            "notes": dataset["notes"],
        }
    return {
        "status": "error",
        "total_cost_yen": None,
        "foods": [],
        "nutrients": [
            {
                "nutrient_id": target.nutrient_id,
                "actual": None,
                "target_min": target.min_value,
                "target_max": target.max_value,
            }
            for target in targets
        ],
        "excluded_foods_count": dataset["excluded_foods_count"],
        "notes": dataset["notes"] + [f"solver status: {status_name}"],
    }


def solve_diet_to_file(
    conn: sqlite3.Connection,
    targets_path: str | Path,
    output_path: str | Path,
) -> dict[str, object]:
    nutrient_rows = conn.execute("SELECT nutrient_id FROM nutrients").fetchall()
    known_nutrients = {row["nutrient_id"] for row in nutrient_rows}
    targets = load_targets(targets_path, known_nutrients)
    result = solve_diet(conn, targets)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return result

