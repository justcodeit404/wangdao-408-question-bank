"""2026 统考真题增补（data/zhenti/2026.json + 发布态 data-*.json）的一致性校验。

这些题不是原书 OCR，来源是官方原卷与官方答案扫描件，因此不进逐页复核流程，
改为在这里守住三件事：官方答案键、题号/章节落位、题图真实存在。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "zhenti" / "2026.json"
MATH_BANK = ROOT / "math-bank"
DATA_FILES = {
    "ds": MATH_BANK / "data-ds.json",
    "coa": MATH_BANK / "data-coa.json",
    "os": MATH_BANK / "data-os.json",
    "net": MATH_BANK / "data-net.json",
}

# 2026 年官方答案（2027 大纲附录第 88 页）
OFFICIAL_KEY = {
    1: "A", 2: "D", 3: "C", 4: "B", 5: "D", 6: "D", 7: "B", 8: "D", 9: "B", 10: "A",
    11: "A", 12: "C", 13: "A", 14: "B", 15: "A", 16: "D", 17: "A", 18: "C", 19: "A", 20: "A",
    21: "D", 22: "C", 23: "C", 24: "D", 25: "D", 26: "A", 27: "C", 28: "C", 29: "D", 30: "B",
    31: "D", 32: "D", 33: "B", 34: "D", 35: "B", 36: "B", 37: "B", 38: "A", 39: "C", 40: "D",
}
COURSE_COUNTS = {"ds": 13, "coa": 13, "os": 12, "net": 9}
CHOICE_NOS = set(range(1, 41))
ESSAY_NOS = set(range(41, 48))


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def published() -> dict:
    return {
        key: json.loads(path.read_text(encoding="utf-8"))
        for key, path in DATA_FILES.items()
        if path.is_file()
    }


def test_item_count_and_courses(payload: dict):
    items = payload["items"]
    assert len(items) == 47
    counts = {}
    for item in items:
        counts[item["course"]] = counts.get(item["course"], 0) + 1
    assert counts == COURSE_COUNTS


def test_question_numbers_cover_exam_paper(payload: dict):
    nos = [item["no"] for item in payload["items"]]
    assert sorted(nos) == list(range(1, 48))
    for item in payload["items"]:
        expected = CHOICE_NOS if item["type"] == "选择题" else ESSAY_NOS
        assert item["no"] in expected, item["id"]


def test_choice_answers_match_official_key(payload: dict):
    for item in payload["items"]:
        if item["type"] != "选择题":
            continue
        no = item["no"]
        assert item["choice"] == OFFICIAL_KEY[no], f"第 {no} 题答案应为 {OFFICIAL_KEY[no]}"
        assert sorted(item["options"]) == ["A", "B", "C", "D"], f"第 {no} 题选项不全"
        assert item["choice"] in item["options"]


def test_every_item_has_explanation(payload: dict):
    for item in payload["items"]:
        assert item["explanation"].strip(), item["id"]
        assert item["content"].strip(), item["id"]


def test_image_files_exist(payload: dict):
    for item in payload["items"]:
        image = item.get("image")
        if not image:
            continue
        assert (MATH_BANK / image).is_file(), f"{item['id']} 缺题图 {image}"


def test_published_chapters_and_ids(payload: dict, published: dict):
    if not published:
        pytest.skip("发布态 data-*.json 尚未生成（未跑 rebuild_bank）")
    for key, data in published.items():
        chapters = {ch["name"]: ch for ch in data["chapters"]}
        for item in payload["items"]:
            if item["course"] != key:
                continue
            chapter = chapters.get(item["chapter"])
            assert chapter is not None, f"{item['id']} 章节不存在：{item['chapter']}"
            ids = [str(q["id"]) for q in chapter["questions"]]
            assert item["id"] in ids, f"{item['id']} 未进入发布态 {chapter['name']}"
            assert ids.count(item["id"]) == 1, f"{item['id']} 在 {chapter['name']} 内重复"


def test_published_question_carries_source_label(payload: dict, published: dict):
    if not published:
        pytest.skip("发布态 data-*.json 尚未生成（未跑 rebuild_bank）")
    for key, data in published.items():
        for chapter in data["chapters"]:
            for q in chapter["questions"]:
                curated = q.get("curated")
                if not curated or curated.get("year") != 2026:
                    continue
                assert q["page"] is None
                assert q["source_label"] == "2026 统考真题"
                assert curated["source"] == "official"
                assert q["answer"]["choice"] or q["type"] != "选择题"
