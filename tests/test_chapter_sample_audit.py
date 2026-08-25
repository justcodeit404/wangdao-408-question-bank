from chapter_sample_audit import build_batch, sample_major_chapter


def _rows(count: int):
    return [
        {"source_uid": f"uid-{index}", "question": {"page": index + 1, "id": f"X{index + 1:02d}"}}
        for index in range(count)
    ]


def test_stratified_sample_is_stable_and_covers_source_order():
    rows = _rows(100)
    first = sample_major_chapter(rows, 5, "round-a")
    second = sample_major_chapter(rows, 5, "round-a")
    assert [item["source_uid"] for item in first] == [item["source_uid"] for item in second]
    assert [item["stratum"] for item in first] == [1, 2, 3, 4, 5]
    for index, item in enumerate(first):
        source_index = int(item["source_uid"].split("-")[1])
        assert index * 20 <= source_index < (index + 1) * 20


def test_current_published_bank_yields_five_samples_for_all_major_chapters():
    batch = build_batch(per_chapter=5, round_id="test-baseline")
    assert batch["summary"]["courses"] == 4
    assert batch["summary"]["major_chapters"] == 26
    assert batch["summary"]["sampled"] == 130
    assert all(
        chapter["sample_count"] == 5
        for course in batch["courses"]
        for chapter in course["chapters"]
    )
