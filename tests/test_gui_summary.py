from src.gui.solution_summary import build_solution_summary_text, is_solution_result, status_label


def test_build_solution_summary_text_contains_key_fields():
    result = {
        "status": "optimal",
        "total_cost_yen": 412.3,
        "foods": [
            {"food_id": "mext_1001", "name": "白米", "amount_g": 320.0, "cost_yen": 96.0},
        ],
        "nutrients": [
            {"nutrient_id": "protein_g", "actual": 67.2, "target_min": 60.0, "target_max": None},
        ],
        "excluded_foods_count": 154,
        "notes": ["price missing foods excluded"],
    }

    summary = build_solution_summary_text(result)

    assert "最適化結果サマリー" in summary
    assert "状態: 最適 (optimal)" in summary
    assert "合計コスト: 412.3 円" in summary
    assert "白米" in summary
    assert "protein_g" in summary
    assert "price missing foods excluded" in summary
    assert is_solution_result(result) is True
    assert status_label("optimal") == "最適"
