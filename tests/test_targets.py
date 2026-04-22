import json

from src.optimize.targets import load_targets


def test_json_target_parsing(tmp_path):
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            {
                "targets": [
                    {"nutrient_id": "energy_kcal", "min": 1800, "max": 2200},
                    {"nutrient_id": "protein_g", "min": 80},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    targets = load_targets(targets_path, {"energy_kcal", "protein_g"})
    assert len(targets) == 2
    assert targets[0].nutrient_id == "energy_kcal"
    assert targets[0].min_value == 1800
    assert targets[0].max_value == 2200
    assert targets[1].max_value is None

