from quality_ledger import assert_consistent, derive_manifests, question_hash


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
        "courses": {"ds": {"mode": "progressive", "total": 3, "certified": 1, "pending": 1, "held": 1}},
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
