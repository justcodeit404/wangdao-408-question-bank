import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import COURSES
from vision_quality_gate import _rows, answer_crop, question_crop

root = Path(r"C:\Users\16416\Desktop\考研\apps\temp\408-vision-audit\claude-local-r3")
worklist = json.loads((root / "worklist.json").read_text(encoding="utf-8"))
unread: set[str] = set()
for index in range(8):
    payload = json.loads((root / f"transcript-{index:02d}.json").read_text(encoding="utf-8"))
    for row in payload.get("transcripts") or []:
        if not row.get("readable"):
            unread.add(row["source_uid"])

lookup = {}
for course in COURSES:
    data = json.loads(Path(course.out_json).read_text(encoding="utf-8"))
    for rows in _rows(course.key, data).values():
        for row in rows:
            lookup[row["source_uid"]] = row

crop_dir = root / "crops-fixed"
out = []
fail = []
for uid in sorted(unread):
    row = lookup[uid]
    try:
        question = question_crop(row["course_key"], row, crop_dir, 48)
        answer = answer_crop(row["course_key"], row, crop_dir, 36)
    except Exception as exc:
        fail.append((uid, str(exc)))
        print("FAIL", uid, exc)
        continue
    item = dict(next(entry for entry in worklist["items"] if entry["source_uid"] == uid))
    item["question_crop"] = str(question.path)
    item["answer_crop"] = str(answer.path)
    item["answer_page"] = answer.page
    out.append(item)
    print("ok", uid, "apage", answer.page)

(root / "worklist-fixed.json").write_text(json.dumps({"items": out}, ensure_ascii=False, indent=2), encoding="utf-8")
print("ok", len(out), "fail", len(fail))
