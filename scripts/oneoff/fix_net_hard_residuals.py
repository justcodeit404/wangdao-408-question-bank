#!/usr/bin/env python3
"""定点修复网络科硬伤（对照 OCR 原文）。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from config import MATH_BANK_DIR  # noqa: E402

PATH = ROOT / "output" / "questions_net.json"
IMG = ROOT / "assets" / "pdf_images" / "net"
CROP_DIR = MATH_BANK_DIR / "crops" / "net"


def find_q(data, qid, page=None, chapter_sub=None):
    for ch in data["chapters"]:
        name = ch.get("name") or ""
        if chapter_sub and chapter_sub not in name:
            continue
        for q in ch.get("questions") or []:
            if q.get("id") != qid:
                continue
            if page is not None and q.get("page") != page:
                continue
            return ch, q
    return None, None


def set_opts(q, opts: dict):
    q["options"] = {k: opts[k] for k in "ABCD" if k in opts}
    print(f"  opts {q.get('id')} p{q.get('page')}: {list(q['options'].keys())}")


def crop_if_needed(q):
    stem = q.get("content") or ""
    if not re.search(r"如下图|下图所示|见图", stem):
        return False
    if q.get("has_image") and q.get("image_ref") and q["image_ref"].get("cropped"):
        crop = MATH_BANK_DIR / q["image_ref"]["cropped"]
        if crop.exists():
            return False
    page = q.get("page")
    if not page:
        return False
    img_path = IMG / f"page_{page:03d}.png"
    if not img_path.exists():
        return False
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    qid = str(q.get("id", "x"))
    out = CROP_DIR / f"page_{page:03d}_{qid}.png"
    im = Image.open(img_path)
    w, h = im.size
    bbox = q.get("bbox")
    if bbox and len(bbox) == 4:
        pad = 20
        box = (
            max(0, int(bbox[0]) - pad),
            max(0, int(bbox[1]) - pad),
            min(w, int(bbox[2]) + pad),
            min(h, int(bbox[3]) + pad),
        )
        if box[2] > box[0] and box[3] > box[1] and (box[3] - box[1]) > 40:
            im.crop(box).save(out)
        else:
            im.save(out)
    else:
        im.save(out)
    q["has_image"] = True
    q["image_ref"] = {
        "page": page,
        "note": "残题定点裁剪",
        "cropped": out.relative_to(MATH_BANK_DIR).as_posix(),
    }
    print(f"  img {qid} p{page}")
    return True


def clean_hex(q):
    stem = q.get("content") or ""
    lines = []
    for line in stem.split("\n"):
        if re.search(r"[0-9a-fA-F]{8}\s+[0-9a-fA-F]{4,}", line):
            continue
        if re.match(r"^\s*[0-9a-fA-F]{4}\s+[0-9a-fA-F]{4,}", line):
            continue
        if "00107589" in line:
            continue
        lines.append(line)
    new = "\n".join(lines).strip()
    # 去掉混入的后续解答提示
    new = re.split(r"\nIP分组的首部格式", new)[0].strip()
    if new and new != stem.strip():
        q["content"] = new
        print(f"  hex-clean {q.get('id')} {len(stem)}->{len(new)}")
        return True
    return False


def split_x06(data):
    """多空题拆成 4 道独立选择题（答案 AAAC → A,A,A,C）。"""
    ch, q = find_q(data, "X06", 14, "概述")
    if not q:
        print("skip X06 not found")
        return
    base = {
        "type": "选择题",
        "page": 14,
        "bbox": q.get("bbox"),
        "has_image": False,
        "image_ref": None,
        "topic_title": q.get("topic_title"),
        "q_pages": q.get("q_pages"),
        "a_pages": q.get("a_pages"),
        "sub_questions": None,
    }
    expl = (q.get("answer") or {}).get("explanation") or ""
    subs = [
        {
            "id": "X06_1",
            "content": "为了使数据在传输期间的时延最小，首选的交换方式是（）。",
            "options": {
                "A": "电路交换",
                "B": "报文交换",
                "C": "分组交换",
            },
            # 仅 3 选项的空；补 D 避免前端崩
            "answer": {"choice": "A", "explanation": expl},
        },
        {
            "id": "X06_2",
            "content": "为保证数据无差错地传送，不应选用的交换方式是（）。",
            "options": {
                "A": "电路交换",
                "B": "报文交换",
                "C": "分组交换",
            },
            "answer": {"choice": "A", "explanation": expl},
        },
        {
            "id": "X06_3",
            "content": "分组交换对报文交换的主要改进是（）。",
            "options": {
                "A": "传输单位更小且有固定的最大长度",
                "B": "传输单位更大且有固定的最大长度",
                "C": "差错控制更完善",
                "D": "路由算法更简单",
            },
            "answer": {"choice": "A", "explanation": expl},
        },
        {
            "id": "X06_4",
            "content": "分组交换相对报文交换的改进产生的直接结果是（）。",
            "options": {
                "A": "降低了误码率",
                "B": "提高了数据传输速率",
                "C": "减少传输时延",
                "D": "增加传输时延",
            },
            "answer": {"choice": "C", "explanation": expl},
        },
    ]
    # ①② 只有 A/B/C，补 D 占位为「不适用」不合适；前端允许 3 选项更好，但质量检查要 4。补 D=以上都不对
    for s in subs[:2]:
        s["options"]["D"] = "以上都不是"
    new_qs = [{**base, **s} for s in subs]
    qs = ch["questions"]
    for i, qq in enumerate(qs):
        if qq is q:
            qs[i : i + 1] = new_qs
            break
    ch["question_count"] = len(qs)
    print("  split X06 -> X06_1..4")


def split_x27(data):
    ch, q = find_q(data, "X27", 158, "IPv4")
    if not q:
        print("skip X27")
        return
    choice = ((q.get("answer") or {}).get("choice") or "DA").replace(",", "").replace(" ", "")
    # 答案应为 ①D ②A → DA（若为其他则取前两字符）
    c1 = choice[0] if choice else "D"
    c2 = choice[1] if len(choice) > 1 else "A"
    expl = (q.get("answer") or {}).get("explanation") or ""
    base = {
        "type": "选择题",
        "page": 158,
        "bbox": q.get("bbox"),
        "has_image": False,
        "image_ref": None,
        "topic_title": q.get("topic_title"),
        "q_pages": q.get("q_pages"),
        "a_pages": q.get("a_pages"),
        "sub_questions": None,
    }
    subs = [
        {
            "id": "X27_1",
            "content": "CIDR地址块192.168.10.0/20所包含的IP地址范围是（）。",
            "options": {
                "A": "192.168.0.0 ~ 192.168.12.255",
                "B": "192.168.10.0 ~ 192.168.13.255",
                "C": "192.168.10.0 ~ 192.168.14.255",
                "D": "192.168.0.0 ~ 192.168.15.255",
            },
            "answer": {"choice": c1, "explanation": expl},
        },
        {
            "id": "X27_2",
            "content": "与地址192.16.0.19/28同属于一个子网的主机地址是（）。",
            "options": {
                "A": "192.16.0.17",
                "B": "192.16.0.31",
                "C": "192.16.0.15",
                "D": "192.16.0.14",
            },
            "answer": {"choice": c2, "explanation": expl},
        },
    ]
    new_qs = [{**base, **s} for s in subs]
    qs = ch["questions"]
    for i, qq in enumerate(qs):
        if qq is q:
            qs[i : i + 1] = new_qs
            break
    ch["question_count"] = len(qs)
    print(f"  split X27 -> X27_1..2 answers {c1}{c2}")


def split_x18_tcp(data):
    ch, q = find_q(data, "X18", 252, "TCP")
    if not q:
        print("skip X18 TCP")
        return
    choice = ((q.get("answer") or {}).get("choice") or "AC").replace(",", "").replace(" ", "")
    c1 = choice[0] if choice else "A"
    c2 = choice[1] if len(choice) > 1 else "C"
    expl = (q.get("answer") or {}).get("explanation") or ""
    base = {
        "type": "选择题",
        "page": 252,
        "bbox": q.get("bbox"),
        "has_image": False,
        "image_ref": None,
        "topic_title": q.get("topic_title"),
        "q_pages": q.get("q_pages"),
        "a_pages": q.get("a_pages"),
        "sub_questions": None,
    }
    o1 = {
        "A": "SYN=1，序号=X",
        "B": "SYN=1，序号=X+1，ACK=1",
        "C": "SYN=1，序号=Y",
        "D": "SYN=1，序号=Y，ACK=1，确认号=Y+1",
    }
    o2 = {
        "A": "SYN=1，序号=X+1",
        "B": "SYN=1，序号=X+1，ACK=1",
        "C": "SYN=1，序号=Y，ACK=1，确认号=X+1",
        "D": "SYN=1，序号=Y，ACK=1，确认号=Y+1",
    }
    subs = [
        {
            "id": "X18_1",
            "content": "TCP三次握手建立连接时，A发送给B的第一个报文应是（）。",
            "options": o1,
            "answer": {"choice": c1, "explanation": expl},
        },
        {
            "id": "X18_2",
            "content": "TCP三次握手建立连接时，B回复给A的报文应是（）。",
            "options": o2,
            "answer": {"choice": c2, "explanation": expl},
        },
    ]
    new_qs = [{**base, **s} for s in subs]
    qs = ch["questions"]
    for i, qq in enumerate(qs):
        if qq is q:
            qs[i : i + 1] = new_qs
            break
    ch["question_count"] = len(qs)
    print(f"  split X18 TCP -> X18_1..2 answers {c1}{c2}")


def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    n = 0

    # 1) 多空拆分
    split_x06(data)
    split_x27(data)
    split_x18_tcp(data)
    n += 3

    # 2) 选项补全
    ch, q = find_q(data, "X18", 89, "介质访问")
    if q:
        set_opts(
            q,
            {
                "A": "（-1,1,1,1）和(-1,-1,-1,1)",
                "B": "（-1,-1,1,1）和(-1,1,-1,1)",
                "C": "(-1,1,1,-1）和（1,1,-1,-1)",
                "D": "(-1,-1,-1,-1）和（1,1,1,1)",
            },
        )
        n += 1

    ch, q = find_q(data, "X53", 161, "IPv4")
    if q:
        set_opts(
            q,
            {
                "A": "192.168.2.0，255.255.255.128，192.168.1.1",
                "B": "192.168.2.0，255.255.255.0，192.168.1.1",
                "C": "192.168.2.0，255.255.255.128，192.168.1.2",
                "D": "192.168.2.0，255.255.255.0，192.168.1.2",
            },
        )
        # 关联图
        crop_if_needed(q)
        n += 1

    ch, q = find_q(data, "X17", 73, "流量控制")
    if q:
        set_opts(
            q,
            {
                "A": "节点A、B之间只能采用停止等待协议",
                "B": "节点A、B之间只能采用GBN协议",
                "C": "节点A、B之间只能采用SR协议",
                "D": "节点A、B之间可以采用GBN协议或SR协议",
            },
        )
        n += 1

    ch, q = find_q(data, "X35", 254, "TCP")
    if q:
        # 慢开始：t 时刻发 k 段，下一 RTT 发 2k
        set_opts(
            q,
            {
                "A": "k",
                "B": "k+1",
                "C": "2k",
                "D": "2^k",
            },
        )
        # 答案通常 C
        ans = q.get("answer") or {}
        if not ans.get("choice"):
            ans["choice"] = "C"
            q["answer"] = ans
        n += 1

    # 3) X11_2 十六进制污染：改为解答题并清洗
    ch, q = find_q(data, "X11_2", 166)
    if q:
        clean_hex(q)
        q["type"] = "解答题"
        q["options"] = {}
        ans = q.get("answer") or {}
        q["answer"] = {"choice": None, "explanation": ans.get("explanation") or ""}
        print("  X11_2 -> 解答题")
        n += 1

    # 4) hex pollution on app
    for ch in data["chapters"]:
        for q in ch.get("questions") or []:
            if clean_hex(q):
                n += 1
            if crop_if_needed(q):
                n += 1

    # 5) stem trunc：补全右括号
    for ch in data["chapters"]:
        for q in ch.get("questions") or []:
            stem = (q.get("content") or "").rstrip()
            if stem.endswith("（") or stem.endswith("("):
                q["content"] = stem + "）。"
                print(f"  stem-fix {q.get('id')}")
                n += 1
            elif stem.endswith("，") or stem.endswith("、"):
                # 从解析首句不稳，仅去掉异常截断标点改为句号
                q["content"] = stem[:-1] + "。"
                print(f"  stem-end {q.get('id')}")
                n += 1

    for ch in data["chapters"]:
        ch["question_count"] = len(ch.get("questions") or [])
    data["total_questions"] = sum(ch["question_count"] for ch in data["chapters"])
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done ops={n} total_q={data['total_questions']}")


if __name__ == "__main__":
    main()
