import json

from quality_hold import HOLD_PATH, collect_all_hold_uids, collect_hold_uids, source_uid


def _choice(
    qid: str,
    *,
    options: dict[str, str],
    choice: str = "A",
    content: str = "题干",
) -> dict:
    return {
        "id": qid,
        "type": "选择题",
        "content": content,
        "options": options,
        "answer": {"choice": choice, "explanation": "解析"},
    }


def test_source_uid_matches_platform_import_contract():
    assert (
        source_uid("ds", "绪论 · 算法和算法评价 · 选择题", "X08")
        == "408:cs408-ds::绪论 · 算法和算法评价 · 选择题::X08"
    )


def test_collect_hold_uids_when_options_missing_or_duplicated():
    chapter = "章 · 节 · 选择题"
    data = {
        "chapters": [
            {
                "name": chapter,
                "questions": [
                    _choice("X01", options={"A": "1", "B": "2", "C": "3"}),
                    _choice(
                        "X02",
                        options={"A": "同", "B": "同", "C": "3", "D": "4"},
                    ),
                    _choice(
                        "X03",
                        options={"A": "1", "B": "2", "C": "3", "D": "4"},
                        choice="B",
                    ),
                ],
            }
        ]
    }
    uids = collect_hold_uids("ds", data)
    assert source_uid("ds", chapter, "X01") in uids
    assert source_uid("ds", chapter, "X02") in uids
    assert source_uid("ds", chapter, "X03") not in uids


def test_collect_hold_uids_skips_essay_without_choice():
    data = {
        "chapters": [
            {
                "name": "章 · 节 · 解答题",
                "questions": [
                    {
                        "id": "A01",
                        "type": "解答题",
                        "content": "证明题",
                        "options": {},
                        "answer": {"choice": "", "explanation": ""},
                    }
                ],
            }
        ]
    }
    assert collect_hold_uids("net", data) == frozenset()


def test_published_hold_covers_collector():
    # 2026-09 起发布数据结构性破损已清零（收集器返回空集属健康状态），
    # 金丝雀改为：4 科发布 JSON 必须都真实扫描到，且扫描结果被 hold 清单覆盖。
    for course_key in ("ds", "coa", "net", "os"):
        assert (HOLD_PATH.parent / f"data-{course_key}.json").is_file()
    hold = json.loads(HOLD_PATH.read_text(encoding="utf-8"))
    expected = collect_all_hold_uids()
    assert expected <= set(hold["source_uids"])
