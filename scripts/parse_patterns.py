#!/usr/bin/env python3
"""parse_questions.py 的正则模式与匹配函数集合。

把易变的 OCR 排版规则收敛到这里，便于回归测试和后续课程扩展。
"""

import re

# 题号格式: 01. 或 02. …（零填充两位以上），要求开头数字 ≤ 2 位
QUESTION_HEADER_RE = re.compile(r"^\s*0?([1-9]\d?)[\.．、]\s*(.+)$")

# 排除答案短格式: 纯"01. C"，也支持多选/多空答案如 "06. B、D" / "11.B,A" / "16.B、E、C、D"
ANSWER_SHORT_RE = re.compile(
    r"^\s*0?([1-9]\d?)[\.．、]\s*([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)\s*$"
)

# 选项行：A. xxx
OPTION_LINE_RE = re.compile(r"^([A-Da-d])[\.．、]\s*(.+?)$")

# 综合应用题答案头：01.【解答】
ANS_HEADER_RE = re.compile(r"^\s*0?([1-9]\d?)[\.．、]\s*[\【\[]?解答[\】\]]?\s*$")

# 应用题答案起始（无【解答】）
APP_ANS_START_RE = re.compile(r"^\s*0?([1-9]\d?)[\.．、]\s*(.+)$")

# 章节/小节标记：必须排除
# - "1.1.3 本节试题精选"
# - "2.数据的存储结构"
# - "一、单项选择题"
TOPIC_HEADER_RE = re.compile(r"^\s*\d+(?:\.\d+){1,3}\s")
SECTION_HEADER_RE = re.compile(r"^\s*[一二三四五六七八九十][、．]\s*[一-龥]+")
NUMBER_HEADER_RE = re.compile(r"^\s*\d{1,2}[\.．、]\s*[一-龥□（(]")

# 页眉/页脚噪音：书籍标题会出现在每页顶部或底部，混入题目内容
# 如 "2027年数据结构考研复习指导"，前面可能带页码 "8 2027年数据结构考研复习指导"
PAGE_NOISE_RE = re.compile(r"^\s*(?:\d+\s+)?\d{4}年.{0,20}考研复习指导\s*$")

# 题干中真正指向附图/插图的短语；避免把"图论""并查集涉及图"等讨论主题的"图"字误标
IMAGE_MARKERS = [
    "如图",
    "见下图",
    "如下图所示",
    "如图所示",
    "图中所示",
    "右图",
    "左图",
    "下图",
    "上图",
    "给出下图",
    "给出上图",
]

# 不含真实附图的"图"字场景，用于过滤误报
IMAGE_FALSE_POSITIVES = [
    "图的基本概念",
    "图论",
    "并查集涉及图",
    "涉及图",
    "图的相关",
    "图的存储",
    "图的遍历",
    "图的拓扑",
    "图的最短",
    "图的最小生成",
    "图的应用",
    "有向图",
    "无向图",
    "连通图",
    "强连通图",
    "生成树",
    "森林",
]


def has_real_image_ref(content):
    """判断题干是否真正指向附图（而非章节术语中的"图"字）。"""
    if not content:
        return False
    for fp in IMAGE_FALSE_POSITIVES:
        if fp in content:
            return False
    return any(m in content for m in IMAGE_MARKERS)


def extract_answer_choice(line):
    """从答案短格式行提取题号和答案字母，兼容 OCR 识别中的带圈数字、中文逗号等变体。

    只匹配题号后紧跟答案字母（允许分隔符）的短格式，避免把题干中的"B树"等误当答案。
    例如：
      11. B      -> ('11', 'B')
      11. B、D   -> ('11', 'BD')
      11.B，A    -> ('11', 'BA')
      11.①B、②D -> ('11', 'BD')
      16.B、E、C、D -> ('16', 'BECD')
    """
    m = re.match(r"^\s*0?([1-9]\d?)[\.．、]", line)
    if not m:
        return None
    qid = m.group(1).zfill(2)
    rest = line[m.end() :]
    # 去掉带圈数字前缀（如 ①B 中的 ①）
    rest = re.sub(r"[①-⑨⑩]", "", rest)
    # 匹配开头的答案字母序列，允许用、,，\s 分隔；短格式行在答案字母后应无其他内容
    choice_part = re.match(r"^\s*([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)\s*", rest)
    if not choice_part:
        return None
    # 答案字母之后不应再有其他字符（避免把 "01. B树" 误当答案）
    after = rest[choice_part.end() :].strip()
    if after and after not in ("。", "，", ",", "."):
        return None
    letters = re.findall(r"[A-Ga-g]", choice_part.group(1))
    if not letters:
        return None
    return qid, "".join(letters).upper()


def section_start_re():
    """题目区起始：X.Y.Z 本节试题精选 / 本节习题精选。"""
    return re.compile(r"^\s*\d+\.\d+(?:\.\d+)?\s*(本节试题精选|本节习题精选)\s*$")


def answer_header_re():
    """题目区结束 / 答案区起始：X.Y.Z 答案与解析。"""
    return re.compile(r"^\s*\d+\.\d+(?:\.\d+)?\s*答案与解析\s*$")


def chapter_header_re():
    """答案区章节标题：一、单项选择题 / 二、综合应用题 等。"""
    return re.compile(
        r"^\s*(?:[一二三四五六七八九十][、．])?\s*(单项选择题|综合应用题|填空题|解答题)"
    )


def is_page_noise(line):
    """判断一行是否为页眉/页脚噪音（书籍标题、年份版次等）。"""
    return bool(PAGE_NOISE_RE.match(line))


# OCR 剥 "D．" 后残留行首全角点等： "．减少不必要的存储空间"
_LEADING_OPTION_PUNCT_RE = re.compile(
    r"^[\s\u3000]*[.\uFF0E\u3002\u3001\uFF0C\u00B7\u2022\u2027\u2219\u22C5]+[\s\u3000]*"
)


def clean_option_text(text):
    """去掉选项正文行首标点杂质（不剥合法内容字母）。"""
    if not text:
        return text
    return _LEADING_OPTION_PUNCT_RE.sub("", str(text).strip(), count=1)
