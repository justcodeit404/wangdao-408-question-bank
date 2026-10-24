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
    monkeypatch.setattr(
        quality_ledger, "PUBLISHED_LEDGER_PATH", bank_dir / "quality-ledger.published.json"
    )
    monkeypatch.setattr(quality_ledger, "LEDGER_JS_PATH", bank_dir / "quality-ledger.js")
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


def _mini_item(uid, *, overall="hold", source="conflict", answer="conflict", evidence=None):
    return {
        "source_uid": uid,
        "course_key": "ds",
        "chapter": "第一章 · 解答题",
        "question_id": uid.split("::")[-1],
        "source_hash": "stale-hash",
        "source_fidelity": source,
        "answer_validation": answer,
        "overall": overall,
        "reason_codes": ["structural_check"],
        "evidence": evidence or {"page_review": {"page": 12}},
    }


def _answer_question(qid, content):
    return {
        "id": qid,
        "type": "解答题",
        "content": content,
        "answer": {"choice": "", "explanation": "解析"},
    }


def _stub_legacy_sources(monkeypatch):
    monkeypatch.setattr(quality_ledger, "_old_verified_records", lambda: {})
    monkeypatch.setattr(quality_ledger, "_old_hold_uids", lambda: set())
    monkeypatch.setattr(quality_ledger, "_curated_records", lambda: {})


def test_rename_migration_moves_hold_and_evidence(monkeypatch, tmp_path):
    old_uid = "408:cs408-ds::第一章 · 解答题::A01_2"
    new_uid = "408:cs408-ds::第一章 · 解答题::A03"
    monkeypatch.setattr(quality_ledger, "RENAMED_UIDS", {old_uid: new_uid})
    _stub_legacy_sources(monkeypatch)
    data = {"chapters": [{"name": "第一章 · 解答题", "questions": [_answer_question("A03", "改号后的题")]}]}
    _configure_published_bank(monkeypatch, tmp_path, data)
    before = {
        "items": {old_uid: _mini_item(old_uid)},
        "courses": {"ds": {"mode": "strict"}},
        "published_hashes": {},
        "summary": {"total": 1, "certified": 0, "pending": 0, "held": 1},
    }

    ledger, changes = quality_ledger.migrate_drift(before)

    assert list(ledger["items"]) == [new_uid]
    item = ledger["items"][new_uid]
    assert item["overall"] == "hold", "改号不能把 hold 丢掉"
    assert item["source_hash"] == question_hash(data["chapters"][0]["questions"][0])
    assert "renamed_from:A01_2" in item["reason_codes"]
    assert item["evidence"] == {"page_review": {"page": 12}}
    assert any("改号迁移" in change for change in changes)
    assert quality_ledger.check_published(ledger) == []


def test_unregistered_publication_is_registered_and_gated(monkeypatch, tmp_path):
    _stub_legacy_sources(monkeypatch)
    data = {"chapters": [{"name": "第一章 · 解答题", "questions": [_answer_question("A09", "新补录的题")]}]}
    _configure_published_bank(monkeypatch, tmp_path, data)
    uid = "408:cs408-ds::第一章 · 解答题::A09"
    before = {"items": {}, "courses": {"ds": {"mode": "strict"}}, "published_hashes": {}}

    assert any("无记录" in problem for problem in quality_ledger.check_published(before))

    ledger, changes = quality_ledger.migrate_drift(before)

    assert uid in ledger["items"]
    assert "unregistered_publication" in ledger["items"][uid]["reason_codes"]
    assert ledger["items"][uid]["overall"] == "hold", "严格课程里未登记题不得默认放行"
    assert any("补登记发布题" in change for change in changes)
    assert quality_ledger.check_published(ledger) == []


def test_deleted_question_leaves_the_ledger(monkeypatch, tmp_path):
    _stub_legacy_sources(monkeypatch)
    data = {"chapters": [{"name": "第一章 · 解答题", "questions": [_answer_question("A03", "留下的题")]}]}
    _configure_published_bank(monkeypatch, tmp_path, data)
    gone_uid = "408:cs408-ds::第一章 · 解答题::X35_2"
    keep_uid = "408:cs408-ds::第一章 · 解答题::A03"
    before = {
        "items": {gone_uid: _mini_item(gone_uid), keep_uid: _mini_item(keep_uid)},
        "courses": {"ds": {"mode": "strict"}},
        "published_hashes": {},
    }

    ledger, changes = quality_ledger.migrate_drift(before)

    assert gone_uid not in ledger["items"]
    assert any("移出已删除题" in change for change in changes)


def test_duplicate_published_uid_is_reported(monkeypatch, tmp_path):
    _stub_legacy_sources(monkeypatch)
    data = {
        "chapters": [
            {"name": "第一章 · 解答题", "questions": [_answer_question("A01", "第一份")]},
            {"name": "第一章 · 解答题", "questions": [_answer_question("A01", "重复的")]},
        ]
    }
    _configure_published_bank(monkeypatch, tmp_path, data)
    before = {"items": {}, "courses": {"ds": {"mode": "strict"}}, "published_hashes": {}}

    problems = quality_ledger.check_published(before)

    assert any("重复 UID" in problem for problem in problems)


def test_item_hash_drift_is_reported_but_only_blocks_in_strict_mode(monkeypatch, tmp_path):
    _stub_legacy_sources(monkeypatch)
    question = _answer_question("A03", "内容")
    data = {"chapters": [{"name": "第一章 · 解答题", "questions": [question]}]}
    _configure_published_bank(monkeypatch, tmp_path, data)
    uid = "408:cs408-ds::第一章 · 解答题::A03"
    ledger = {
        "items": {uid: _mini_item(uid)},
        "courses": {"ds": {"mode": "strict"}},
        "published_hashes": {"ds": quality_ledger.sha256_file(tmp_path / "math-bank" / "data-ds.json")},
    }

    assert quality_ledger.check_published(ledger) == [], "重排导致的哈希漂移不阻断热更"
    assert quality_ledger.item_hash_drift(ledger) == [f"ds: {uid}"]
    strict = quality_ledger.check_published(ledger, strict_item_hashes=True)
    assert any("逐题哈希过期" in problem for problem in strict)


def test_real_rename_registry_contains_the_migrated_uids():
    assert quality_ledger.RENAMED_UIDS[
        "408:cs408-ds::绪论 · 算法和算法评价 · 解答题::A01_2"
    ].endswith("::A03")
    assert quality_ledger.RENAMED_UIDS[
        "408:cs408-net::网络层 · IPv4 · 选择题::X11_2"
    ].endswith("::A11_2")
