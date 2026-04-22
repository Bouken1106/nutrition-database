from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NutrientTarget:
    target_id: str
    nutrient_id: str
    min_value: float | None
    max_value: float | None


def load_targets(targets_path: str | Path, known_nutrients: set[str]) -> list[NutrientTarget]:
    with open(targets_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list):
        raise ValueError("targets JSON must contain a 'targets' array")
    targets: list[NutrientTarget] = []
    for index, raw_target in enumerate(raw_targets, start=1):
        if not isinstance(raw_target, dict):
            raise ValueError("each target must be an object")
        nutrient_id = raw_target.get("nutrient_id")
        if nutrient_id not in known_nutrients:
            raise ValueError(f"unsupported nutrient_id: {nutrient_id}")
        min_value = raw_target.get("min")
        max_value = raw_target.get("max")
        if min_value is None and max_value is None:
            raise ValueError(f"target {nutrient_id} must define at least one of min or max")
        if min_value is not None:
            min_value = float(min_value)
        if max_value is not None:
            max_value = float(max_value)
        if min_value is not None and max_value is not None and min_value > max_value:
            raise ValueError(f"target {nutrient_id} has min greater than max")
        targets.append(
            NutrientTarget(
                target_id=f"target_{index}_{nutrient_id}",
                nutrient_id=str(nutrient_id),
                min_value=min_value,
                max_value=max_value,
            )
        )
    return targets

