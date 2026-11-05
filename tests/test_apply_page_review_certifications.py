import json

import apply_page_review_certifications as apply_mod
from apply_page_review_certifications import apply, published_hash_sync_allowed


def _item(uid, *, overall="hold", source_hash="old-hash", reasons=None):
    return {
        "source_uid": uid,
        "course_key": "ds",
        "chapter": "章",
        "question_id": "A01",
        "source_hash": source_hash,
        "source_fidelity": "verified" if overall == "certified" else "conflict",
        "answer_validation": "verified" if overall == "certified" else "conflict",
        "overall": overall,
        "reason_codes": list(reasons or (["strict_hold"] if overall == "hold" else [])),
        "q_pages": [1],
        "a_pages": [2],
        "has_image": False,
        "answer_choice": "",
    }


def _ledger():
    items = {
        "u-patch": _item("u-patch"),
        "u-certify": _item("u-certify", source_hash="drift-hash"),
        "u-other": _item("u-other", overall="certified", source_hash="keep", reasons=[]),
    }
    return {
        "schema_version": 1,
        "generated_at": "t",
        "published_hashes": {},
        "courses": {
            "ds": {
                "name": "数据结构",
                "mode": "strict",
                "total": 3,
                "certified": 1,
                "pending": 0,
                "held": 2,
            }
        },
        "summary": {"total": 3, "certified": 1, "pending": 0, "held": 2},
        "items": items,
    }


def _record(uid, action, source_hash, *, verified=True):
    row = {
        "source_uid": uid,
        "final_action": action,
        "source_hash": source_hash,
        "q_pages_viewed": [{"path": "q.png", "sha256": "q"}],
        "a_pages_viewed": [{"path": "a.png", "sha256": "a"}],
        "reviewed_at": "2026-11-05T00:00:00+00:00",
    }
    if action == "patch":
        row["post_patch_verified"] = verified
    return row


def _run(tmp_path, monkeypatch, records, sync_uids, published_index):
    evidence = tmp_path / "evidence.json"
    ledger_path = tmp_path / "ledger.json"
    evidence.write_text(json.dumps({"records": records}), encoding="utf-8")
    ledger_path.write_text(json.dumps(_ledger()), encoding="utf-8")
    saved = {}
    monkeypatch.setattr(apply_mod, "write_outputs", lambda ledger: saved.update(ledger=ledger))
    result = apply(
        evidence,
        ledger_path,
        sync_uids=set(sync_uids),
        published_index=published_index,
    )
    return result, saved["ledger"]


def test_patch_syncs_only_allowlisted_uid_when_evidence_matches_published(tmp_path, monkeypatch):
    published_question = {
        "q_pages": [9, 10],
        "a_pages": [11],
        "has_image": True,
        "image_ref": {"cropped": "crops/ds/page_009_A01.png"},
        "answer": {"choice": None},
    }
    result, ledger = _run(
        tmp_path,
        monkeypatch,
        [
            _record("u-patch", "patch", "published-hash"),
            _record("u-certify", "certify", "published-hash"),
        ],
        {"u-patch"},
        {
            "u-patch": {"hash": "published-hash", "question": published_question},
            "u-certify": {"hash": "published-hash", "question": published_question},
        },
    )
    assert result["synced"] == 1
    assert result["changed"] == 1
    patched = ledger["items"]["u-patch"]
    assert patched["overall"] == "certified"
    assert patched["source_hash"] == "published-hash"
    assert patched["q_pages"] == [9, 10]
    assert patched["a_pages"] == [11]
    assert patched["has_image"] is True
    assert "strict_hold" not in patched["reason_codes"]
    certify = ledger["items"]["u-certify"]
    assert certify["overall"] == "hold"
    assert certify["source_hash"] == "drift-hash"
    other = ledger["items"]["u-other"]
    assert other["overall"] == "certified"
    assert other["source_hash"] == "keep"
    assert "evidence" not in other


def test_sync_rejects_hash_mismatch_and_unverified_patch():
    record = _record("u-patch", "patch", "evidence-hash")
    assert not published_hash_sync_allowed(
        uid="u-patch",
        record=record,
        item_source_hash="old-hash",
        published_hash="other-hash",
        allow_uids={"u-patch"},
    )
    record["post_patch_verified"] = False
    assert not published_hash_sync_allowed(
        uid="u-patch",
        record=record,
        item_source_hash="old-hash",
        published_hash="evidence-hash",
        allow_uids={"u-patch"},
    )
    record["post_patch_verified"] = True
    assert not published_hash_sync_allowed(
        uid="u-other",
        record=record,
        item_source_hash="old-hash",
        published_hash="evidence-hash",
        allow_uids={"u-patch"},
    )
    record["final_action"] = "certify"
    assert not published_hash_sync_allowed(
        uid="u-patch",
        record=record,
        item_source_hash="old-hash",
        published_hash="evidence-hash",
        allow_uids={"u-patch"},
    )
