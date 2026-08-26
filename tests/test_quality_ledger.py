import json
from types import SimpleNamespace

import quality_ledger
from quality_ledger import (
    assert_consistent,
    derive_manifests,
    iter_choice_rows,
    question_hash,
)


def _item(uid, overall="pending", source="pending", answer="pending"):
    return {
        "source_uid": uid,
        "course_key": "ds",
        "chapter": "c",
        "question_id": "X01",
        "source_hash": "h",
        "source_fidelity": source,
        "answer_validation": answer,
        "overall": overall,
        "reason_codes": [],
    }


def test_ledger_summary_and_derived_hold_are_consistent():
    ledger = {
        "summary": {"total": 3, "certified": 1, "pending": 1, "held": 1},
        "published_hashes": {"ds": "data-hash"},
        "courses": {
            "ds": {
                "mode": "progressive",
                "total": 3,
                "certified": 1,
                "pending": 1,
                "held": 1,
            }
        },
        "items": {
            "u1": _item("u1", "certified", "verified", "verified"),
            "u2": _item("u2"),
            "u3": _item("u3", "hold", "conflict", "conflict"),
        },
    }
    assert_consistent(ledger)
    hold, verification = derive_manifests(ledger)
    assert hold["source_uids"] == ["u3"]
    assert verification["summary"]["total"] == 3


def test_certified_without_two_layers_is_rejected():
    ledger = {
        "summary": {"total": 1, "certified": 1, "pending": 0, "held": 0},
        "courses": {},
        "items": {"u1": _item("u1", "certified", "verified", "pending")},
    }
    try:
        assert_consistent(ledger)
    except ValueError as exc:
        assert "certified" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("incomplete certification must fail closed")


def test_question_hash_changes_when_answer_changes():
    question = {
        "id": "X01",
        "type": "选择题",
        "content": "题干",
        "options": {"A": "甲", "B": "乙"},
        "answer": {"choice": "A", "explanation": "说明"},
    }
    first = question_hash(question)
    question["answer"]["choice"] = "B"
    assert question_hash(question) != first


def _configure_published_bank(monkeypatch, tmp_path, data):
    bank_dir = tmp_path / "math-bank"
    bank_dir.mkdir()
    (bank_dir / "data-ds.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(quality_ledger, "MATH_BANK_DIR", bank_dir)
    monkeypatch.setattr(quality_ledger, "LEDGER_PATH", bank_dir / "quality-ledger.json")
    monkeypatch.setattr(quality_ledger, "HOLD_PATH", bank_dir / "quality-hold.json")
    monkeypatch.setattr(
        quality_ledger, "VERIFICATION_PATH", bank_dir / "quality-verification.json"
    )
    monkeypatch.setattr(quality_ledger, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(
        quality_ledger, "COURSES", [SimpleNamespace(key="ds", name="数据结构")]
    )


def test_build_ledger_includes_answer_questions_as_pending(monkeypatch, tmp_path):
    data = {
        "chapters": [
            {
                "name": "第一章 · 选择题",
                "questions": [
                    {
                        "id": "X01",
                        "type": "选择题",
                        "content": "题干",
                        "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
                        "answer": {"choice": "A", "explanation": "说明"},
                    },
                ],
            },
            {
                "name": "第一章 · 解答题",
                "questions": [
                    {
                        "id": "A01",
                        "type": "解答题",
                        "content": "证明题",
                        "answer": {"choice": "", "explanation": "证明"},
                    },
                ],
            },
        ],
    }
    _configure_published_bank(monkeypatch, tmp_path, data)

    ledger = quality_ledger.build_ledger()

    answer_uid = "408:cs408-ds::第一章 · 解答题::A01"
    assert set(ledger["items"]) == {
        "408:cs408-ds::第一章 · 选择题::X01",
        answer_uid,
    }
    assert ledger["items"][answer_uid]["overall"] == "pending"
    assert ledger["items"][answer_uid]["reason_codes"] == []
    assert quality_ledger.published_uid_counts("ds", data)[answer_uid] == 1
    assert [uid for uid, _, _ in iter_choice_rows("ds", data)] == [
        "408:cs408-ds::第一章 · 选择题::X01",
    ]


def test_build_ledger_holds_duplicate_uid_and_keeps_first_question(
    monkeypatch, tmp_path
):
    first = {
        "id": "X01",
        "type": "选择题",
        "content": "第一题",
        "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
        "answer": {"choice": "A"},
    }
    second = {
        "id": "X01",
        "type": "选择题",
        "content": "第二题",
        "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
        "answer": {"choice": "B"},
    }
    data = {"chapters": [{"name": "第一章 · 选择题", "questions": [first, second]}]}
    _configure_published_bank(monkeypatch, tmp_path, data)

    ledger = quality_ledger.build_ledger()

    uid = "408:cs408-ds::第一章 · 选择题::X01"
    assert list(ledger["items"]) == [uid]
    assert ledger["items"][uid]["source_hash"] == question_hash(first)
    assert ledger["items"][uid]["overall"] == "hold"
    assert {"structural_error", "duplicate_uid"} <= set(
        ledger["items"][uid]["reason_codes"]
    )
    assert quality_ledger.published_uid_counts("ds", data)[uid] == 2
