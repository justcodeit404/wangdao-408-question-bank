#!/usr/bin/env python3
"""规范化题库文本中的 OCR 遗留空格（保守、幂等、只删不增）。

根因：王道 PDF 内嵌文本层由扫描+OCR 生成，自带莫名空格（如
"V= {V1,V2, V3"、"选项 C 同时"）；viewer 把 \n 渲染成换行/空格后更加显眼。
原书的数学/代码排版空隙（如 "V = {v1, v2"、"Pop(st, x)"）由 OCR 不一致地
保留了一部分，统一按数字排版惯例去掉（tests 锁定的策展文本语义除外）。

规则（separator = 单个空格/制表符/换行；连续分隔符不动；只删不增）：
  R1  CJK ↔ sep ↔ CJK            → 删（「其 关键」「（ ）」）
  R2  CJK ↔ sep ↔ ASCII 字母数字 → 删（「选项 C」→「选项C」、「即 t≤n」→「即t≤n」）
  R3  , ; = 后 sep 接 字母数字/开括号/引号 → 删（「V= {」→「V={」、「V1, V3」→「V1,V3」）
      守卫：逗号在函数调用括号内（"Pop(st, x)"）保留；逗号不在任何括号内且
            前一 token 为 ≥3 个纯字母（"add xaddr, 3"）保留；分号前一非空
            字符是 ')'（代码语句结束 "…); Next"）保留
  R5  字母数字/闭括号/引号 后 sep 接 , ; = → 删（「n = 0」→「n=0」）

结构保护（分隔符一律不删）：
  - 「题目图片：」「答案图片：」引用整行（lib/helpers 依赖行结构）
  - 选项标签 A. / A、 / b) / 罗马数字 II. / III． 等前的分隔符
    （原书有意义的排版分隔，如「电路交换 B.报文交换」「临界区⏎III.…」）

绝不删：两个 ASCII 字母之间的空格（保护 int n、英文单词）。

用法：
  python scripts/normalize_spaces.py                # dry-run，出统计+报告
  python scripts/normalize_spaces.py --apply        # 就地写回四个课程 questions.json
  python scripts/normalize_spaces.py --course ds    # 只处理某门课
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import COURSES, REPO_ROOT  # noqa: E402
from utils import write_json_atomic  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

_CJK_RANGES = (
    (0x2E80, 0x303F), (0x3400, 0x4DBF), (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF), (0xFF00, 0xFFEF),
)
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_OPEN = "<[{(\""
_CLOSE_QUOT = ")]}>\"'”’"
_PUNCT3 = ",;="

# 结构保护：选项标签（A. / A、 / b)）、罗马数字（II. / IV．）、圈码 ①-⑩、
# （n）/(n) 序号前的分隔符不删
_LABEL_RX = re.compile(
    r"[ \t\n]+(?=(?:[A-Da-d][\.、．)]|"
    r"(?:X|IX|IV|V?I{1,3})[\.、．)]|"
    r"[①②③④⑤⑥⑦⑧⑨⑩]|\([0-9]+\)|（[0-9]+）))")

IMAGE_REF_RE = re.compile(r"^[ \t]*(题目图片|答案图片)：[^\n]*$", re.M)

_PLACEHOLDER = "\ue000REF{}\ue001"


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in _CJK_RANGES)


def _enclosing_table(text: str) -> "list[str | None]":
    """返回每个位置的前置最内层开括号（忽略不配对的残键）。"""
    table: "list[str | None]" = []
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{", ">": "<"}
    for ch in text:
        table.append(stack[-1] if stack else None)
        if ch in "([{<":
            stack.append(ch)
        elif ch in ")]}>":
            if stack and stack[-1] == pairs[ch]:
                stack.pop()
            elif ch in stack:  # 容错：弹到匹配处
                while stack and stack[-1] != pairs[ch]:
                    stack.pop()
                if stack:
                    stack.pop()
    return table


def _prev_token(text: str, pos: int) -> str:
    """取 pos 之前紧邻的字母数字 token（跳过空白）。"""
    j = pos - 1
    while j >= 0 and text[j] in " \t\n":
        j -= 1
    end = j + 1
    while j >= 0 and (text[j] in _ALNUM):
        j -= 1
    return text[j + 1:end]


def normalize_text(s: str) -> "tuple[str, Counter]":
    """对单个字符串应用全部规则，返回 (新文本, 各规则命中次数)。"""
    counts: Counter = Counter()
    if not s:
        return s, counts
    refs: list[str] = []

    def _stash(m: "re.Match[str]") -> str:
        refs.append(m.group(0))
        return _PLACEHOLDER.format(len(refs) - 1)

    text = IMAGE_REF_RE.sub(_stash, s)
    protected = {m.end() - 1 for m in _LABEL_RX.finditer(text)}
    enc = _enclosing_table(text)

    out: list[str] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch in " \t\n":
            j = i
            while j < n and text[j] in " \t\n":
                j += 1
            if j - i == 1:
                prev = text[i - 1] if i > 0 else ""
                nxt = text[j] if j < n else ""
                rule = None
                if prev and nxt:
                    if _is_cjk(prev) and _is_cjk(nxt):
                        rule = "R1_cjk_cjk"
                    elif _is_cjk(prev) and nxt in _ALNUM:
                        rule = "R2_cjk_alnum"
                    elif prev in _ALNUM and _is_cjk(nxt):
                        rule = "R2_alnum_cjk"
                    elif prev in _PUNCT3 and (
                            nxt in _ALNUM or nxt in _OPEN or nxt in _CLOSE_QUOT):
                        rule = "R3_punct_alnum"
                        if prev == ",":
                            e = enc[i - 1] if i - 1 < len(enc) else None
                            if e == "(" and i >= 2 and text[i - 2].isalpha():
                                rule = None  # 函数调用实参 "Pop(st, x)"
                            elif e is None:
                                tok = _prev_token(text, i - 1)
                                if len(tok) >= 3 and tok.isalpha():
                                    rule = None  # 指令助记符 "add xaddr, 3"
                        elif prev == ";":
                            k = i - 2
                            while k >= 0 and text[k] in " \t\n":
                                k -= 1
                            if k >= 0 and text[k] == ")":
                                rule = None  # 代码语句结束 "…); Push"
                    elif prev in _ALNUM + _CLOSE_QUOT and nxt in _PUNCT3:
                        rule = "R5_alnum_punct"
                    elif (prev in _ALNUM and nxt in "(<" and j + 1 < n
                            and (text[j + 1] in _ALNUM or _is_cjk(text[j + 1]))):
                        # "O (n" / "f (x" → "O(n" / "f(x"；
                        # "return ((" 后随开括号则保留（R4 守卫）
                        rule = "R4_alnum_open"
                if rule and i not in protected:
                    counts[rule] += 1
                    i = j
                    continue
            out.append(text[i:j])
            i = j
            continue
        out.append(ch)
        i += 1

    result = "".join(out)
    if refs:
        result = re.sub(
            re.escape(_PLACEHOLDER).replace(r"\{\}", r"(\d+)"),
            lambda m: refs[int(m.group(1))],
            result,
        )
    return result, counts


def iter_text_fields(q: dict):
    """产出可写字段 (container, key)。"""
    yield q, "content"
    opts = q.get("options")
    if isinstance(opts, dict):
        for k in opts:
            yield opts, k
    ans = q.get("answer") or {}
    if isinstance(ans, dict):
        yield ans, "explanation"
    for sq in q.get("sub_questions") or []:
        if isinstance(sq, dict):
            yield from iter_text_fields(sq)


def normalize_questions(data: dict) -> "tuple[int, Counter, list]":
    """就地规范化整门课数据；返回 (改动题数, 规则计数, 改动样本)。"""
    changed = 0
    total: Counter = Counter()
    samples: list = []
    for ch in data.get("chapters", []):
        for q in ch.get("questions", []):
            qc: Counter = Counter()
            diff_parts = []
            for container, key in iter_text_fields(q):
                old = container.get(key)
                if not isinstance(old, str) or not old:
                    continue
                new, counts = normalize_text(old)
                if new != old:
                    container[key] = new
                    qc.update(counts)
                    if len(diff_parts) < 2:
                        for i in range(min(len(old), len(new))):
                            if old[i] != new[i]:
                                diff_parts.append(
                                    old[max(0, i - 15): i + 15].replace("\n", "⏎")
                                    + "  ==>  "
                                    + new[max(0, i - 15): i + 15].replace("\n", "⏎")
                                )
                                break
            if qc:
                changed += 1
                total.update(qc)
                if len(samples) < 200:
                    samples.append({
                        "id": q.get("id"),
                        "page": q.get("page"),
                        "counts": dict(qc),
                        "diff": diff_parts[:1],
                    })
    return changed, total, samples


def main() -> None:
    ap = argparse.ArgumentParser(description="规范化题库文本空格（幂等）")
    ap.add_argument("--apply", action="store_true", help="就地写回（默认 dry-run）")
    ap.add_argument("--course", default="", help="逗号分隔课程 key（默认全部存在的）")
    ap.add_argument("--report", default="",
                    help="dry-run 报告输出路径（默认 temp/normalize_spaces_report.json）")
    args = ap.parse_args()

    keys = [k.strip() for k in args.course.split(",") if k.strip()] or None
    report_path = Path(args.report) if args.report else (
        REPO_ROOT / "temp" / "normalize_spaces_report.json")

    grand = Counter()
    grand_changed = 0
    all_samples = []
    for c in COURSES:
        if keys and c.key not in keys:
            continue
        path = Path(c.out_json)
        if not path.exists():
            print(f"  [skip] {c.key}: {path} 不存在")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        changed, counts, samples = normalize_questions(data)
        grand.update(counts)
        grand_changed += changed
        print(f"  [{c.key}] 改动 {changed} 题, 规则命中 {dict(counts)}")
        for s in samples[:5]:
            print(f"      示例 {s['id']} (p{s['page']}): {s['diff']}")
        for s in samples:
            s["course"] = c.key
        all_samples.extend(samples)
        if args.apply and changed:
            write_json_atomic(path, data, indent=1)
            print(f"  [{c.key}] 已写回 {path}")

    print(f"合计: 改动 {grand_changed} 题, 规则命中 {dict(grand)}")
    if not args.apply:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps({"changed_questions": grand_changed,
                        "rule_hits": dict(grand),
                        "samples": all_samples}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"dry-run 报告: {report_path}")


if __name__ == "__main__":
    main()
