import json

from page_review_queue import sync_queue


def test_sync_queue_marks_patch_certified_and_stale(tmp_path):
    chapter = "章节 · 选择题"
    uid = f"408:cs408-ds::{chapter}::X01"
    queue = {
        "items": [{"source_uid": uid, "source_hash": "old", "status": "ready"},
                  {"source_uid": "u2", "source_hash": "same", "status": "ready"}]
    }
    ledger = {"items": {
        uid: {"source_hash": "new", "overall": "certified"},
        "u2": {"source_hash": "different", "overall": "hold"},
    }}
    patches = {"items": [{"course": "ds", "chapter": chapter, "qid": "X01", "fields": {"choice": "A"}}]}
    evidence = {"records": []}
    paths = {}
    for name, value in (("queue.json", queue), ("ledger.json", ledger), ("patches.json", patches), ("evidence.json", evidence)):
        path = tmp_path / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        paths[name] = path
    counts = sync_queue(paths["queue.json"], paths["ledger.json"], paths["patches.json"], paths["evidence.json"])
    saved = json.loads(paths["queue.json"].read_text(encoding="utf-8"))
    assert saved["items"][0]["status"] == "patched_certified"
    assert saved["items"][0]["source_hash"] == "new"
    assert saved["items"][1]["status"] == "stale"
    assert counts["patched_certified"] == 1
    assert counts["stale"] == 1
