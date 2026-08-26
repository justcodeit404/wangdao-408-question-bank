import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "luna_audit_queue.py"
spec = importlib.util.spec_from_file_location("luna_audit_queue", SCRIPT)
luna = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(luna)


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "math-bank"
    root.mkdir()
    q1 = {
        "id": "X01",
        "type": "选择题",
        "content": "1+1=?",
        "options": {"A": "1", "B": "2"},
        "answer": {"choice": "B", "explanation": "加法", "a_pages": [99]},
        "q_pages": [1],
        "a_pages": [2],
        "has_image": True,
        "image_ref": {
            "cropped": "crops/ds/x.png",
            "box": [1, 2, 3, 4],
            "note": "answer page",
        },
    }
    q2 = {
        "id": "X02",
        "type": "选择题",
        "content": "2+2=?",
        "options": {"A": "3", "B": "4"},
        "answer": {"choice": "B", "explanation": "加法"},
        "q_pages": [3],
        "a_pages": [4],
    }
    data = {"chapters": [{"name": "第一章 · 小节 · 选择题", "questions": [q1, q2]}]}
    for course in luna.COURSES:
        (root / f"data-{course}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    uid = luna.source_uid("ds", "第一章 · 小节 · 选择题", "X01")
    uid2 = luna.source_uid("ds", "第一章 · 小节 · 选择题", "X02")
    ledger = {
        "items": {
            uid: {
                "source_uid": uid,
                "course_key": "ds",
                "overall": "hold",
                "reason_codes": ["vision_conflict"],
                "source_fidelity": "conflict",
            },
            uid2: {
                "source_uid": uid2,
                "course_key": "ds",
                "overall": "pending",
                "reason_codes": [],
                "source_fidelity": "verified",
            },
        }
    }
    (root / "quality-ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
    )
    return root


def test_blind_packet_has_no_answer_or_answer_page_leak(tmp_path):
    root = _fixture(tmp_path)
    row = luna.iter_questions(root, ["ds"])[0]
    packet = luna.make_blind_packet(row, "p1")
    text = json.dumps(packet, ensure_ascii=False).lower()
    assert "answer" not in text
    assert "explanation" not in text
    assert "a_pages" not in text
    assert "question_hash" in packet and "packet_hash" in packet
    assert "source_hash" in packet and packet["source_hash"] == row["source_hash"]
    assert packet["question"].get("q_pages") == [1]
    assert packet["question"].get("question_image") == "crops/ds/x.png"
    assert packet["course"] == "ds" and packet["pass_id"] == "p1"


def test_uid_and_question_hash_are_deterministic_and_answer_independent(tmp_path):
    root = _fixture(tmp_path)
    row = luna.iter_questions(root, ["ds"])[0]
    q = dict(row["question"])
    before = luna.question_hash(q, row["source_uid"])
    q["answer"] = {"choice": "A", "explanation": "changed"}
    q["a_pages"] = [777]
    assert luna.source_uid("ds", row["chapter"], "X01") == row["source_uid"]
    assert luna.question_hash(q, row["source_uid"]) == before
    row2 = [
        x
        for x in luna.iter_questions(root, ["ds"])
        if x["source_uid"].endswith("::X02")
    ][0]
    assert row2["source_hash"] == luna.source_hash(row2["question"])


def test_batch_sharding_is_stable(tmp_path):
    root = _fixture(tmp_path)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    s1 = luna.initialize(
        root=root, output_dir=out1, courses=["ds"], pass_id="p", batch_size=1
    )
    s2 = luna.initialize(
        root=root, output_dir=out2, courses=["ds"], pass_id="p", batch_size=1
    )
    assert s1["queue_hash"] == s2["queue_hash"]
    luna.resume(root=root, output_dir=out1, pass_id="p")
    luna.resume(root=root, output_dir=out2, pass_id="p")
    b1 = json.loads(
        (out1 / "blind" / "p" / "batch-0001.json").read_text(encoding="utf-8")
    )
    b2 = json.loads(
        (out2 / "blind" / "p" / "batch-0001.json").read_text(encoding="utf-8")
    )
    assert b1 == b2


def test_resume_advances_cursor_without_duplicates(tmp_path):
    root = _fixture(tmp_path)
    out = tmp_path / "out"
    luna.initialize(
        root=root, output_dir=out, courses=["ds"], pass_id="p", batch_size=1
    )
    first = luna.resume(root=root, output_dir=out, pass_id="p")
    second = luna.resume(root=root, output_dir=out, pass_id="p")
    assert first["next_index"] == 1
    assert second["next_index"] == 2
    assert second["status"] == "complete"
    assert len(second["batches"]) == 2
    a = json.loads(
        (out / "blind" / "p" / "batch-0001.json").read_text(encoding="utf-8")
    )
    b = json.loads(
        (out / "blind" / "p" / "batch-0002.json").read_text(encoding="utf-8")
    )
    assert a["items"][0]["source_uid"] != b["items"][0]["source_uid"]


def test_resume_rejects_a_cursor_that_would_reemit_an_existing_uid(tmp_path):
    root = _fixture(tmp_path)
    out = tmp_path / "out"
    luna.initialize(
        root=root, output_dir=out, courses=["ds"], pass_id="p", batch_size=1
    )
    luna.resume(root=root, output_dir=out, pass_id="p")
    batch_path = out / "blind" / "p" / "batch-0001.json"
    original = batch_path.read_text(encoding="utf-8")
    state_path = out / "state-p.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["next_index"] = 0
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="already emitted"):
        luna.resume(root=root, output_dir=out, pass_id="p")
    assert batch_path.read_text(encoding="utf-8") == original


def test_visual_packet_keeps_published_snapshot_and_pages(tmp_path):
    root = _fixture(tmp_path)
    row = luna.iter_questions(root, ["ds"])[0]
    packet = luna.make_visual_packet(row, "p1")
    assert packet["source_hash"] == row["source_hash"]
    assert packet["visual"]["question"]["answer"]["explanation"] == "加法"
    assert packet["visual"]["q_pages"] == [1]
    assert packet["visual"]["a_pages"] == [2]
    assert packet["visual"]["question_image"]["cropped"] == "crops/ds/x.png"


def test_visual_queue_excludes_low_risk_items(tmp_path):
    root = _fixture(tmp_path)
    state = luna.initialize(
        root=root,
        output_dir=tmp_path / "out",
        courses=["ds"],
        pass_id="visual",
        kind="visual",
        batch_size=8,
    )
    assert len(state["items"]) == 1
    assert state["items"][0]["risk_tier"] != "low"


def test_batch_has_own_hash_and_visual_default_is_eight(tmp_path):
    root = _fixture(tmp_path)
    out = tmp_path / "out"
    state = luna.initialize(
        root=root, output_dir=out, courses=["ds"], pass_id="v", kind="visual"
    )
    assert state["batch_size"] == 8
    luna.resume(root=root, output_dir=out, pass_id="v")
    packet = json.loads(
        (out / "visual" / "v" / "batch-0001.json").read_text(encoding="utf-8")
    )
    payload = {k: v for k, v in packet.items() if k != "packet_hash"}
    payload["items"] = [
        {k: v for k, v in item.items() if k != "packet_hash"}
        for item in packet["items"]
    ]
    assert packet["packet_hash"] == luna._sha(payload)
    assert all(item["packet_hash"] == packet["packet_hash"] for item in packet["items"])
    assert all(item["item_hash"] for item in packet["items"])


def test_validate_batch_rejects_missing_packet_hash_and_stale_source_hash(tmp_path):
    root = _fixture(tmp_path)
    row = luna.iter_questions(root, ["ds"])[0]
    packet = luna._batch_packet(
        "blind-solution-batch",
        "p",
        "batch-0001",
        [
            luna.make_blind_packet(row, "p"),
        ],
    )
    packet.pop("packet_hash")
    with pytest.raises(ValueError, match="packet_hash"):
        luna.validate_batch(packet)
    packet = luna._batch_packet(
        "blind-solution-batch",
        "p",
        "batch-0001",
        [
            luna.make_blind_packet(row, "p"),
        ],
    )
    with pytest.raises(ValueError, match="source_hash mismatch"):
        luna.validate_batch(packet, {row["source_uid"]: "stale-hash"})


def test_initialize_rejects_duplicate_published_uids(tmp_path):
    root = _fixture(tmp_path)
    data_path = root / "data-ds.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    data["chapters"][0]["questions"].append(data["chapters"][0]["questions"][0])
    data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate source_uid"):
        luna.initialize(
            root=root, output_dir=tmp_path / "out", courses=["ds"], pass_id="p"
        )


def test_default_queue_reports_but_omits_untracked_rows(tmp_path):
    root = _fixture(tmp_path)
    # Add a published question without a ledger record.
    data_path = root / "data-ds.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    data["chapters"][0]["questions"].append(
        {
            "id": "X99",
            "type": "选择题",
            "content": "未跟踪",
            "options": {"A": "A"},
            "answer": {"choice": "A"},
        }
    )
    data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert all(
        "::X99" not in row["source_uid"] for row in luna.iter_questions(root, ["ds"])
    )
    report = luna.untracked_report(root, ["ds"])
    assert any(row["source_uid"].endswith("::X99") for row in report)
    state = luna.initialize(
        root=root, output_dir=tmp_path / "out", courses=["ds"], pass_id="p"
    )
    assert state["omitted_untracked"] == 1
    assert any(uid.endswith("::X99") for uid in state["omitted_uids"])
