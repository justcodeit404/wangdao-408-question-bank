import json
from pathlib import Path

import pytest

from fix_questions import fix_file, load_page_review_patches

BANK = Path(__file__).resolve().parents[1] / "math-bank"


def _load(course: str) -> dict:
    return json.loads((BANK / f"data-{course}.json").read_text(encoding="utf-8"))


def _q(course: str, chapter_part: str, qid: str) -> dict:
    data = _load(course)
    for chapter in data["chapters"]:
        if chapter_part in str(chapter.get("name") or "") and "选择" in str(
            chapter.get("name") or ""
        ):
            for question in chapter["questions"]:
                if question.get("id") == qid:
                    return question
    raise AssertionError(f"missing {course} {qid}")


def test_coa_trap_has_split_option_d():
    question = _q("coa", "异常和中断机制", "X01")
    assert "D" in question["options"]
    assert "内核" in question["options"]["D"]
    assert "异常情况" in question["options"]["C"]
    assert question["options"]["C"] != question["options"]["D"]


def test_coa_visible_registers_options_and_answer():
    question = _q("coa", "控制器的功能和工作原理", "X26")
    assert question["options"]["B"] != question["options"]["C"]
    assert "III" in question["options"]["C"]
    assert question["answer"]["choice"] == "B"


def test_ds_scan_star_stem_not_truncated():
    question = _q("ds", "栈和队列的应用", "X14")
    assert "当扫描到" in question["content"]
    assert "*" in question["content"]


def test_ds_circular_queue_end_pointers_not_duplicated():
    question = _q("ds", " · 队列 · ", "X22")
    assert question["options"]["A"] != question["options"]["B"]
    assert "end1==end2" in question["options"]["A"]


def test_ds_2012_preorder_uses_latin_a_not_alpha():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X35")
    assert "α" not in question["content"]
    assert "a,e,b,d,c" in question["content"].replace(" ", "")
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "b,c,d,e,a" in compact


def test_ds_x12_preorder_uses_latin_a_not_alpha():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X12")
    assert "α" not in question["content"]
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "先序序列是" in compact
    assert "a...b" in compact or "a.…b" in compact or "...a..." in compact
    assert "b" in compact
    for option in question["options"].values():
        assert "α" not in option


def test_ds_x33_2010_threaded_tree_stem_not_ocr_null():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X33")
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "Null" not in question["content"]
    assert "A.B.C" not in compact
    assert "后序线索树定义的是" in compact
    assert question.get("has_image") is True
    assert (question.get("image_ref") or {}).get("cropped") == "crops/ds/page_154_X33.png"
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "题目图片：crops/ds/page_154_X33.png" in expl


def test_ds_2022_inorder_neighbors_split_roman_items():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X41")
    content = question["content"]
    assert "Iq是p的双亲" not in content
    assert "I. q是p的双亲" in content
    assert "II. q是p的右孩子" in content
    assert "III. q是p的右兄弟" in content
    assert "IV. q是p的双亲的双亲" in content
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "α是p的双亲" not in expl
    assert "{p,9)" not in expl
    assert "{p,q}" in expl
    assert "说法III不可能" in expl
    assert expl.rstrip().endswith("说法III不可能。")


def test_ds_2024_inorder_uses_q_not_nine():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X43")
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "P,V,9" not in compact
    assert "p,v,q" in compact
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "因此g不存在" not in expl
    assert "因此q不存在" in expl


def test_ds_forest_x01_roman_items_and_floor_log():
    question = _q("ds", "树、森林", "X01")
    content = question["content"]
    assert "I对于" not in content
    assert "I. 对于有n个结点的二叉树，其高度为 ⌊log₂ n⌋" in content
    assert "II. 完全二叉树中，若一个结点没有左孩子，则它必是叶结点" in content
    assert "III. 高度为h（h>0）的完全二叉树对应的森林所含的树的个数一定是h" in content
    assert "\u2028IV. 一棵树中的叶子数一定等于与其对应的二叉树的叶子数" in content
    assert content.count("III.") == 1
    assert "log2n" not in content.replace(" ", "")
    patches = load_page_review_patches()
    fields = patches[("ds", "树与二叉树 · 树、森林 · 选择题", "X01")]
    assert fields["content"] == content
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "答案图片：crops/ds/page_181_X01_1.png" in expl
    assert "答案图片：crops/ds/page_181_X01_2.png" in expl
    assert expl == fields["explanation"]
    crop_dir = BANK / "crops" / "ds"
    assert (crop_dir / "page_181_X01_1.png").is_file()
    assert (crop_dir / "page_181_X01_2.png").is_file()


def test_page_review_manifest_is_valid_and_unique():
    patches = load_page_review_patches()
    assert len(patches) == 52
    assert all(len(key) == 3 for key in patches)


def test_page_review_manifest_is_applied_by_fix_file(tmp_path):
    (course, chapter, qid), fields = next(iter(load_page_review_patches().items()))
    path = tmp_path / f"questions_{course}.json"
    path.write_text(
        json.dumps(
            {
                "chapters": [
                    {
                        "name": chapter,
                        "questions": [
                            {
                                "id": qid,
                                "type": "选择题",
                                "content": "old",
                                "options": {"A": "a", "B": "b", "C": "old-c", "D": "old-d"},
                                "answer": {"choice": "A", "explanation": "old"},
                            }
                        ],
                        "question_count": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fix_file(path, pdf_images_dir=tmp_path, course_key=course, apply_page_review_patches=True)
    question = json.loads(path.read_text(encoding="utf-8"))["chapters"][0]["questions"][0]
    for key, value in fields.get("options", {}).items():
        assert question["options"][key] == value


def test_page_review_manifest_rejects_duplicate_target(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data" / "quality" / "page_review_patches.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["items"].append(payload["items"][0])
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate page review patch target"):
        load_page_review_patches(path)
