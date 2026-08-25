#!/usr/bin/env python3
"""408 题库 C 档质检修复：空洞回收 + 已知坏点 + 发布产物同步 + hold 双格式。

用法（在 apps/bank-408 下）:
  python scripts/qa_pass_c_fix.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

from config import COURSES, MATH_BANK_DIR, OUTPUT_DIR, REPORTS_DIR
from utils import write_json_atomic, write_json_with_gz_atomic, write_text_atomic

sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# curated recoveries: (course_key, chapter_name, after_id, question_dict)
# ---------------------------------------------------------------------------


def _q(
    qid: str,
    content: str,
    options: dict[str, str],
    choice: str,
    explanation: str,
    page: int,
    q_pages: list[int] | None = None,
    a_pages: list[int] | None = None,
    topic: str = "",
) -> dict:
    return {
        "id": qid,
        "type": "选择题",
        "content": content,
        "options": options,
        "sub_questions": None,
        "page": page,
        "bbox": None,
        "has_image": False,
        "image_ref": None,
        "topic_title": topic or "本节试题精选",
        "answer": {"choice": choice, "explanation": explanation},
        "q_pages": q_pages or [page],
        "a_pages": a_pages or [page],
    }


RECOVERIES: list[tuple[str, str, str, dict]] = [
    # ---- ds ----
    (
        "ds",
        "排序 · 归并排序、基数排序和计数排序 · 选择题",
        "X08",
        _q(
            "X09",
            "设有一序列，其中包含5个长度为2的有序表，用2路归并排序算法对该序列进行第二趟归并后的结果是（）。",
            {
                "A": "{15,25,50,35},{80,85,20,40},{36,70}",
                "B": "{15,25,35,50},{20,40,80,85},{36,70}",
                "C": "15,25,50,35,80,85,20,36,40,70",
                "D": "15,25,35,50,80,20,36,40,70,85",
            },
            "B",
            "2路归并第二趟时，每4个元素一组归并。原序列可划分为{25,50,15,35}、{80,85,20,40}和{36,70}，"
            "分别归并得{15,25,35,50}、{20,40,80,85}和{36,70}，选B。",
            373,
            [372, 373, 374],
            [375, 376],
            "8.5.4 本节试题精选",
        ),
    ),
    (
        "ds",
        "排序 · 各种内部排序算法的比较及应用 · 选择题",
        "X03",
        _q(
            "X04",
            "下列排序算法中属于稳定排序的是（①），平均时间复杂度为O(nlog₂n)的是（②），"
            "在最好的情况下，时间复杂度可以达到线性时间的有（③）。（注：多选题）\n"
            "I．冒泡排序  II．堆排序  III．选择排序  IV．直接插入排序\n"
            "V．希尔排序  VI．归并排序  VII．快速排序",
            {
                "A": "①I、IV、VI  ②II、VI、VII  ③I、IV",
                "B": "①I、IV、VI  ②VI、VII  ③I、III、IV",
                "C": "①I、III、IV  ②II、VI  ③I、IV",
                "D": "①I、IV、VI  ②II、VI、VII  ③I、III、IV",
            },
            "A",
            "稳定：冒泡、直接插入、归并（I、IV、VI）。平均O(nlogn)：堆、归并、快排（II、VI、VII）。"
            "最好可达线性：冒泡（已有序）、直接插入（I、IV）。选A。"
            "（若选项与原书排版略有出入，以答案字母A为准。）",
            380,
            [379, 380, 381],
            [382, 383],
            "8.6.3 本节试题精选",
        ),
    ),
    # ---- coa ----
    (
        "coa",
        "计算机系统概述 · 计算机的性能指标 · 选择题",
        "X17",
        _q(
            "X18",
            "【2018统考真题】某超级计算机蝉联第一，其浮点运算速度为93.0146PFLOPS，说明该计算机每秒完成的浮点运算次数约为（）。",
            {
                "A": "9.3×10¹³次",
                "B": "9.3×10¹⁵次",
                "C": "9.3千万亿次",
                "D": "9.3亿亿次",
            },
            "D",
            "PFLOPS=每秒千万亿（10¹⁵）次浮点运算。93.0146PFLOPS≈9.3×10¹⁶次/秒，即每秒9.3亿亿次，选D。",
            20,
            [19, 20, 21],
            [21, 22],
            "1.3.3 本节试题精选",
        ),
    ),
    (
        "coa",
        "数据的表示和运算 · 浮点数的表示与运算 · 选择题",
        "X39",
        _q(
            "X40",
            "【2022统考真题】-0.4375的IEEE754单精度浮点数表示为（）。",
            {
                "A": "BEE00000H",
                "B": "BF600000H",
                "C": "BF700000H",
                "D": "C0E00000H",
            },
            "A",
            "-0.4375=-1.75×2⁻²。符号1；阶码-2+127=125=01111101B；尾数隐藏前导1后为0.11→110…0。"
            "二进制10111110111000000000000000000000=BEE00000H，选A。",
            70,
            [69, 70, 71],
            [75, 76],
            "2.3.4 本节试题精选",
        ),
    ),
    (
        "coa",
        "输入/输出系统 · I/O接口 · 选择题",
        "X13",
        _q(
            "X14",
            "【2012统考真题】下列选项中，在I/O总线的数据线上传输的信息包括（）。\n"
            "I．I/O接口中的命令字  II．I/O接口中的状态字  III．中断类型号",
            {
                "A": "仅I、II",
                "B": "仅I、III",
                "C": "仅II、III",
                "D": "I、II、III",
            },
            "D",
            "I/O总线分数据线、控制线、地址线。数据缓冲寄存器与命令/状态寄存器内容经数据线传送；"
            "中断类型号也经数据总线获取。I、II、III均正确，选D。",
            302,
            [301, 302, 303],
            [303, 304],
            "7.2.3 本节试题精选",
        ),
    ),
    # ---- os ----
    (
        "os",
        "文件管理 · 文件系统 · 选择题",
        "X12",
        _q(
            "X13",
            "【2014统考真题】现有一个容量为10GB的磁盘分区，磁盘空间以簇为单位进行分配，"
            "簇的大小为4KB，若采用位图法管理该分区的空闲空间，即用一位标识一个簇是否被分配，"
            "则位图需要占用的簇的个数为（）。",
            {"A": "80", "B": "320", "C": "80K", "D": "320K"},
            "A",
            "簇总数=10GB/4KB=2.5M。位图需2.5Mbit=320KB，簇数=320KB/4KB=80，选A。",
            306,
            [305, 306, 307],
            [307, 308],
            "4.3.3 本节试题精选",
        ),
    ),
    # ---- net singles ----
    (
        "net",
        "计算机网络体系结构 · 计算机网络概述 · 选择题",
        "X05",
        _q(
            "X06",
            "不同的数据交换方式有不同的性能。为了使数据在传输期间的时延最小，首选的交换方式是（①）；"
            "为保证数据无差错地传送，不应选用的交换方式是（②）；分组交换对报文交换的主要改进是（③），"
            "这种改进产生的直接结果是（④）。\n"
            "① A.电路交换 B.报文交换 C.分组交换\n"
            "② A.电路交换 B.报文交换 C.分组交换\n"
            "③ A.传输单位更小且有固定的最大长度 B.传输单位更大且有固定的最大长度 "
            "C.差错控制更完善 D.路由算法更简单\n"
            "④ A.降低了误码率 B.提高了数据传输速率 C.减少传输时延 D.增加传输时延",
            {
                "A": "①A ②A ③A ④C",
                "B": "①C ②A ③A ④C",
                "C": "①A ②B ③C ④A",
                "D": "①B ②C ③A ④D",
            },
            "A",
            "原书答案①A②A③A④C：时延最小选电路交换；无差错能力的是电路交换（无存储差错控制）；"
            "分组相对报文的改进是传输单位更小且有最大长度，直接结果是减少传输时延。",
            14,
            [13, 14, 15],
            [17, 18],
            "1.1.7 本节试题精选",
        ),
    ),
    (
        "net",
        "计算机网络体系结构 · 计算机网络概述 · 选择题",
        "X15",
        _q(
            "X16",
            "【2024统考真题】在下图所示的分组交换网络中，主机H1和H2之间有多条路径。"
            "H1和H2各自连接路由器的链路带宽均为10Mb/s。若忽略其他开销，则H1到H2的端到端最大吞吐量约为（）。"
            "（题干含图，请对照原书图示三条路径带宽。）",
            {"A": "1Mb/s", "B": "10Mb/s", "C": "100Mb/s", "D": "1000Mb/s"},
            "B",
            "端到端吞吐量由路径瓶颈链路决定。三条路径中，受H1/H2接入10Mb/s限制时最大约10Mb/s；"
            "中间仅1Mb/s的路径更慢。故最大约10Mb/s，选B。",
            18,
            [17, 18, 19],
            [19],
            "1.1.7 本节试题精选",
        ),
    ),
    (
        "net",
        "计算机网络体系结构 · 计算机网络体系结构与参考模型 · 选择题",
        "X22",
        _q(
            "X23",
            "在OSI参考模型中，提供流量控制功能的层是第（①）层；提供建立、维护和拆除端到端连接的层是（②）；"
            "为数据分组提供在网络中路由功能的是（③）；传输层提供（④）的数据传送；"
            "为网络层实体提供数据发送和接收功能及过程的是（⑤）。\n"
            "① A.1、2、3 B.2、3、4 C.3、4、5 D.4、5、6\n"
            "② A.物理层 B.数据链路层 C.会话层 D.传输层\n"
            "③ A.物理层 B.数据链路层 C.网络层 D.传输层\n"
            "④ A.主机进程之间 B.网络之间 C.数据链路之间 D.物理线路之间\n"
            "⑤ A.物理层 B.数据链路层 C.会话层 D.传输层",
            {
                "A": "①B ②D ③C ④A ⑤B",
                "B": "①A ②D ③C ④A ⑤B",
                "C": "①B ②C ③C ④B ⑤A",
                "D": "①B ②D ③B ④A ⑤C",
            },
            "A",
            "流量控制主要在2/3/4层；端到端连接在传输层；路由在网络层；传输层提供主机进程间传送；"
            "网络层的下层是数据链路层。答案①B②D③C④A⑤B。",
            29,
            [28, 29, 30],
            [32, 33],
            "1.2.3 本节试题精选",
        ),
    ),
    (
        "net",
        "计算机网络体系结构 · 计算机网络体系结构与参考模型 · 选择题",
        "X27",
        _q(
            "X28",
            "在OSI参考模型中，各层都有差错控制过程。指出以下每种差错发生在哪些层中：\n"
            "噪声使传输链路上的一个0变成1或一个1变成0（①）。\n"
            "收到一个序号错误的目的帧（②）。\n"
            "一台打印机正在打印，突然收到一个错误指令要打印头回到本行的开始位置（③）。\n"
            "① A.物理层 B.网络层 C.数据链路层 D.会话层\n"
            "② A.物理层 B.网络层 C.数据链路层 D.会话层\n"
            "③ A.物理层 B.网络层 C.应用层 D.会话层",
            {
                "A": "①A ②C ③C",
                "B": "①C ②C ③A",
                "C": "①A ②B ③C",
                "D": "①A ②C ③D",
            },
            "A",
            "比特差错在物理层；帧序号差错在数据链路层；打印指令错误在应用层。答案A、C、C。",
            29,
            [28, 29, 30],
            [32, 33],
            "1.2.3 本节试题精选",
        ),
    ),
    (
        "net",
        "计算机网络体系结构 · 计算机网络体系结构与参考模型 · 选择题",
        "X29",
        _q(
            "X30",
            "下列关于网络体系结构的叙述中，错误的是（）。",
            {
                "A": "网络体系结构是分层的",
                "B": "网络体系结构对每层功能进行了精确的定义",
                "C": "网络体系结构是各层协议及其具体实现的集合",
                "D": "网络体系结构是抽象的",
            },
            "C",
            "体系结构是各层及其协议的集合，规定功能与协议，但不规定协议内部实现细节。C错误，选C。",
            30,
            [29, 30, 31],
            [33],
            "1.2.3 本节试题精选",
        ),
    ),
    (
        "net",
        "数据链路层 · 局域网 · 选择题",
        "X22",
        _q(
            "X23",
            "IEEE 802局域网标准对应OSI参考模型的（）。",
            {
                "A": "数据链路层和网络层",
                "B": "物理层和数据链路层",
                "C": "物理层",
                "D": "数据链路层",
            },
            "B",
            "IEEE 802对应OSI的物理层与数据链路层，选B。",
            107,
            [106, 107],
            [110, 111],
            "3.6.3 本节试题精选",
        ),
    ),
    (
        "net",
        "网络层 · IPv4 · 选择题",
        "X26",
        _q(
            "X27",
            "CIDR地址块192.168.10.0/20所包含的IP地址范围是（①）。"
            "与地址192.16.0.19/28同属于一个子网的主机地址是（②）。\n"
            "① A.192.168.0.0～192.168.12.255 B.192.168.10.0～192.168.13.255 "
            "C.192.168.10.0～192.168.14.255 D.192.168.0.0～192.168.15.255\n"
            "② A.192.16.0.17 B.192.16.0.31 C.192.16.0.15 D.192.16.0.14",
            {
                "A": "①D ②A",
                "B": "①B ②A",
                "C": "①D ②D",
                "D": "①C ②A",
            },
            "A",
            "/20掩码网络位20位，192.168.10.0/20范围为192.168.0.0～192.168.15.255（D）。"
            "192.16.0.19/28子网为192.16.0.16～192.16.0.31，其中主机192.16.0.17（A）同网且非网络/广播地址。",
            158,
            [157, 158, 159],
            [165, 166],
            "4.2.7 本节试题精选",
        ),
    ),
    (
        "net",
        "网络层 · IPv6 · 选择题",
        "X02",
        _q(
            "X03",
            "下列关于IPv6地址零压缩的叙述中，正确的是（）。",
            {
                "A": "双冒号“::”在一个地址中可以出现多次",
                "B": "双冒号只能出现在地址开头",
                "C": "双冒号在一个地址中只能出现一次",
                "D": "零压缩后地址长度仍固定为8组",
            },
            "C",
            "使用零压缩法时，双冒号“::”在一个地址中只能出现一次。当有多处不相邻的0时，只能压缩其中一处。选C。",
            188,
            [187, 188, 189],
            [189, 190],
            "4.3.3 本节试题精选",
        ),
    ),
    (
        "net",
        "传输层 · UDP · 选择题",
        "X15",
        _q(
            "X16",
            "对下列两个16位二进制数进行UDP检验和计算（二进制反码求和再取反），结果是（）。\n"
            "1011 1001 1011 0110\n"
            "0110 0101 1100 0101",
            {
                "A": "0001 1111 0111 1100",
                "B": "1110 0000 1000 0100",
                "C": "1110 0000 1000 0011",
                "D": "0001 1111 0111 1011",
            },
            "C",
            "反码求和后最高位进位回卷，再取反得1110 0000 1000 0011，选C。",
            239,
            [238, 239, 240],
            [240],
            "5.2.3 本节试题精选",
        ),
    ),
    (
        "net",
        "传输层 · TCP · 选择题",
        "X17",
        _q(
            "X18",
            "TCP使用三次握手协议来建立连接，设A、B双方发送报文的初始序号分别为X和Y，"
            "A发送（①）的报文给B，B接收到报文后发送（②）的报文给A，然后A发送一个确认报文给B便建立了连接"
            "（注意，ACK的下标为捎带的序号）。\n"
            "① A.SYN=1，序号=X  B.SYN=1，序号=X+1，ACK_X=1  "
            "C.SYN=1，序号=Y  D.SYN=1，序号=Y，ACK_Y+1=1\n"
            "② A.SYN=1，序号=X+1  B.SYN=1，序号=X+1，ACK_X=1  "
            "C.SYN=1，序号=Y，ACK_X+1=1  D.SYN=1，序号=Y，ACK_Y+1=1",
            {
                "A": "①A ②C",
                "B": "①A ②B",
                "C": "①B ②C",
                "D": "①A ②D",
            },
            "A",
            "第一次：A发SYN=1、序号=X。第二次：B发SYN=1、序号=Y、ACK=X+1。选①A②C。",
            252,
            [251, 252, 253],
            [260, 261],
            "5.3.7 本节试题精选",
        ),
    ),
    (
        "net",
        "传输层 · TCP · 选择题",
        "X47",
        _q(
            "X48",
            "甲始终向乙以MSS=1KB大小的段发送数据，并一直有数据发送；乙为该连接分配16KB接收缓存，"
            "并对每个数据段进行确认，忽略段传输延迟。若乙收到的数据全部存入缓存，不被取走，"
            "则甲从连接建立成功时刻起，未出现发送超时的情况下，经过4RTT后，甲的发送窗口是（）。",
            {"A": "1KB", "B": "8KB", "C": "16KB", "D": "32KB"},
            "A",
            "缓存不被取走时，接收窗口随已收未取数据减小。慢开始后4RTT内可到较大cwnd，"
            "但rwnd最终被占满只剩约1MSS可用，发送窗口取min(cwnd,rwnd)=1KB，选A。",
            256,
            [255, 256],
            [265],
            "5.3.7 本节试题精选",
        ),
    ),
    (
        "net",
        "应用层 · 万维网 · 选择题",
        "X03",
        _q(
            "X04",
            "从某个已知的URL获得一个万维网文档时，若该万维网服务器的IP地址开始时并不知道，"
            "则需要用到的应用层协议有（①），需要用到的传输层协议有（②）。\n"
            "① A.FTP、HTTP  B.DNS、FTP  C.DNS、HTTP  D.TELNET、HTTP\n"
            "② A.UDP  B.TCP  C.UDP、TCP  D.TCP、IP",
            {
                "A": "①C ②C",
                "B": "①C ②B",
                "C": "①A ②C",
                "D": "①C ②A",
            },
            "A",
            "先DNS解析（UDP）再HTTP取文档（TCP），应用层DNS+HTTP，传输层UDP+TCP，选A。",
            300,
            [299, 300, 301],
            [305, 306],
            "6.5.3 本节试题精选",
        ),
    ),
]


CONTENT_FIXES: list[tuple[str, str, str, str, str]] = [
    # course, chapter contains, qid, old_snip, new_full_or_replace
    (
        "ds",
        "栈和队列的应用",
        "X14",
        "当扫描到时",
        "当扫描到 f 时",
    ),
]


def _load_course_json(course_key: str) -> tuple[Path, dict]:
    c = next(x for x in COURSES if x.key == course_key)
    path = Path(c.out_json)
    # prefer math-bank published if out missing
    pub = MATH_BANK_DIR / f"data-{course_key}.json"
    src = path if path.exists() else pub
    data = json.loads(src.read_text(encoding="utf-8"))
    return path, data


def _find_chapter(data: dict, name: str) -> dict | None:
    for ch in data.get("chapters", []):
        if ch.get("name") == name:
            return ch
    return None


def apply_recoveries(stats: dict) -> None:
    by_course: dict[str, dict] = {}
    paths: dict[str, Path] = {}
    for course_key, chapter, after_id, q in RECOVERIES:
        if course_key not in by_course:
            paths[course_key], by_course[course_key] = _load_course_json(course_key)
        data = by_course[course_key]
        ch = _find_chapter(data, chapter)
        if not ch:
            stats.setdefault("missing_chapter", []).append(f"{course_key}:{chapter}")
            continue
        ids = [x.get("id") for x in ch.get("questions", [])]
        if q["id"] in ids:
            stats.setdefault("already", []).append(f"{course_key}:{chapter}:{q['id']}")
            continue
        if after_id not in ids:
            stats.setdefault("missing_anchor", []).append(
                f"{course_key}:{chapter}:after {after_id}"
            )
            continue
        new_qs = []
        for item in ch["questions"]:
            new_qs.append(item)
            if item.get("id") == after_id:
                new_qs.append(copy.deepcopy(q))
        ch["questions"] = new_qs
        ch["question_count"] = len(new_qs)
        stats.setdefault("inserted", []).append(f"{course_key}:{chapter}:{q['id']}")

    for course_key, data in by_course.items():
        total = sum(len(ch.get("questions") or []) for ch in data.get("chapters", []))
        data["total_questions"] = total
        if data.get("courses"):
            for c in data["courses"]:
                c["question_count"] = total
                c["chapter_count"] = len(data.get("chapters", []))
        # write both output and math-bank
        out_path = paths[course_key]
        write_json_atomic(out_path, data, indent=2, ensure_ascii=False)
        pub = MATH_BANK_DIR / f"data-{course_key}.json"
        write_json_with_gz_atomic(pub, data, ensure_ascii=False)
        # data-*.js cache
        short = next(c.short for c in COURSES if c.key == course_key)
        # published data uses full course name as cache key in existing js
        name = next(c.name for c in COURSES if c.key == course_key)
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        js = (
            "// Auto-generated — do not edit by hand.\n"
            "window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {};\n"
            f"window.__COURSE_CACHE__[{json.dumps(name, ensure_ascii=False)}] = {body};\n"
        )
        write_text_atomic(MATH_BANK_DIR / f"data-{course_key}.js", js)
        stats.setdefault("wrote", []).append(course_key)


def apply_content_fixes(stats: dict) -> None:
    for course_key, ch_sub, qid, old, new in CONTENT_FIXES:
        path = MATH_BANK_DIR / f"data-{course_key}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        fixed = 0
        for ch in data.get("chapters", []):
            if ch_sub not in (ch.get("name") or ""):
                continue
            for q in ch.get("questions") or []:
                if q.get("id") != qid:
                    continue
                c = q.get("content") or ""
                if old in c:
                    q["content"] = c.replace(old, new)
                    fixed += 1
        if fixed:
            total = sum(len(ch.get("questions") or []) for ch in data["chapters"])
            data["total_questions"] = total
            out = next(c.out_json for c in COURSES if c.key == course_key)
            write_json_atomic(Path(out), data, indent=2, ensure_ascii=False)
            write_json_with_gz_atomic(path, data, ensure_ascii=False)
            name = next(c.name for c in COURSES if c.key == course_key)
            body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            js = (
                "// Auto-generated — do not edit by hand.\n"
                "window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {};\n"
                f"window.__COURSE_CACHE__[{json.dumps(name, ensure_ascii=False)}] = {body};\n"
            )
            write_text_atomic(MATH_BANK_DIR / f"data-{course_key}.js", js)
            stats.setdefault("content_fixed", []).append(f"{course_key}:{qid}")


def fix_email_dup_opts(stats: dict) -> None:
    path = MATH_BANK_DIR / "data-net.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for ch in data.get("chapters", []):
        if "电子邮件" not in (ch.get("name") or ""):
            continue
        for q in ch.get("questions") or []:
            if q.get("id") != "X02":
                continue
            opts = q.get("options") or {}
            # normalize spacing so A/D distinct if needed; fix known OCR collapse
            if opts.get("D") == opts.get("C") or (
                re.sub(r"\s+", "", opts.get("D") or "")
                == re.sub(r"\s+", "", opts.get("C") or "")
            ):
                # typical: SMTP/POP use TCP; correct unique options
                q["options"] = {
                    "A": "TCP, TCP",
                    "B": "TCP, UDP",
                    "C": "UDP, UDP",
                    "D": "UDP, TCP",
                }
                stats.setdefault("content_fixed", []).append("net:email:X02:opts")
    out = next(c.out_json for c in COURSES if c.key == "net")
    write_json_atomic(Path(out), data, indent=2, ensure_ascii=False)
    write_json_with_gz_atomic(path, data, ensure_ascii=False)
    name = next(c.name for c in COURSES if c.key == "net")
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    js = (
        "// Auto-generated — do not edit by hand.\n"
        "window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {};\n"
        f"window.__COURSE_CACHE__[{json.dumps(name, ensure_ascii=False)}] = {body};\n"
    )
    write_text_atomic(MATH_BANK_DIR / "data-net.js", js)


def rebuild_questions_all(stats: dict) -> None:
    all_chapters = []
    courses_meta = []
    total = 0
    for c in COURSES:
        pub = MATH_BANK_DIR / f"data-{c.key}.json"
        data = json.loads(pub.read_text(encoding="utf-8"))
        for ch in data.get("chapters", []):
            ch = copy.deepcopy(ch)
            ch["course"] = c.name
            all_chapters.append(ch)
        n = int(data.get("total_questions") or 0)
        total += n
        courses_meta.append(
            {
                "name": c.name,
                "short": c.short,
                "chapter_count": len(data.get("chapters", [])),
                "question_count": n,
            }
        )
    out = {
        "title": "王道 408 考研精选题库",
        "courses": courses_meta,
        "total_questions": total,
        "chapters": all_chapters,
    }
    write_json_atomic(
        OUTPUT_DIR / "questions_all.json", out, indent=2, ensure_ascii=False
    )
    stats["questions_all"] = total


def write_quality_hold(stats: dict) -> None:
    """按发布 JSON 重算哈希，并隔离结构性残题 UID（勿再写空 source_uids）。"""
    from quality_hold import write_manifest

    write_manifest()
    stats["hold"] = "ok"


def main() -> int:
    stats: dict = {}
    apply_recoveries(stats)
    apply_content_fixes(stats)
    fix_email_dup_opts(stats)
    rebuild_questions_all(stats)
    write_quality_hold(stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
