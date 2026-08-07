#!/usr/bin/env python3
"""从 OCR 补全网络科重抽后缺失的 5 道综合应用题解析。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PATH = ROOT / "output" / "questions_net.json"
OCR = ROOT / "data" / "ocr" / "net"


def page_text(pn: int) -> str:
    p = OCR / f"page_{pn:03d}.json"
    if not p.exists():
        return ""
    d = json.loads(p.read_text(encoding="utf-8"))
    return "\n".join(b.get("text", "") for b in d.get("blocks", []))


def extract_between(pages: list[int], start_pat: str, end_pat: str | None = None) -> str:
    text = "\n".join(page_text(p) for p in pages)
    m = re.search(start_pat, text)
    if not m:
        return ""
    rest = text[m.end() :]
    if end_pat:
        m2 = re.search(end_pat, rest)
        if m2:
            rest = rest[: m2.start()]
    return rest.strip()


# (chapter name contains, q id, stem keywords, explanation)
PATCHES = []


def build_patches():
    # A02 局域网带宽
    expl = extract_between(
        list(range(19, 22)),
        r"传播时延\s*=\s*2",
        r"03．【解答】|03\.【解答】|1\.2计算机网络",
    )
    if not expl:
        expl = (
            "传播时延=2×10³m÷(2×10⁸m/s)=10μs。\n"
            "1）分组大小为100B：带宽 x=100B÷10μs=80Mb/s。\n"
            "2）分组大小为512B：带宽 y=512B÷10μs=409.6Mb/s。\n"
            "因此，带宽应分别等于80Mb/s和409.6Mb/s。"
        )
    else:
        expl = "传播时延=2" + expl  # restore start
    PATCHES.append(("计算机网络概述", "A02", "2km", expl))

    # A05 UDP 分片
    expl = extract_between(
        list(range(239, 243)),
        r"以太网帧的数据段的最大长度是1500B，UDP用户数据报的首部是8B",
        r"5\.3\s*TCP|5\.3TCP",
    )
    if not expl:
        expl = (
            "以太网帧数据段最大1500B，UDP首部8B，IP首部20B。"
            "UDP数据8192B+8B=8200B，应划分为6个IP报片。"
            "数据长度分别为1480×5+800B，片偏移0,185,370,555,740,925。"
        )
    else:
        expl = "以太网帧的数据段的最大长度是1500B，UDP用户数据报的首部是8B" + expl
    PATCHES.append(("UDP", "A05", "8192B", expl))

    # A05 2021 统考
    expl = extract_between(
        list(range(306, 309)),
        r"04．【解答】|04\.【解答】",
        r"6\.6\s*本章小结|05．【解答】|05\.【解答】",
    )
    if expl:
        PATCHES.append(("万维网", "A05", "2021统考真题", expl))

    # A08 2017 GBN - search 08.【解答】 in a_pages range
    expl = extract_between(
        list(range(80, 88)),
        r"08．【解答】|08\.【解答】",
        r"09．【解答】|09\.【解答】|3\.5",
    )
    if expl:
        PATCHES.append(("流量控制与可靠传输机制", "A08", "2017统考真题", expl))

    # A07 2024
    expl = extract_between(
        list(range(208, 215)),
        r"07．【解答】|07\.【解答】|2024统考真题",
        r"08．【解答】|08\.【解答】|4\.5|4\.6",
    )
    # may match wrong - refine by keyword 第五疆域 in nearby question not answer
    if expl and ("路由" in expl or "OSPF" in expl or "距离向量" in expl or "链路状态" in expl):
        PATCHES.append(("路由算法与路由协议", "A07", "2024统考真题", expl))


def main():
    build_patches()
    data = json.loads(PATH.read_text(encoding="utf-8"))
    filled = 0
    for ch in data.get("chapters", []):
        ch_name = ch.get("name") or ""
        for q in ch.get("questions", []):
            ans = q.get("answer") or {}
            if (ans.get("choice") or "").strip() or (ans.get("explanation") or "").strip():
                continue
            qid = q.get("id")
            stem = q.get("content") or ""
            for ch_key, pid, stem_key, expl in PATCHES:
                if qid != pid:
                    continue
                if ch_key not in ch_name:
                    continue
                if stem_key not in stem:
                    continue
                q["answer"] = {"choice": None, "explanation": expl.strip()}
                filled += 1
                print(f"filled {qid} in {ch_name} expl_len={len(expl)}")
                break
    data["total_questions"] = sum(ch.get("question_count", len(ch.get("questions", []))) for ch in data.get("chapters", []))
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"filled={filled} total_patches={len(PATCHES)}")


if __name__ == "__main__":
    main()
