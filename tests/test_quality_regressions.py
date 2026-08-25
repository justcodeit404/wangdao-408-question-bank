import json

import enhance_audit


def test_regression_fixture_checks_declared_fields(tmp_path, monkeypatch):
    fixture = tmp_path / "quality_regressions.json"
    fixture.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "source_uid": "408:cs408-ds::绪论 · 算法和算法评价 · 选择题::X01",
                        "expected": {
                            "options": {"A": "正确选项"},
                            "answer": {"choice": "A", "explanation_contains": "复杂度"},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(enhance_audit, "REGRESSIONS_PATH", fixture)
    rows = [
        (
            "绪论 · 算法和算法评价 · 选择题",
            {
                "id": "X01",
                "options": {"A": "正确选项", "B": "错误", "C": "错误", "D": "错误"},
                "answer": {"choice": "A", "explanation": "时间复杂度"},
            },
        )
    ]
    uid = "408:cs408-ds::绪论 · 算法和算法评价 · 选择题::X01"
    assert uid in {
        f"408:cs408-ds::{chapter}::{q['id']}" for chapter, q in rows
    }
    assert enhance_audit._regression_matches(None, rows[0][0], rows[0][1], {
        "options": {"A": "正确选项"},
        "answer": {"choice": "A", "explanation_contains": "复杂度"},
    }) == (True, "")


def test_regression_fixture_reports_mismatch():
    ok, field = enhance_audit._regression_matches(
        None,
        "章",
        {"options": {"A": "旧"}, "answer": {"choice": "B", "explanation": "解析"}},
        {"options": {"A": "新"}, "answer": {"choice": "A"}},
    )
    assert ok is False
    assert field == "options.A"
