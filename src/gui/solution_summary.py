from __future__ import annotations

from typing import Any

STATUS_LABELS = {
    "optimal": "最適",
    "infeasible": "実行不可",
    "error": "エラー",
}


def is_solution_result(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    return "status" in payload and "foods" in payload and "nutrients" in payload


def status_label(status: object) -> str:
    key = str(status or "").strip().lower()
    if not key:
        return "不明"
    return STATUS_LABELS.get(key, key)


def format_value(value: object) -> str:
    if value is None:
        return "なし"
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def target_range_text(min_value: object, max_value: object) -> str:
    if min_value is None and max_value is None:
        return "指定なし"
    parts: list[str] = []
    if min_value is not None:
        parts.append(f"下限 {format_value(min_value)}")
    if max_value is not None:
        parts.append(f"上限 {format_value(max_value)}")
    return " / ".join(parts)


def build_solution_summary_text(result: dict[str, Any]) -> str:
    lines = [
        "最適化結果サマリー",
        f"状態: {status_label(result.get('status'))} ({format_value(result.get('status'))})",
        f"合計コスト: {format_value(result.get('total_cost_yen'))} 円",
        f"除外食品数: {format_value(result.get('excluded_foods_count'))} 件",
    ]

    notes = result.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("注意事項:")
        for note in notes:
            lines.append(f"- {format_value(note)}")

    foods = result.get("foods")
    lines.append("")
    lines.append("選ばれた食品:")
    if isinstance(foods, list) and foods:
        for food in foods:
            if not isinstance(food, dict):
                continue
            lines.append(
                "- "
                f"{format_value(food.get('name'))} "
                f"(food_id={format_value(food.get('food_id'))}, "
                f"量={format_value(food.get('amount_g'))} g, "
                f"費用={format_value(food.get('cost_yen'))} 円)"
            )
    else:
        lines.append("- ありません")

    nutrients = result.get("nutrients")
    lines.append("")
    lines.append("栄養素の達成状況:")
    if isinstance(nutrients, list) and nutrients:
        for nutrient in nutrients:
            if not isinstance(nutrient, dict):
                continue
            lines.append(
                "- "
                f"{format_value(nutrient.get('nutrient_id'))}: "
                f"実績 {format_value(nutrient.get('actual'))}, "
                f"目標 {target_range_text(nutrient.get('target_min'), nutrient.get('target_max'))}"
            )
    else:
        lines.append("- ありません")
    return "\n".join(lines)
