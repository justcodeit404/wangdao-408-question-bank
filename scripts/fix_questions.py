#!/usr/bin/env python3
"""对 questions_*.json 应用安全的自动修复：
1. 从解析文本中提取缺失的选择题答案 choice
2. 拆分题干中的子问题标记 （1）...（2）... 为 sub_questions
3. 对题干含图标记的题目设置 has_image=true，并按题目 bbox 裁剪出精准截图
4. 清理空 explanation 占位符
"""

import copy
import json
import re
import sys
from pathlib import Path

from PIL import Image

from config import image_dir_for, PROJECT_ROOT, MATH_BANK_DIR, COURSE_BY_OUT_JSON
from parse_patterns import has_real_image_ref

sys.stdout.reconfigure(encoding="utf-8")

PAGE_REVIEW_PATCHES_PATH = PROJECT_ROOT / "data" / "quality" / "page_review_patches.json"
PAGE_REVIEW_PATCH_FIELDS = {"content", "options", "choice", "explanation", "option_groups"}
OPTION_KEYS = {"A", "B", "C", "D", "E"}
ANSWER_CROP_LINE_RE = re.compile(
    r"^(?:答案图片|解析图片|题图|答图)\s*[：:]\s*answer_crops/[^\n]*", re.MULTILINE
)


def load_page_review_patches(path=PAGE_REVIEW_PATCHES_PATH):
    """Load and validate persistent original-page patches for every rebuild."""
    manifest_path = Path(path)
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError(f"invalid page review patch manifest: {manifest_path}")
    patches = {}
    for index, item in enumerate(payload["items"]):
        if not isinstance(item, dict):
            raise ValueError(f"page review patch #{index + 1} is not an object")
        course = str(item.get("course") or "").strip()
        chapter = str(item.get("chapter") or "").strip()
        qid = str(item.get("qid") or "").strip()
        fields = item.get("fields")
        if not course or not chapter or not qid or not isinstance(fields, dict) or not fields:
            raise ValueError(f"page review patch #{index + 1} has incomplete target/fields")
        unknown = sorted(set(fields) - PAGE_REVIEW_PATCH_FIELDS)
        if unknown:
            raise ValueError(f"page review patch {course}/{chapter}/{qid} has unknown fields: {unknown}")
        options = fields.get("options")
        if options is not None and (
            not isinstance(options, dict) or not options or any(
                str(key) not in OPTION_KEYS or not isinstance(value, str) or not value.strip()
                for key, value in options.items()
            )
        ):
            raise ValueError(f"page review patch {course}/{chapter}/{qid} has invalid options")
        option_groups = fields.get("option_groups")
        if option_groups is not None:
            if not isinstance(option_groups, list) or len(option_groups) < 2:
                raise ValueError(f"page review patch {course}/{chapter}/{qid} has invalid option_groups")
            for group in option_groups:
                group_options = group.get("options") if isinstance(group, dict) else None
                if (
                    not isinstance(group_options, dict) or not group_options or any(
                        str(key) not in OPTION_KEYS or not isinstance(value, str) or not value.strip()
                        for key, value in group_options.items()
                    )
                ):
                    raise ValueError(
                        f"page review patch {course}/{chapter}/{qid} has invalid option_groups options"
                    )
                if group.get("label") is not None and not isinstance(group["label"], str):
                    raise ValueError(f"page review patch {course}/{chapter}/{qid} has invalid option_groups label")
        if "choice" in fields:
            choice = str(fields["choice"]).strip().upper()
            if not choice or any(letter not in "ABCDE" for letter in choice):
                raise ValueError(f"page review patch {course}/{chapter}/{qid} has invalid choice")
            if option_groups and len(choice) != len(option_groups):
                raise ValueError(
                    f"page review patch {course}/{chapter}/{qid} choice length != option_groups length"
                )
        for key in ("content", "explanation"):
            if key in fields and (not isinstance(fields[key], str) or not fields[key].strip()):
                raise ValueError(f"page review patch {course}/{chapter}/{qid} has empty {key}")
        target = (course, chapter, qid)
        if target in patches:
            raise ValueError(f"duplicate page review patch target: {course}/{chapter}/{qid}")
        patches[target] = dict(fields)
    return patches

# 题目区域截图的四周留白（像素）
# 原 60 过大会把相邻题目也裁进来；10 足够保留插图边缘，同时最大限度避免混入邻题
CROP_PADDING = 10

# 已逐页对照原书确认的少量补丁。放在主修复流程中，避免下次全量重建又丢失。
CURATED_OPTION_PATCHES = {
    ("ds", 360, "X18"): {
        "D": "6,1,7,9,8,4,5→7,1,6,9,8,4,5→7,9,6,1,8,4,5→9,7,6,1,8,4,5→9,8,6,1,7,4,5",
    },
    # 2009 统考真题：打印缓冲区题与下一道 2012 操作符栈题在 OCR 时被串接，
    # 导致本题选项错贴成 2012 题的 5/7/8/11。已对照真题订正。
    ("ds", 100, "X12"): {
        "A": "栈",
        "B": "队列",
        "C": "树",
        "D": "图",
    },
    # 下三角按列压缩：B 选项首字符 j 被读成 Jj；其余空格规范化。
    ("ds", 110, "X08"): {
        "A": "(j-1)(2n-j+1)/2+i-j",
        "B": "(j-1)(2n-j+2)/2+i-j+1",
        "C": "(j-1)(2n-j+2)/2+i-j",
        "D": "(j-1)(2n-j+1)/2+i-j-1",
    },
    # 计组 Cache 局部性：选项 C/D 的数组下标被 OCR 截断/错位。
    ("coa", 123, "X07"): {
        "C": "将第5行改为 sum+=a[i][k][j];",
        "D": "将第5行改为 sum+=a[j][i][k];",
    },
    # 树的基本概念：选项中幂次被 OCR 扁平化（4^{i-1} → 4(i-1)）。
    ("ds", 132, "X04"): {
        "C": "第i层上至多有4^{i-1}个结点",
    },
    ("ds", 132, "X05"): {
        "B": "至多有4^h-1个结点",
        "C": "至多有4^h个结点",
    },
    # m 叉树叶结点数：纯文本 ∑(i-1)Ni+1 易被读成 N_{i+1}，改把 +1 提到求和前面。
    ("ds", 132, "X08"): {
        "D": "1 + ∑(i-1)Ni（i=2…m）",
    },
    # 完全二叉树最少结点数：OCR 丢失了指数及 h-1 中的括号。
    ("ds", 138, "X11"): {
        "A": "$2^h$",
        "B": "$2^h+1$",
        "C": "$2^{h-1}$",
        "D": "$2^h-1$",
    },
    # 完全二叉树同层判定：⌊log₂i⌋ 被 OCR 读成 [log / Llog / 」 。
    # 对照 assets/pdf_images/ds/page_139.png 第 20 题。
    ("ds", 139, "X20"): {
        "A": "⌊log₂p⌋ = ⌊log₂q⌋",
        "B": "log₂p = log₂q",
        "C": "⌊log₂p⌋ + 1 = ⌊log₂q⌋",
        "D": "⌊log₂p⌋ = ⌊log₂q⌋ + 1",
    },
    # 满二叉树 n 与 h：OCR 把 2^h 扁平化成 2h。对照 page_151.png（书页 139）+ 答案页。
    ("ds", 139, "X24"): {
        "D": "$n=2^h-1$",
    },
}

# 原书题干/解析中已人工确认的 OCR 字符修正。
CURATED_TEXT_PATCHES = {
    ("ds", 73, "X14"): {
        "content": "设a,b,c,d,e,f以所给的次序入栈，若在入栈操作时，允许出栈操作，则下面不会出现\n的出栈序列为（）。",
        "explanation": "根据栈“先进后出”的特点，且在入栈操作的同时允许出栈操作，显然选项D中c最先出栈，\n则此时栈内必定为a和b，但因为a先于b入栈，所以a要晚出栈。对于某个出栈的元素，在它之\n前入栈却晚出栈的元素必定是按逆序出栈的，其余答案均是可能出现的情况。",
    },
    ("ds", 74, "X29"): {
        "content": "【2013统考真题】一个栈的入栈序列为1,2,3,…,n，出栈序列是P1,P2,P3,…,Pn。若P2=3,\n则P3可能取值的个数是（）。",
        "explanation": "显然，3之后的4,5,...,n都是P3可取的数（一直入栈直到该数入栈后马上出栈）。接下来\n分析1和2是否可取：P1可以是3之前入栈的数（可能是1或2），也可以是4。当P1=1时，\nP3可取2；当P1=2时，P3可取1。因此，P3可能取除3外的所有数，个数为n-1。",
    },
    # page_110：B[k]、aij 被 OCR 截断/错识。
    ("ds", 110, "X08"): {
        "content": (
            "若将n阶下三角矩阵A按列优先顺序压缩存放在一维数组B[1...n(n+1)/2+1]中，"
            "则存放到B[k]中的非零元素aij（1≤i,j≤n）的下标i,j与k的对应关系是（）。"
        ),
        "explanation": (
            "按列优先存储，故元素aij前有j-1列，共有n+(n-1)+…+(n-j+2)=(j-1)(2n-j+2)/2个"
            "元素，元素aij是第j列上第i-j+1个元素，数组B的下标从1开始，"
            "k=(j-1)(2n-j+2)/2+i-j+1。"
        ),
    },
    # page_132「树的基本概念」：下标 n₀/n₁/n₂/n₃ 与幂次被 OCR 吃掉；解答题答案串题。
    # 对照 assets/pdf_images/ds/page_132.png ~ page_134.png（书页 127–129）。
    ("ds", 132, "X05"): {
        "content": "度为4、高度为h的树，（）。",
        "explanation": (
            "要使得度为4、高度为h的树的总结点数最少，需要满足以下两个条件：\n"
            "①至少有一个结点有4个分支。\n"
            "②每层的结点数尽可能少。\n"
            "情况类似右图所示的树，结点数为h+3。\n"
            "要使得度为4、高度为h的树的总结点数最多，应使每个非叶结点的度均为4，即满树，"
            "总结点数最多为$1+4+4^2+\\cdots+4^{h-1}$。\n"
            "对于上面的两题，应画出草图来求解，就能一目了然。"
        ),
    },
    ("ds", 132, "X06"): {
        "content": "假定一棵度为3的树中，结点数为50，则其最小高度为（）。",
        "explanation": (
            "要求满足条件的树，那么该树是一棵完全三叉树。在度为3的完全三叉树中，第1层有1个"
            "结点，第2层有3¹=3个结点，第3层有3²=9个结点，第4层有3³=27个结点，因此结点数之"
            "和为1+3+9+27=40，第5层的结点数=50-40=10个，因此最小高度为5。"
        ),
    },
    # 下标统一用 ASCII：n0/n1/n2/n3（不用 Unicode 下标 n₀，部分字体把 ₀ 渲成 o，像 OCR 错题）
    ("ds", 132, "X07"): {
        "content": (
            "设有一棵度为3的树，其中度为3的结点数n3=2，度为2的结点数n2=1，叶结点数"
            "n0=6，则该树的结点总数为（）。"
        ),
        "explanation": (
            "总结点数n=n0+n1+n2+n3=6+n1+1+2=n1+9，总度数=n-1="
            "n1+2n2+3n3=n1+2+6=n1+8，根据题目条件无法得出n的具体"
            "值，只能证明n是一个大于或等于9的任意整数。画出满足题目条"
            "件的树，可以是右图所示的一棵树，该树中无法确定n的具体数量。"
        ),
    },
    ("ds", 132, "X08"): {
        "content": (
            "设一棵m叉树中有N1个度数为1的结点，N2个度数为2的结点，……，Nm个度数为m的结点，"
            "则该树中共有（）个叶结点。"
        ),
        "explanation": (
            "设叶结点数为N0，总结点数为N，则N = N1+2N2+3N3+…+mNm + 1，"
            "又因为N = N0+N1+N2+…+Nm，所以"
            "N0 = N2+2N3+…+(m-1)Nm + 1 = 1 + ∑(i-1)Ni（i=2…m）。"
        ),
    },
    ("ds", 132, "X09"): {
        "content": (
            "【2010统考真题】在一棵度为4的树T中，若有20个度为4的结点，10个度为3的结点，"
            "1个度为2的结点，10个度为1的结点，则树T的叶结点数是（）。"
        ),
        "explanation": (
            "设树中度为i（i=0,1,2,3,4）的结点数分别为ni，树中结点总数为n，则n=分支数+1，"
            "而分支数又等于树中各结点的度之和，即n=1+n1+2n2+3n3+4n4=n0+n1+n2+n3+n4。依题"
            "意，n1+2n2+3n3+4n4=10+2+30+80=122，n1+n2+n3+n4=10+1+10+20=41，可得出"
            "n0=82，即树T的叶结点的个数是82。"
        ),
    },
    ("ds", 132, "A02"): {
        "content": "含有n个结点的三叉树的最小高度是多少?",
        "explanation": (
            "要求含有n个结点的三叉树的最小高度，那么满足条件的一定是一棵完全三叉树，"
            "设含有n个结点的完全三叉树的高度为h，第h层至少有1个结点，至多有3^{h-1}个结点。"
            "则有1+3^1+3^2+…+3^{h-2}<n≤1+3^1+3^2+…+3^{h-2}+3^{h-1}，"
            "即(3^{h-1}-1)/2<n≤(3^h-1)/2，得3^{h-1}<2n+1≤3^h，"
            "即h-1<log3(2n+1)≤h，h>log3(2n+1)且h≥log3(2n+1)。"
            "因为h只能为正整数，h=⌈log3(2n+1)⌉，所以这种三叉树的最小高度是⌈log3(2n+1)⌉。"
        ),
    },
    ("ds", 132, "A03"): {
        "content": (
            "已知一棵度为4的树中，度为0,1,2,3的结点数分别为14,4,3,2，求该树的结点总数n"
            "和度为4的结点数，并给出推导过程。"
        ),
        "explanation": (
            "设树中度为i（i=0,1,2,3,4）的结点数为ni，则结点总数n=n0+n1+n2+n3+n4，即n=23+n4，"
            "根据“树中所有结点的度数加1等于结点数”的结论，有n=0+n1+2n2+3n3+4n4+1，即有n="
            "17+4n4。\n"
            "综合两式得n4=2，n=25。所以该树的结点总数为25，度为4的结点数为2。"
        ),
    },
    ("ds", 132, "A04"): {
        "content": (
            "已知一棵度为m的树中，有n1个度为1的结点，有n2个度为2的结点……有nm个度为"
            "m的结点，问该树有多少个叶结点？"
        ),
        "explanation": (
            "树中的结点数等于所有结点的度数加1，因此有n=∑i·ni+1=n1+2n2+3n3+…+m·nm+1"
            "（i从0到m）。\n"
            "又有n=n0+n1+n2+…+nm，所以\n"
            "n0=(n1+2n2+3n3+…+m·nm+1)-(n1+n2+…+nm)\n"
            "=n2+2n3+…+(m-1)nm+1=1+∑(i-1)ni（i=2…m）。\n"
            "注意\n"
            "综合以上几题，常用于求解树结点与度之间关系的有：\n"
            "①总结点数=n0+n1+n2+…+nm。\n"
            "②总分支数=1·n1+2n2+…+m·nm（度为m的结点引出m条分支）。\n"
            "③总结点数=总分支数+1。\n"
            "这类题目常在选择题中出现，读者对以上关系应当熟练掌握并灵活应用。"
        ),
    },
    # page_138：完全二叉树高度为 h 时的最少结点数，原书公式为 2^{h-1}。
    ("ds", 138, "X11"): {
        "content": "高度为h的完全二叉树最少有（）个结点。",
        "explanation": (
            "高度为h的完全二叉树中，第1层～第h-1层构成一个高度为h-1的满二叉树，"
            "结点数为 $2^{h-1}-1$。第h层至少有一个结点，所以最少的结点数="
            "$(2^{h-1}-1)+1=2^{h-1}$。"
        ),
    },
    # page_139：同层判定，⌊log₂i⌋+1。对照 page_139.png + 答案页。
    ("ds", 139, "X20"): {
        "content": "在一棵完全二叉树中，其根的序号为1，（）可判定序号为p和q的两个结点是否在同一层。",
        "explanation": (
            "由完全二叉树的性质，编号为i（i≥1）的结点所在的层次为⌊log₂i⌋+1，"
            "若两个结点位于同一层，则一定有⌊log₂p⌋+1=⌊log₂q⌋+1，"
            "因此有⌊log₂p⌋=⌊log₂q⌋成立。"
        ),
    },
    # page_139：满二叉树 n=2^h-1。选项 D 的上标被 OCR 吃掉；锁定已校对解析。
    ("ds", 139, "X24"): {
        "content": "对于一棵满二叉树，共有n个结点和 m个叶结点，高度为h，则（）。",
        "explanation": (
            "对于高度为h的满二叉树，结点总数 "
            "$n=2^0+2^1+\\cdots+2^{h-1}=2^h-1$，叶结点数 $m=2^{h-1}$。"
        ),
    },
    # 三叉树最小高度：OCR 将 3^{i-1}、求和式和 ceil/log 下标压扁。
    ("ds", 139, "X22"): {
        "explanation": (
            "满足条件的三叉树可以是完全三叉树，第i（i≥1）层最多有 "
            "3^{i-1} 个结点。高度为h时，前h层最多有 "
            "1+3+\\cdots+3^{h-1}=\\dfrac{3^h-1}{2} 个结点；由 "
            "50≤(3^h-1)/2 得 h≥\\lceil\\log_3 101\\rceil=5。"
        ),
    },
    # 二叉树最大深度：OCR 将 2^6-1 的公式和数字混写。
    ("ds", 139, "X15"): {
        "explanation": (
            "要使只有度为0和2的二叉树含有126个结点且深度最大，前6层组成满二叉树，"
            "共有$2^6-1=63$个结点，剩余63个结点位于第7层，因此最大深度为7。"
        ),
    },
    # 计组定长编码：8 位可表示 2^8=256 种不同编码。
    ("coa", 32, "X07"): {
        "explanation": (
            "8 位二进制编码共有 $2^8=256$ 种不同表示。若全 0 编码表示无效，"
            "则可表示的有效编码数量相应减一；本题按题干约定选择对应选项。"
        ),
    },
    # CSMA/CD 退避窗口：第 i 次冲突的随机退避范围为 0～$2^i-1$。
    ("net", 106, "X18"): {
        "explanation": (
            "二进制指数退避算法在第i次冲突后，从0到$2^i-1$中随机选择退避时隙；"
            "达到规定的最大重传次数后再放弃发送。"
        ),
    },
    # QAM 信号状态数：4 MHz、48 Mb/s 对应 log₂V=6，即 $V=2^6=64$。
    ("net", 43, "X27"): {
        "explanation": (
            "由奈奎斯特和香农公式可知，题设条件对应每个码元携带6 bit，"
            "因此 $V=2^6=64$，采用 QAM-64 调制。"
        ),
    },
    # 性能指标计算：统一恢复 OCR 丢失的乘号、幂次和除号。
    ("coa", 18, "X09"): {
        "explanation": (
            "CPU 频率为500 MHz。程序P的指令数为 $500\\times10^6$，平均 CPI 为2.5，"
            "故执行时间为 $500\\times10^6\\div(2.5\\times10^6)=200$ ms。"
        ),
    },
    ("coa", 20, "X20"): {
        "explanation": (
            "程序P的指令数为 $5\\times10^5$，平均 CPI 为1.2，故所需时钟周期数为 "
            "$5\\times10^5\\times1.2=6\\times10^5$。"
        ),
    },
}

# 仅对已逐条核对的题目字段做字符替换，避免误伤散列表装填因子 α 等正确符号。
CURATED_CHARACTER_REPLACEMENTS = {
    # 数据结构：普通变量 a 被 OCR 误识别为 α。
    **{
        ("ds", page, qid, field): (("α", "a"),)
        for page, qid, field in (
            (25, "A11", "explanation"),
            (26, "A14", "content"),
            (26, "A14", "explanation"),
            (73, "X15", "explanation"),
            (73, "X19", "explanation"),
            (73, "X26", "explanation"),
            (73, "X27", "content"),
            (73, "X28", "explanation"),
            (88, "X20", "explanation"),
            (151, "X01", "explanation"),
            (152, "X02", "option_B"),
            (153, "X12", "option_A"),
            (153, "X12", "explanation"),
            (153, "X19", "explanation"),
            (154, "X33", "explanation"),
            (155, "X35", "explanation"),
            (155, "X38", "content"),
            (155, "X38", "explanation"),
            (155, "X39", "content"),
            (155, "X39", "explanation"),
            (156, "A10", "explanation"),
            (177, "X04", "content"),
            (177, "X04", "explanation"),
            (179, "X19", "explanation"),
            (179, "X20", "explanation"),
            (224, "X08", "explanation"),
            (243, "X14", "explanation"),
            (247, "X46", "explanation"),
        )
    },
    # 此处原书变量为带下标的 a_i。
    ("ds", 19, "X04", "explanation"): (
        ("元素α在顺序表中的位序", "元素aᵢ在顺序表中的位序"),
    ),
    # 计组：普通变量 a、z、地址 [x] 及异或符号的定点纠错。
    ("coa", 53, "A05", "explanation"): (("α", "a"),),
    ("coa", 34, "X32", "explanation"): (("ε", "z"),),
    ("coa", 190, "A05", "explanation"): (("0Φ1=1", "0⊕1=1"),),
    ("coa", 264, "A01", "content"): (("[α]", "[x]"),),
    # 2026-08 408 OCR 公式/下标专项修复（已对照原书裁剪图确认）
    ("ds", 123, "X10", "content"): (("i和」", "i和j"),),
    ("ds", 276, "X22", "content"): (("elseif", "else if"),),
    ("coa", 70, "X45", "content"): (("employee[].id", "employee[1].id"),),
    ("coa", 123, "X07", "content"): (
        ("? for(j=0;j<n;j++)", "③ for(j=0;j<n;j++)"),
        ("? sum+=a[k][j][i];", "⑤ sum+=a[k][j][i];"),
    ),
    ("coa", 186, "X04", "content"): (
        ("sum+=b[ij]", "sum+=b[i][j]"),
        ("b[i] [j]", "b[i][j]"),
    ),
    ("coa", 187, "X07", "content"): (("a[i", "a[i]"),),
    ("coa", 242, "X25", "content"): (("R[r2]-R[r1]", "R[r2]←R[r1]"),),
    ("coa", 263, "X28", "content"): (
        ("Il: add s2,sl, s0", "I1: add s2,s1, s0"),
        ("12: load s3, O(t2)", "I2: load s3, 0(t2)"),
        ("14: store s2,O(t2)", "I4: store s2,0(t2)"),
    ),
    ("coa", 263, "X30", "content"): (
        ("11 add s2,sl, s0", "I1 add s2,s1, s0"),
        ("R[s2]R[s1] + R[s0]", "R[s2]←R[s1] + R[s0]"),
        ("12 peo s3, 0(s2)", "I2 load s3, 0(s2)"),
        ("R[s3]M[R[s2] + 0]", "R[s3]←M[R[s2] + 0]"),
        ("13 beq t2,s3,L1", "I3 beq t2,s3,L1"),
        ("!ppe t2,t2,20", "I4 addi t2,t2,20"),
        ("R[t2]-R[t2]+ 20", "R[t2]←R[t2]+ 20"),
        ("15 L1:", "I5 L1:"),
        ("II1~", "I1~"),
    ),
    ("os", 122, "X36", "content"): (
        ("Po、P互斥", "P0、P1互斥"),
        ("进程 PO 进程 P1", "进程 P0 进程 P1"),
        (
            "while(flag[l]&&turn== 1); while(flag[0]&&turn==0）",
            "while(flag[1]&&turn==1); while(flag[0]&&turn==0)",
        ),
    ),
    ("os", 123, "X45", "content"): (("chopStick[(i+1)&5]", "chopStick[(i+1)%5]"),),
    ("os", 124, "X48", "content"): (
        ("进程Po和进程P", "进程P0和进程P1"),
        ("若进程P和进程P访问", "若进程P0和进程P1访问"),
        (
            "void PO () //进程Po void P1() //进程P1",
            "void P0 () //进程P0 void P1() //进程P1",
        ),
        (
            "while(flag[l]&&(turn== 1)) ; while(flag[0]&&(turn==0)）",
            "while(flag[1]&&(turn==1)) ; while(flag[0]&&(turn==0))",
        ),
    ),
}

# 原书答案页与题目页均已人工确认的答案/解析修正。
CURATED_ANSWER_PATCHES = {
    # 跨页解析被 parse_answer_page 按页切断：OCR 续页无题号前缀 → 后半段丢失。
    # 以下 4 条均对照 data/ocr/ds 答案页拼回全文（2027 王道数据结构）。
    ("ds", 87, "X01"): {
        "choice": "D",
        "explanation": (
            "栈和队列的逻辑结构都是线性结构，都可以采用顺序存储或链式存储，选项A和B错误，"
            "选项C显然也错误。只有选项D才是栈和队列的本质区别，限定表中插入和删除操作位置的不同。"
        ),
    },
    ("ds", 88, "X12"): {
        "choice": "B",
        "explanation": (
            "因为队列需在双端进行操作，所以选项C和D的链表显然不太适合链队。"
            "对于选项A，链表在完成入队和出队后还要修改为循环的，对于队列来讲这是多余的（画蛇添足）。"
            "对于选项B，因为有首指针，所以适合删除首结点；因为有队尾指针，所以适合在其后插入结点。"
        ),
    },
    ("ds", 100, "X11"): {
        "choice": "A",
        "explanation": (
            "使用栈可以模拟递归的过程，以此来消除递归，但对于单向递归和尾递归而言，可以用迭代"
            "的方式来消除递归，选项A正确。不同的入栈和出栈组合操作，会产生许多不同的输出序列，"
            "选项B错误。通常使用栈来处理函数或过程调用，选项C错误。队列和栈都是操作受限的线性表，"
            "但只有队列允许在表的两端进行运算，而栈只允许在栈顶方向进行操作，选项D错误。"
        ),
    },
    # 2009 统考真题：打印缓冲区题选项被错贴，解析保持 FIFO 逻辑。
    ("ds", 100, "X12"): {
        "choice": "B",
        "explanation": (
            "在提取数据时必须保持原来数据的顺序，所以缓冲区的特性是先进先出，应选队列。"
        ),
    },
    ("ds", 178, "X06"): {
        "choice": "D",
        "explanation": (
            "森林转换为二叉树后，二叉树的根结点及其左子树由第1棵树转换得到，"
            "二叉树的根结点的右子树由剩余的森林转换得到，以此类推，可以划分出第2、3、…棵树的结点。"
            "具有16个结点的完全二叉树的形态如右图所示，沿二叉树的根结点往右下遍历，共有4个结点，"
            "可知森林中有4棵树，其中第1棵树的结点数最多，有9个。"
        ),
    },
    ("coa", 291, "X01"): {
        "choice": "D",
        "explanation": "同步总线事务通常包括地址/命令阶段和数据阶段，需要多个时钟周期完成；地址与数据一般分时传输。现代同步总线支持突发传输，一次事务可连续传送多个数据单元，因此 D 项错误。",
    },
    ("coa", 291, "X02"): {
        "choice": "C",
        "explanation": "不同速度的设备之间既可采用异步方式，也可采用同步方式；同步控制能够传送数据，但会限制快速设备性能。",
    },
    ("coa", 291, "X03"): {
        "choice": "C",
        "explanation": "同步控制由统一时序控制，采用公共时钟和统一时钟周期，既可用于 CPU 控制，也可用于高速外部设备控制。",
    },
}

# OCR 把个别单选题的选项读坏后，会误归入“综合应用题”并串接下一题解析。
# 以下内容均已逐页对照原书确认；主流程末尾会把它们移回对应选择题章节。
CURATED_CHOICE_PATCHES = {
    ("ds", 132, "A01"): {
        "id": "X08",
        "content": "设一棵m叉树中有N1个度数为1的结点，N2个度数为2的结点，……，Nm个度数为m的结点，则该树中共有（）个叶结点。",
        "options": {
            "A": "∑(i-1)Ni（i=1…m）",
            "B": "∑Ni（i=1…m）",
            "C": "∑(i-1)Ni（i=2…m）",
            # 勿写成 ∑(i-1)Ni+1：纯文本易误读为 N_{i+1}
            "D": "1 + ∑(i-1)Ni（i=2…m）",
        },
        "answer": {
            "choice": "D",
            "explanation": (
                "设叶结点数为N0，总结点数为N，则N = N1+2N2+3N3+…+mNm + 1，"
                "又因为N = N0+N1+N2+…+Nm，所以"
                "N0 = N2+2N3+…+(m-1)Nm + 1 = 1 + ∑(i-1)Ni（i=2…m）。"
            ),
        },
    },
    ("ds", 212, "A01"): {
        "id": "X05",
        "content": "一个有n个顶点的图用邻接矩阵A表示，若图为有向图，顶点vᵢ的入度是（）；若图为无向图，顶点vᵢ的度是（）。",
        "options": {
            "A": "∑A[i][j]（i=1…n）",
            "B": "∑A[j][i]（j=1…n）",
            "C": "∑A[j][i]（i=1…n）",
            "D": "∑A[j][i]（j=1…n）或∑A[i][j]（j=1…n）",
        },
        "answer": {
            "choice": "BD",
            "explanation": "第一空选 B：有向图中第 i 列之和为 vᵢ 的入度；第二空选 D：无向图的邻接矩阵对称，第 i 行或第 i 列之和均为 vᵢ 的度。",
        },
    },
    ("ds", 342, "A01"): {
        "id": "X13",
        "content": "折半插入排序算法的时间复杂度为（）。",
        "options": {"A": "O(n)", "B": "O(nlog₂n)", "C": "O(n²)", "D": "O(n³)"},
        "answer": {
            "choice": "C",
            "explanation": "折半查找只减少比较次数，元素移动次数仍为 O(n²)，因此总时间复杂度为 O(n²)。",
        },
    },
    ("coa", 52, "A01"): {
        "id": "X31",
        "content": "【2018统考真题】减法指令“sub R1,R2,R3”的功能为“(R1)-(R2)→R3”，该指令执行后将生成进位/借位标志CF和溢出标志OF。若(R1)=FFFF FFFFH，(R2)=FFFF FFF0H，则该减法指令执行后，CF与OF分别为（）。",
        "options": {
            "A": "CF=0，OF=0",
            "B": "CF=1，OF=0",
            "C": "CF=0，OF=1",
            "D": "CF=1，OF=1",
        },
        "answer": {
            "choice": "A",
            "explanation": "FFFFFFFH−FFFFFFF0H=0000000FH，无借位且无符号溢出，因此 CF=0、OF=0。",
        },
    },
    ("coa", 52, "A02"): {
        "id": "X32",
        "content": "【2023统考真题】已知x、y为int型，当x=100、y=200时，执行“x减y”指令得到的溢出标志OF和借位标志CF分别为0、1，那么当x=10、y=-20时，执行该指令得到的OF和CF分别为（）。",
        "options": {
            "A": "OF=0，CF=0",
            "B": "OF=0，CF=1",
            "C": "OF=1，CF=0",
            "D": "OF=1，CF=1",
        },
        "answer": {
            "choice": "B",
            "explanation": "10−(−20)=30，在int范围内，不发生有符号溢出，OF=0；按无符号减法需要借位，CF=1。",
        },
    },
    ("coa", 186, "A01"): {
        "id": "X02",
        "content": "假设R[ax]=7FE6H，R[bx]=FFE8H，执行指令“sub bx,ax”后，寄存器的内容和各标志的变化为（）。",
        "options": {
            "A": "R[ax]=8002H，OF=0，SF=1，CF=1，ZF=0",
            "B": "R[bx]=8002H，OF=0，SF=1，CF=0，ZF=0",
            "C": "R[ax]=8002H，OF=1，SF=1，CF=0，ZF=0",
            "D": "R[bx]=8002H，OF=1，SF=1，CF=0，ZF=0",
        },
        "answer": {
            "choice": "B",
            "explanation": "FFE8H−7FE6H=8002H，结果写回 bx；两个操作数和结果的符号位均为 1，不发生有符号溢出，OF=0；结果为负且非零，SF=1、ZF=0，无借位，CF=0。",
        },
    },
    ("net", 75, "A01"): {
        "id": "X30",
        "content": "【2023统考真题】假设通过同一条信道，数据链路层分别采用停止-等待协议、GBN协议和SR协议（发送窗口和接收窗口相等）传输数据，三个协议的数据帧长相同，忽略确认帧长，帧序号位数为3比特。若对应三个协议的发送方最大信道利用率分别是U₁、U₂和U₃，则U₁、U₂和U₃满足的关系是（）。",
        "options": {"A": "U₁≤U₂≤U₃", "B": "U₁≤U₃≤U₂", "C": "U₂≤U₃≤U₁", "D": "U₃≤U₂≤U₁"},
        "answer": {
            "choice": "B",
            "explanation": "3比特序号下，GBN发送窗口最大为7，SR发送窗口最大为4，停止-等待窗口为1，因此 U₁≤U₃≤U₂。",
        },
    },
}

# OCR 把带 A/B/C/D 序列的综合应用题误分类为选择题。
# 以下题目已对照原书题目页和答案页确认，主流程末尾会移回解答题章节。
CURATED_APPLICATION_PATCHES = {
    ("ds", 74, "X03_2"): {
        "id": "A03",
        "content": "栈的初态和终态均为空，以I和O分别表示入栈和出栈，则出入栈的操作序列可表示为由I和O组成的序列，可以操作的序列称为合法序列，否则称为非法序列。",
        "options": None,
        "sub_questions": [
            "下面所示的序列中哪些是合法的？\nA. IOIIOIOO　B. IOOIOIIO　C. IIIOIOIO　D. IIIOOIOO",
            "通过对（1）的分析，写出一个算法，判定所给的操作序列是否合法。若合法，返回 true，否则返回 false（假定被判定的操作序列已存入一维数组中）。",
        ],
        "answer": {
            "choice": None,
            "explanation": "（1）A、D 合法，B、C 不合法。B 中先入栈 1 次，再连续出栈 2 次，出现空栈出栈；C 中入栈和出栈次数不相等，最终栈不为空。\n\n（2）扫描操作序列，用 balance 表示当前栈内元素个数。遇到 I 时 balance 加 1，遇到 O 时 balance 减 1；若任意时刻 balance 小于 0，则序列非法。扫描结束后 balance 必须等于 0。\n\nbool Judge(const char A[]) {\n    int balance = 0;\n    for (int i = 0; A[i] != '\\0'; ++i) {\n        if (A[i] == 'I') {\n            ++balance;\n        } else if (A[i] == 'O') {\n            if (--balance < 0) return false;\n        } else {\n            return false;\n        }\n    }\n    return balance == 0;\n}",
        },
    },
    # net IPv4 综合题 11：含报文图与三小问，OCR 曾误塞进选择题选项且解析串成 X11。
    ("net", 166, "X11_2"): {
        "id": "A11_2",
        "content": "主机A的IP地址为218.207.61.211，MAC地址为00:1d:72:98:1d:fc。A收到一个帧，该\n帧的前64个字节的十六进制形式和ASCII形式如下图所示。\nIP分组的首部格式见图4.5，以太网帧的格式参见3.6.2节。问：\n1）主机A所在网络的网关路由器的相应端口的MAC地址是多少?\n2）该IP分组所携带的数据量为多少字节？\n3）若该分组需要被路由器转发到一条MTU为380B的链路上，则路由器将做何种\n操作?",
        "options": None,
        "sub_questions": None,
        "has_image": True,
        "image_ref": {
            "page": 166,
            "note": "题干含报文十六进制图，已按题目区域裁剪",
            "cropped": "crops/net/page_166_X11_2.png",
        },
        "answer": {
            "choice": None,
            "explanation": "1）根据收到的帧，找出源IP地址为dac76628，表示成十进制为218.199.102.40，是一个C\n类IP地址，与A的IP地址218.207.61.211不在同一个网络中，所以需经过路由器转发。\nMAC地址只具有本地意义（ARP也只能工作在同一局域网中）。该帧为A收到的帧，因\n此目的MAC地址为A的MAC地址，源MAC地址为网关路由器端口的MAC地址（若\n为A发出的帧，则目的MAC地址为默认网关的MAC地址）。首先找到目的MAC地址\n00:1d:72:98:1d:fc的位置，根据以太网帧的结构，目的MAC地址后面紧邻的是源MAC地\n址，因此源MAC地址为00:00:5e:00:01:01。\n2）要求得IP分组所携带的数据量，需要知道首部长度和总长度。218.207.61.211表示成十\n六进制是da.cf.3d.d3，并且作为分组中的目的IP地址。在图中确定目的IP地址的位置，\n再根据IP首部的结构，分别从目的IP的位置向前数14和16个字节，即可找到总长\n度和首部长度字段的位置。但首部长度字段所在的字节值为0x45，首部长度字段只有4\n位，前4位是版本号。因此首部字段的值为5，单位为4B，所以首部长度为20B。总长度字\n段值为0x0190，十进制为400B。因此分组携带的数据长度为380B。\n3）因为整个IP分组的长度是400B，大于输出链路MTU（380B）。这时需要考虑分片，但\n是否能够分片还得看IP首部中的标志位。IP首部中的标志字段占3位，从前到后依次为\n保留位、DF、MF。根据IP首部结构找到标志字段所在的字节，其值为0x40，二进制表\n示为01000000，于是DF=1，不能对该IP分组进行分片。此时，路由器应进行的操作是\n丢弃该分组，并用ICMP差错报文向源主机报告。",
        },
    },
}


# 抽取阶段整题丢失、但原书确实存在的题（按原书页图逐题核对后收录）。
# key: (course_key, 章节名, qid)；fix_file 在对应章节内按题号顺序插入（幂等）。
# 首个案例：coa 性能指标 X18 题号块 OCR 为空（【】）被丢弃，平台侧已按坏数据导入
# （题干缺主语、年份误作 2018），此处按原书补回。
# 解析兜底编号（上一题号_2）纠正为原书题号；仅处理目标号未被占用的题。
# X35_2 → X62（net IPv4 第 62 题）；A01_2 → A03（ds 算法评价第 3 题）。
# A11_2（net IPv4 解答题）目标号 A12 已被占用，暂保留。
CURATED_ID_RENAMES = {
    ("net", "网络层 · IPv4 · 选择题", "X35_2"): "X62",
    ("ds", "绪论 · 算法和算法评价 · 解答题", "A01_2"): "A03",
}


CURATED_INSERTS = {
    ("os", "文件管理 · 文件系统 · 选择题", "X13"): {
        "id": "X13",
        "type": "选择题",
        "content": "【2014统考真题】现有一个容量为10GB的磁盘分区，磁盘空间以簇为单位进行分配，簇的大小为4KB，若采用位图法管理该分区的空闲空间，即用一位来标识一个簇是否被分配，则存放该位图所需要的簇数为（）。",
        "options": {"A": "80", "B": "320", "C": "80K", "D": "320K"},
        "sub_questions": None,
        "page": 306,
        "bbox": [195.0, 656.0, 954.0, 769.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "4.3.6 本节习题精选",
        "answer": {
            "choice": "A",
            "explanation": "簇的总数为10GB/4KB=2.5M，用一位标识一簇是否被分配，整个磁盘共需要2.5Mbit，即需要2.5M/8=320KB，因此共需要320KB/4KB=80簇。",
        },
        "q_pages": [305, 306, 307],
        "a_pages": [307, 308, 309, 310, 311, 312, 313, 314, 315, 316, 317, 318],
    },
    ("ds", "排序 · 归并排序、基数排序和计数排序 · 选择题", "X09"): {
        "id": "X09",
        "type": "选择题",
        "content": "一组经过第一趟2路归并排序后的记录的关键字为{25,50,35,15,80,85,20,40,36,70}，其中包含5个长度为2的有序表，用2路归并排序算法对该序列进行第二趟归并后的结果为（）。",
        "options": {
            "A": "15,25,35,50,80,20,85,40,70,36",
            "B": "15,25,35,50,20,40,80,85,36,70",
            "C": "15,25,50,35,80,85,20,36,40,70",
            "D": "15,25,35,50,80,20,36,40,70,85",
        },
        "sub_questions": None,
        "page": 373,
        "bbox": [150.0, 705.0, 960.0, 880.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "8.5.4 本节习题精选",
        "answer": {
            "choice": "B",
            "explanation": "这里采用2路归并排序算法，且是第二趟排序，因此每4个元素放在一起归并，可将序列划分为{25,50,15,35}，{80,85,20,40}和{36,70}，分别对它们进行排序后有{15,25,35,50}，{20,40,80,85}和{36,70}。",
        },
        "q_pages": [372, 373, 374, 375],
        "a_pages": [375, 376, 377, 378],
    },
    ("net", "计算机网络体系结构 · 计算机网络概述 · 选择题", "X16"): {
        "id": "X16",
        "type": "选择题",
        "content": "【2024统考真题】某分组交换网络及每段链路的带宽如下图所示，H1到H2的最大吞吐量约为（）。",
        "options": {"A": "1Mb/s", "B": "10Mb/s", "C": "100Mb/s", "D": "1000Mb/s"},
        "sub_questions": None,
        "page": 16,
        "bbox": [150.0, 490.0, 960.0, 700.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "1.1.7 本节习题精选",
        "answer": {
            "choice": "B",
            "explanation": "H1到H2有三条路径。H1和H2各自连接路由器的链路带宽均为10Mb/s，这是所有路径共有的端侧链路。现在假设每个数据段为10Mb，分别分析各路径的吞吐量。\n路径一：中间两段链路带宽均为1000Mb/s，受限于H1、H2直连路由器的链路带宽10Mb/s，无论中间链路有多快，数据从H1发出需1s（10Mb÷10Mb/s），到达H2前最后一跳也需1s，吞吐量约为10Mb/s。\n路径二：中间一段链路带宽为1Mb/s，H1发送一个数据段需1s，但经过中间1Mb/s链路时，转发时延为10Mb÷1Mb/s=10s（成为瓶颈），因此H2每隔10s收到一个数据段，吞吐量约为1Mb/s。\n路径三：中间两段链路带宽均为100Mb/s，与路径一的分析类似，吞吐量约为10Mb/s。\n由此可见，端到端的吞吐量由路径中带宽最小的链路（瓶颈）决定。",
        },
        "q_pages": [14, 15, 16, 17],
        "a_pages": [17, 18, 19, 20, 21, 22, 23, 24, 25, 26],
    },
    ("net", "计算机网络体系结构 · 计算机网络体系结构与参考模型 · 选择题", "X30"): {
        "id": "X30",
        "type": "选择题",
        "content": "【2010统考真题】下列选项中不属于网络体系结构所描述的内容是（）。",
        "options": {
            "A": "网络的层次",
            "B": "每层使用的协议",
            "C": "协议的内部实现细节",
            "D": "每层必须完成的功能",
        },
        "sub_questions": None,
        "page": 30,
        "bbox": [150.0, 210.0, 960.0, 300.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "1.2.4 本节习题精选",
        "answer": {
            "choice": "C",
            "explanation": "网络体系结构是指各层及其协议的集合，涵盖网络的层次划分、每层的功能及所用的协议，因此选项A、B、D均属于描述内容。而协议的内部实现细节属于实现问题，不由体系结构规定。",
        },
        "q_pages": [27, 28, 29, 30],
        "a_pages": [30, 31, 32, 33, 34, 35, 36, 37, 38, 39],
    },
    ("net", "传输层 · UDP · 选择题", "X16"): {
        "id": "X16",
        "type": "选择题",
        "content": "【2024统考真题】UDP在计算检验和的过程中，计算得到中间结果为1011 1001 1011 0110时，还需要加上最后一个16位数0110 0101 1100 0101，最终计算得到的检验和是（）。",
        "options": {
            "A": "0001 1111 0111 1011",
            "B": "0001 1111 0111 1100",
            "C": "1110 0000 1000 0011",
            "D": "1110 0000 1000 0100",
        },
        "sub_questions": None,
        "page": 237,
        "bbox": [150.0, 1150.0, 960.0, 1262.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "5.2.3 本节习题精选",
        "answer": {
            "choice": "C",
            "explanation": "UDP检验和的计算方法是二进制反码求和再取反。反码求和规则：①从低位到高位逐列相加；②若最高位相加后产生进位，则把该进位加到结果的最低位（回卷）。\n1011 1001 1011 0110\n+ 0110 0101 1100 0101\n= 1 0001 1111 0111 1011\n回卷：0001 1111 0111 1100\n再取反：1110 0000 1000 0011，故选C。",
        },
        "q_pages": [236, 237, 238],
        "a_pages": [238, 239, 240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 250],
    },
    ("coa", "计算机系统概述 · 计算机的性能指标 · 选择题", "X18"): {
        "id": "X18",
        "type": "选择题",
        "content": "【2021统考真题】2017年公布的全球超级计算机TOP 500排名中，我国“神威·太湖之光”超级计算机蝉联第一，其浮点运算速度为93.0146PFLOPS，说明该计算机每秒完成的浮点操作次数约为（）。",
        "options": {
            "A": "9.3×10^13次",
            "B": "9.3×10^15次",
            "C": "9.3千万亿次",
            "D": "9.3亿亿次",
        },
        "sub_questions": None,
        "page": 20,
        "bbox": [153.0, 303.0, 954.0, 418.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "1.3.2 本节习题精选",
        "answer": {
            "choice": "D",
            "explanation": "PFLOPS=每秒千万亿（10^15）次浮点运算。故93.0146PFLOPS≈每秒9.3×10^16次浮点运算，即每秒9.3亿亿次浮点运算。",
        },
        "q_pages": [20],
        "a_pages": [20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31],
    },


    ("ds", "栈、队列和数组 · 栈和队列的应用 · 选择题", "X13"): {
        "id": "X13",
        "type": "选择题",
        "content": "【2012统考真题】已知操作符包括“+”“-”“*”“/”“（”和“）”。将中缀表达式 a+b-a*((c+d)/e-f)+g 转换为等价的后缀表达式 ab+acd+e/f-*-g+ 时，用栈来存放暂时还不能确定运算次序的操作符。栈初始时为空，转换过程中同时保存在栈中的操作符的最大个数是（）。",
        "options": {"A": "5", "B": "7", "C": "8", "D": "11"},
        "sub_questions": None,
        "page": 100,
        "bbox": [150.0, 1000.0, 980.0, 1120.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "3.3.3 本节习题精选",
        "answer": {
            "choice": "A",
            "explanation": "中缀转后缀时，扫描到操作数直接输出，操作符按优先级入栈/出栈；本题转换过程中栈内操作符最多同时保存 5 个，故选 A。",
        },
        "q_pages": [100],
        "a_pages": [101, 102, 103, 104, 105],
    },

    ("coa", "输入/输出系统 · I/O接口 · 选择题", "X14"): {
        "id": "X14",
        "type": "选择题",
        "content": "【2012统考真题】下列选项中，在I/O总线的数据线上传输的信息包括（）。\nI. I/O接口中的命令字\nII. I/O接口中的状态字\nIII. 中断类型号",
        "options": {"A": "仅I、II", "B": "仅I、III", "C": "仅II、III", "D": "I、II、III"},
        "sub_questions": None,
        "page": 302,
        "bbox": [155.0, 350.0, 980.0, 420.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "7.2.5 本节习题精选",
        "answer": {
            "choice": "D",
            "explanation": "数据缓冲寄存器和命令/状态寄存器的内容都通过数据线传送；中断类型号也由数据线送 CPU，故 I、II、III 均包括。",
        },
        "q_pages": [302],
        "a_pages": [303, 304, 305, 306],
    },

    ("net", "数据链路层 · 局域网 · 选择题", "X23"): {
        "id": "X23",
        "type": "选择题",
        "content": "IEEE 802局域网标准对应OSI参考模型的（）。",
        "options": {"A": "数据链路层和网络层", "B": "物理层和数据链路层", "C": "物理层", "D": "数据链路层"},
        "sub_questions": None,
        "page": 107,
        "bbox": [150.0, 510.0, 980.0, 590.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "3.5.4 本节习题精选",
        "answer": {
            "choice": "B",
            "explanation": "IEEE 802 为局域网制定的标准相当于 OSI 参考模型的数据链路层和物理层；数据链路层又分为 LLC 和 MAC 两个子层。",
        },
        "q_pages": [107],
        "a_pages": [108, 109, 110, 111, 112, 113],
    },

    ("net", "传输层 · TCP · 选择题", "X48"): {
        "id": "X48",
        "type": "选择题",
        "content": "甲始终向乙以MSS=1KB大小的段发送数据，并一直有数据发送；乙为该连接分配16KB接收缓存，并对每个数据段进行确认，忽略段传输延迟。若乙收到的数据全部存入缓存，不被取走，则甲从连接建立成功时刻起，未出现发送超时的情况下，经过4RTT后，甲的发送窗口是（）。",
        "options": {"A": "1KB", "B": "8KB", "C": "16KB", "D": "32KB"},
        "sub_questions": None,
        "page": 256,
        "bbox": [155.0, 300.0, 980.0, 440.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "5.3.4 本节习题精选",
        "answer": {
            "choice": "A",
            "explanation": "发送窗口=min{接收窗口，拥塞窗口}。慢开始前 4 个 RTT 分别发送 1/2/4/8KB，累计 15KB；接收缓存仅剩 1KB，故发送窗口为 1KB。",
        },
        "q_pages": [256],
        "a_pages": [257, 258, 259, 260, 261, 262, 263, 264, 265],
    },

    ("net", "网络层 · IPv6 · 选择题", "X03"): {
        "id": "X03",
        "type": "选择题",
        "content": "下列关于IPv6地址1A22:120D:0000:0000:72A2:0000:0000:00C0的表示中，错误的是（）。",
        "options": {
            "A": "1A22:120D::72A2:0000:0000:00C0",
            "B": "1A22:120D::72A2:0:0:C0",
            "C": "1A22::120D::72A2::00C0",
            "D": "1A22:120D:0:0:72A2::C0",
        },
        "sub_questions": None,
        "page": 189,
        "bbox": [150.0, 1150.0, 980.0, 1230.0],
        "has_image": False,
        "image_ref": None,
        "topic_title": "4.4.4 本节习题精选",
        "answer": {
            "choice": "C",
            "explanation": "一个IPv6地址中双冒号“::”只能出现一次；选项 C 出现多个“::”，表示错误。",
        },
        "q_pages": [189],
        "a_pages": [190, 191, 192, 193, 194],
    },
}


def _qid_number(qid: str) -> int | None:
    m = re.search(r"(\d+)$", str(qid or ""))
    return int(m.group(1)) if m else None


def apply_curated_inserts(chapter: dict, course_key: str | None, fixes: dict) -> None:
    """把 CURATED_INSERTS 中属于本章且尚不存在的题按题号插入；已存在则跳过。"""
    chapter_name = str(chapter.get("name") or "").strip()
    existing = {str(q.get("id") or "") for q in chapter.get("questions", [])}
    for (key, ch_name, qid), question in CURATED_INSERTS.items():
        if key != course_key or ch_name != chapter_name or qid in existing:
            continue
        num = _qid_number(qid)
        pos = len(chapter["questions"])
        if num is not None:
            for i, q in enumerate(chapter["questions"]):
                n = _qid_number(str(q.get("id") or ""))
                if n is not None and n < num:
                    pos = i + 1
        chapter["questions"].insert(pos, copy.deepcopy(question))
        chapter["question_count"] = len(chapter["questions"])
        existing.add(qid)
        fixes["curated_inserted"] += 1


def apply_curated_choice_patches(data, course_key):
    """修复并移动已核对的误分类单选题，返回实际应用数量。"""
    applied = 0
    for (key, page, old_id), patch in CURATED_CHOICE_PATCHES.items():
        if key != course_key:
            continue
        # 已完成过首次移动时，旧 Axx 题已不存在；仍需刷新目标题，保证补丁修改
        # 在后续重复构建中生效。
        existing = next(
            (
                q
                for ch in data.get("chapters", [])
                for q in ch.get("questions", [])
                if int(q.get("page") or 0) == page
                and str(q.get("id") or "") == patch["id"]
                and q.get("type") == "选择题"
            ),
            None,
        )
        if existing is not None:
            if any(existing.get(field) != value for field, value in patch.items()):
                existing.update(patch)
                existing["type"] = "选择题"
                existing["sub_questions"] = None
                applied += 1
            continue
        source_ch = None
        question = None
        for ch in data.get("chapters", []):
            for q in ch.get("questions", []):
                if int(q.get("page") or 0) == page and str(q.get("id") or "") == old_id:
                    source_ch, question = ch, q
                    break
            if question is not None:
                break
        if question is None or source_ch is None:
            continue

        target_name = re.sub(
            r"\s*·\s*解答题\s*$", " · 选择题", source_ch.get("name") or ""
        )
        target_ch = next(
            (ch for ch in data.get("chapters", []) if ch.get("name") == target_name),
            None,
        )
        if target_ch is None:
            raise ValueError(f"找不到补丁目标章节: {target_name}")
        if any(q.get("id") == patch["id"] for q in target_ch.get("questions", [])):
            raise ValueError(f"补丁题号冲突: {target_name} {patch['id']}")

        source_ch["questions"].remove(question)
        question.update(patch)
        question["type"] = "选择题"
        question["sub_questions"] = None
        target_ch["questions"].append(question)
        target_ch["questions"].sort(
            key=lambda q: (
                int(re.search(r"\d+", str(q.get("id") or "9999")).group()),
                str(q.get("id") or ""),
            )
        )
        applied += 1

    for ch in data.get("chapters", []):
        ch["question_count"] = len(ch.get("questions", []))
    data["total_questions"] = sum(
        ch["question_count"] for ch in data.get("chapters", [])
    )
    return applied


def apply_curated_application_patches(data, course_key):
    """修复并移动已核对的误分类综合应用题，返回实际应用数量。"""
    applied = 0
    for (key, page, old_id), patch in CURATED_APPLICATION_PATCHES.items():
        if key != course_key:
            continue
        existing = next(
            (
                q
                for ch in data.get("chapters", [])
                for q in ch.get("questions", [])
                if int(q.get("page") or 0) == page
                and str(q.get("id") or "") == patch["id"]
                and q.get("type") == "解答题"
            ),
            None,
        )
        if existing is not None:
            changed = False
            if any(existing.get(field) != value for field, value in patch.items()):
                existing.update(patch)
                existing["type"] = "解答题"
                changed = True
            # 某些历史构建同时保留了误分类 Xxx 和正确 Axx，需删除重复的选择题副本。
            for ch in data.get("chapters", []):
                stale = [
                    q
                    for q in ch.get("questions", [])
                    if int(q.get("page") or 0) == page
                    and str(q.get("id") or "") == old_id
                    and q.get("type") == "选择题"
                ]
                for q in stale:
                    ch["questions"].remove(q)
                    changed = True
            if changed:
                applied += 1
            continue

        source_ch = None
        question = None
        for ch in data.get("chapters", []):
            for q in ch.get("questions", []):
                if int(q.get("page") or 0) == page and str(q.get("id") or "") == old_id:
                    source_ch, question = ch, q
                    break
            if question is not None:
                break
        if question is None or source_ch is None:
            continue

        target_name = re.sub(
            r"\s*·\s*选择题\s*$", " · 解答题", source_ch.get("name") or ""
        )
        target_ch = next(
            (ch for ch in data.get("chapters", []) if ch.get("name") == target_name),
            None,
        )
        if target_ch is None:
            raise ValueError(f"找不到综合应用题补丁目标章节: {target_name}")
        if any(q.get("id") == patch["id"] for q in target_ch.get("questions", [])):
            raise ValueError(f"综合应用题补丁题号冲突: {target_name} {patch['id']}")

        source_ch["questions"].remove(question)
        question.update(patch)
        question["type"] = "解答题"
        target_ch["questions"].append(question)
        target_ch["questions"].sort(
            key=lambda q: (
                int(re.search(r"\d+", str(q.get("id") or "9999")).group()),
                str(q.get("id") or ""),
            )
        )
        applied += 1

    for ch in data.get("chapters", []):
        ch["question_count"] = len(ch.get("questions", []))
    data["total_questions"] = sum(
        ch["question_count"] for ch in data.get("chapters", [])
    )
    return applied


def apply_curated_character_replacements(q, course_key):
    """应用已核对的字段级字符纠错，返回是否发生修改。"""
    page = int(q.get("page") or 0)
    qid = str(q.get("id") or "")
    changed = False
    for field in (
        "content",
        "explanation",
        "option_A",
        "option_B",
        "option_C",
        "option_D",
    ):
        replacements = CURATED_CHARACTER_REPLACEMENTS.get(
            (course_key, page, qid, field)
        )
        if not replacements:
            continue
        if field == "content":
            current = q.get("content") or ""
        elif field == "explanation":
            current = (q.get("answer") or {}).get("explanation") or ""
        else:
            current = (q.get("options") or {}).get(field[-1]) or ""
        updated = current
        for old, new in replacements:
            updated = updated.replace(old, new)
        if updated == current:
            continue
        if field == "content":
            q["content"] = updated
        elif field == "explanation":
            answer = q.get("answer") or {}
            answer["explanation"] = updated
            q["answer"] = answer
        else:
            options = q.get("options") or {}
            options[field[-1]] = updated
            q["options"] = options
        changed = True
    return changed


# 页眉/页脚噪音：每页顶部/底部可能出现书名，前面可能带页码
# 如 "2027年数据结构考研复习指导" 或 "8 2027年数据结构考研复习指导"
PAGE_NOISE_RE = re.compile(
    r"\n\s*(?:\d+\s+)?\d{4}年.{0,20}考研复习指导\s*$", re.MULTILINE
)
PAGE_NOISE_START_RE = re.compile(r"^\s*(?:\d+\s+)?\d{4}年.{0,20}考研复习指导\s*\n")
# 行内/任意行：书名页眉
BOOK_TITLE_LINE_RE = re.compile(
    r"^\s*(?:\d+\s+)?\d{4}年.{0,25}考研复习指导\s*$",
    re.MULTILINE,
)
BOOK_TITLE_INLINE_RE = re.compile(
    r"(?:\d+\s+)?2027年(?:数据结构|计算机组成原理|计算机网络|操作系统)?考研复习指导"
)

# 章节页眉/页脚：
# - "第2章线性表 19" / "第 4章 指令系统 153"（带页码）
# - "第1章 绪 论" / "第1章绪论"（跨页时整行掉进代码题干，无页码）
CHAPTER_PAGE_NOISE_RE = re.compile(
    r"^\s*第\s*\d+\s*章\s*[^\n]{0,40}?(?:\s+\d{1,3})?\s*$",
    re.MULTILINE,
)
# 选项/题干末尾粘连的章节页脚（不一定单独成行）
CHAPTER_FOOTER_TRAIL_RE = re.compile(
    r"[\n\r\s]*第\s*\d+\s*章\s*[^\n]{0,40}?\s+\d{1,3}\s*$"
)
# 答案区标题误入
ANSWER_SECTION_NOISE_RE = re.compile(
    r"^\s*\d+(?:\.\d+)+\s*[～~\-—]*\s*答案与解析\s*$",
    re.MULTILINE,
)
# 单独页码行（OCR 常把页码夹在代码中间）
LONE_PAGE_NUM_RE = re.compile(r"^\s*\d{1,3}\s*$", re.MULTILINE)


def clean_content(content):
    """清理题干/解析中的页眉页脚与跨页章节标题噪音。"""
    if not content:
        return content
    # 去掉末尾单独一行的噪音
    content = PAGE_NOISE_RE.sub("", content)
    # 去掉开头单独一行的噪音（理论上较少）
    content = PAGE_NOISE_START_RE.sub("", content)
    content = BOOK_TITLE_LINE_RE.sub("", content)
    content = BOOK_TITLE_INLINE_RE.sub("", content)
    # 去掉章节页眉/页脚行（含「第1章 绪 论」这类无页码标题）
    content = CHAPTER_PAGE_NOISE_RE.sub("", content)
    content = ANSWER_SECTION_NOISE_RE.sub("", content)
    # 去掉行末粘连的「第X章… 页码」
    content = CHAPTER_FOOTER_TRAIL_RE.sub("", content)
    # 去掉夹在中间的纯页码行（前后都是内容时才删，避免误伤「答案 01」类）
    lines = content.split("\n")
    cleaned_lines = []
    for i, line in enumerate(lines):
        if LONE_PAGE_NUM_RE.match(line):
            # 仅当上下行都像正文/代码时丢弃孤立页码
            prev_ok = i > 0 and lines[i - 1].strip() != ""
            next_ok = i + 1 < len(lines) and lines[i + 1].strip() != ""
            if prev_ok and next_ok:
                continue
        cleaned_lines.append(line)
    content = "\n".join(cleaned_lines)
    # 压缩因删行产生的多余空行
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def clean_option_text(text):
    """清理选项中粘连的章节页脚，如 '与数组a的元素次序相反\\n第2章线性表 41'。"""
    if not text:
        return text
    text = CHAPTER_FOOTER_TRAIL_RE.sub("", str(text))
    text = CHAPTER_PAGE_NOISE_RE.sub("", text)
    text = BOOK_TITLE_LINE_RE.sub("", text)
    return text.strip()


# 题干中常见的插图标注 / OCR 误识别的图注碎片
# xau/π 是 OCR 将图注/箭头误识别成的无意义字符；<- 在 C/C++ 题干中通常也是图注箭头
DIAGRAM_ARTIFACT_PATTERNS = [
    # 2012 统考真题“loading 和 being 共同后缀”一题的图注碎片
    r"^\s*strl[、,，]?\s*$",
    r"^\s*str2\s*$",
    r"^\s*[→\-~]+\s*n\s*[→\-~]+\s*g\s*$",
    # 无意义的 OCR 乱码
    r"\bxau\b",
    r"π",
]
DIAGRAM_ARTIFACT_RE = re.compile(
    "|".join(f"({p})" for p in DIAGRAM_ARTIFACT_PATTERNS), re.MULTILINE
)

# 从图注碎片行中抢救被混入的选项，如 "N==x-==<- ' B. L->prior==NULL&&L->next==NULL"
OPTION_IN_GARBAGE_RE = re.compile(
    r"([A-Da-d])[\.．、]\s*(.+?)(?=\s+[A-Da-d][\.．、]\s*|$)", re.DOTALL
)


def is_diagram_artifact_line(line):
    """判断一行是否为图注/OCR 碎片行。

    注意：像 'x<-16' 这种数学比较式虽然包含 '<-' 子串，但不是图注碎片，
    需要排除。
    """
    if not line.strip():
        return False
    # 明确的 OCR 乱码
    if re.search(r"\bxau\b|π", line):
        return True
    # 图注选项标签行，如 "(d) ad<-d=xau..."
    if re.match(r"^\s*[（(]\s*d\s*[）)]", line):
        return True
    # 包含 <- 箭头时，需排除数学比较式（如 x<-16, a<-b 且整体为合法表达式）
    if "<-" in line:
        # 行首为 ! : = 等图注符号，肯定是碎片
        if re.match(r"^\s*[!:=]", line):
            return True
        # 若只有一个 <- 且前后是 ASCII 标识符/数字（比较式），保留
        arrows = re.findall(r"<-(?!=)", line)
        if len(arrows) == 1 and "->" not in line:
            m = re.search(r"([A-Za-z0-9_]+)<-(-?[A-Za-z0-9_]+)", line)
            if m:
                return False
        # 多个 <- 或混有 -> 等，视为图注箭头碎片
        return True
    return False


# 罗马数字，避免被误当作图注标签块清理
_ROMAN_NUMERALS = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
_LABEL_LINE_RE = re.compile(r"^[A-Za-z0-9\s]+$")


def _is_label_line(line):
    """判断一行是否为图注标签行：仅含字母/数字/空格，长度<=4，且非罗马数字。"""
    s = line.strip()
    if not s or len(s) > 4 or s in _ROMAN_NUMERALS:
        return False
    return bool(_LABEL_LINE_RE.match(s))


def _strip_trailing_label_block(lines):
    """移除题干末尾的连续图注标签块，如：
       ALU\nCO\nB\nM\nMAR\nPC  或单独一行的 P。
    返回 (清理后的行列表, 被移除的行数)。"""
    if not lines:
        return lines, 0
    # 从末尾找连续标签行
    end = len(lines)
    while end > 0 and _is_label_line(lines[end - 1]):
        end -= 1
    label_block = lines[end:]
    if not label_block:
        return lines, 0
    # 只有一行时，仅当它是单个字符才清理（避免误删合法短缩写）
    if len(label_block) == 1 and len(label_block[0].strip()) > 1:
        return lines, 0
    # 多行标签块中若包含过长行（3-4字符），确认这是标签列表：
    # 块中至少有一行长度<=2，或者块长度>=2且全部<=4（已满足）
    if len(label_block) >= 2 and not any(len(l.strip()) <= 2 for l in label_block):
        return lines, 0
    return lines[:end], len(label_block)


_BLANK_MARK_RE = re.compile(r"（\s*）|\(\s*\)|（\s*[）)]")
_STMT_PREFIX_RE = re.compile(r"^\s*(?:[IVXⅠⅡⅢⅣⅤⅥⅦ]+[.．、]|[①-⑩]|[A-Da-d][.．、])")
_INLINE_STMT_RE = re.compile(r"^\s*(?:I{1,3}|IV|V|VI{0,3}|Ⅰ|Ⅱ|Ⅲ|Ⅳ)[^\s.．、]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CJK_PUNCT_RE = re.compile(r"[。，、；：（）()！]")
_CODE_SYMBOL_RE = re.compile(r"[=;{}\[\]<>]")
_TABLE_DATA_RE = re.compile(
    r"\d+\.\d+\.\d+\.\d+|(?i:\b(?:[0-9a-f]{2}-){5}[0-9a-f]{2}\b)|\b0x[0-9a-fA-F]+\b"
)
_TOKEN_RE = re.compile(r"[A-Za-z]{1,6}|\d+(?:\.\d+)?(?:[A-Za-z/]+)?")
# 题图里常见的标签词（中文标注）——出现在题干尾部且无句读时按图注碎片处理
_FIG_LABEL_WORDS = (
    "路由器", "交换机", "集线器", "网桥", "服务器", "主机", "发送方", "接收方",
    "电路交换", "报文交换", "分组交换", "链路", "时延", "传播", "帧", "端口",
    "地址", "时间", "丢失", "互联网", "局域网", "以太网", "接入点", "带宽",
)


def _looks_like_fig_junk(text):
    """判断一段文字是否像图内标签被 OCR 拼成的碎片。

    排除：陈述行（I./II./①/A.）、表格、代码块、箭头、带中文句读的正文。
    """
    s = text.strip()
    if not s or len(s) > 80:
        return False
    if _STMT_PREFIX_RE.match(s) or _INLINE_STMT_RE.match(s):
        return False
    if s.rstrip().endswith(("？", "?")):
        return False
    if "|" in s or "```" in s or "→" in s:
        return False
    # 表格数据：IP/CIDR、MAC、十六进制串一律不动（可能是题干里的路由表/转发表）
    if _TABLE_DATA_RE.search(s):
        return False
    has_cjk = bool(_CJK_RE.search(s))
    if has_cjk and _CJK_PUNCT_RE.search(s):
        return False
    if not has_cjk:
        return False
    return any(w in s for w in _FIG_LABEL_WORDS)


def strip_trailing_after_last_blank(content):
    """选择题：最后一个（　）之后只允许陈述行，其余按图注碎片清掉。

    只作用于空格符所在行及其后的行；正文句读齐全时一律不动。
    """
    if not content or not _BLANK_MARK_RE.search(content):
        return content
    lines = content.split("\n")
    idx = max(i for i, line in enumerate(lines) if _BLANK_MARK_RE.search(line))
    marks = list(_BLANK_MARK_RE.finditer(lines[idx]))
    head = lines[idx][: marks[-1].end()]
    tail = lines[idx][marks[-1].end():]
    if tail:
        bare = tail.lstrip("。，、；：.")
        if bare and _looks_like_fig_junk(bare):
            lines[idx] = head + ("。" if tail.startswith("。") else "")
    kept = lines[:idx]
    kept.append(lines[idx])
    kept.extend(ln for ln in lines[idx + 1:] if not _looks_like_fig_junk(ln))
    return "\n".join(kept).strip()


def fix_ocr_zero_letter_o(text: str) -> str:
    """数字语境中把 OCR 把 0 误识成 O/o/Ｏ 的情况改回 0。

    刻意避开：
    - 大 O 复杂度 O(n)、O(1)
    - 栈操作序列中的 I/O
    - I/O 设备、标识符中间的字母 O
    """
    if not text:
        return text

    # 数组下标：A[O] / A[O..5] / A[O...n] / a[0][O] / d[O]
    text = re.sub(r"([A-Za-z])\[([OoＯ])(?=[\].\d…～~])", r"\1[0", text)
    text = re.sub(r"\[([OoＯ])\]", "[0]", text)

    # 下标区间起点：O..n / O...n / O～n-1（不在字母后）
    text = re.sub(r"(?<![A-Za-z0-9_])[OoＯ](?=\.\.|\.\.\.|…|～|~)", "0", text)

    # 中文数量/返回值语境：入度为O、返回O、值为O、都为O、等于O
    text = re.sub(
        r"(入度|出度|度数?|返回|等于|初值|取值|都为|值为|为)[OoＯ](?![A-Za-z(（])",
        r"\g<1>0",
        text,
    )

    # 比较：==O / <=O / O== 等（排除 O( 复杂度；排除线代零矩阵 E=O / A=O）
    # 注意：单独的 =O 常表示零矩阵，不能改成 =0
    text = re.sub(r"(==|!=|<=|>=)\s*[OoＯ](?![A-Za-z(（0-9])", r"\1 0", text)
    text = re.sub(r"(?<![A-Za-z0-9_])[OoＯ]\s*(==|!=|<=|>=|<|>)", r"0\1", text)
    # 严格小于/大于后的孤立 O（入度>O 等），但避免 A=O / E=O 零矩阵
    text = re.sub(r"([<>])\s*[OoＯ](?![A-Za-z(（0-9])", r"\g<1>0", text)

    # 选项/并列数字：3和O、O和5（排除「I和O」栈操作：要求 O 侧邻数字或句读）
    text = re.sub(r"(?<=\d)和[OoＯ](?![A-Za-z(（])", "和0", text)
    text = re.sub(r"(?<![A-Za-z0-9_])[OoＯ]和(?=\d)", "0和", text)

    # 括号/逗号中的孤立 O：F(O)、S(O)、(1,4,O)
    text = re.sub(r"([,，(（])\s*[OoＯ](?=\s*[,，)）])", r"\g<1>0", text)
    text = re.sub(r"([A-Za-z_]\w*)\(\s*[OoＯ]\s*\)", r"\1(0)", text)

    # 十六进制字面量中的字母 o：0x000o0111 → 0x00000111
    text = re.sub(r"(0[xX][0-9A-Fa-f]*)[oO](?=[0-9A-Fa-f])", r"\g<1>0", text)

    # 二进制/比特串中的 O：0111111O → 01111110
    text = re.sub(r"(?<=[01])[OoＯ](?=[01])", "0", text)
    text = re.sub(r"(?<=[01])[OoＯ](?![A-Za-z0-9_])", "0", text)

    return text


def fix_ocr_letter_l_as_one(text: str) -> str:
    """指针/算术语境中把 +l / n+l 误识改回 +1（不依赖整段是否像代码）。"""
    if not text:
        return text
    # rear+l / front+l / n+l / MaxSize 上下文
    text = re.sub(
        r"\b(rear|front|top|MaxSize|maxsize|n|m)\s*\+\s*l\b",
        r"\1+1",
        text,
        flags=re.IGNORECASE,
    )
    # (...+l) / +l% / +l)
    text = re.sub(r"\+\s*l(?=\s*[)）%])", "+1", text)
    return text


def fix_ocr_missing_mod_percent(text: str) -> str:
    """循环队列等题中取模符号 % 被 OCR 丢掉的常见形态。

    例：
      front=(front+1)6 → front=(front+1)%6
      (rear+1)(n+1) → (rear+1)%(n+1)

    刻意保守：不匹配普通数学连乘 (a)(b)，避免误插入 %。
    """
    if not text:
        return text
    # 队指针自增后直接跟容量数字：front=(front+1)6
    text = re.sub(
        r"(\b(?:front|rear|top)\b[^\n]{0,40}?\+\s*1\s*[)）])\s*(?=\d)",
        r"\1%",
        text,
        flags=re.IGNORECASE,
    )
    # )( 之间漏 %，右侧仅 n+1 / MaxSize（不含裸数字，避免 (f)(1-x) 类数学式）
    text = re.sub(
        r"([)）])\s*(?=[(（](?:n\s*\+\s*1|MaxSize|maxsize)\b)",
        r"\1%",
        text,
        flags=re.IGNORECASE,
    )
    return text


def fix_common_ocr_errors(text):
    """修正 OCR 常见错误，如图论题中 V5 被误识别为 Vs、罗马数字被误识别。"""
    if not text:
        return text
    # V5 被误识别为 Vs；V5s 是 Vs 后再多识别一个 s
    text = re.sub(r"(?<![A-Za-z0-9_])V5s(?![A-Za-z0-9_])", "V5", text)
    text = re.sub(r"(?<![A-Za-z0-9_])Vs(?![A-Za-z0-9_])", "V5", text)
    # 小写 v5 被误识别为 vs（出现在选项序列中）
    text = re.sub(r"(?<![A-Za-z0-9_])vs(?![A-Za-z0-9_])", "v5", text)

    # 罗马数字 OCR 修正：OCR 常把 II/III 识别成全角罗马数字与字母 I 的混合
    # 如 ⅡI -> II、IⅢI -> III、ⅢI -> III、ⅠI -> II
    text = text.replace("ⅡI", "II").replace("IⅢI", "III").replace("ⅢI", "III")
    text = text.replace("ⅠI", "II").replace("ⅠⅠ", "II").replace("ⅠⅠⅠ", "III")
    # 剩余全角罗马数字统一转成 ASCII
    text = (
        text.replace("Ⅰ", "I")
        .replace("Ⅱ", "II")
        .replace("Ⅲ", "III")
        .replace("Ⅳ", "IV")
        .replace("Ⅴ", "V")
        .replace("Ⅵ", "VI")
        .replace("Ⅶ", "VII")
        .replace("Ⅷ", "VIII")
        .replace("Ⅸ", "IX")
        .replace("Ⅹ", "X")
    )
    text = text.replace("é", "e")
    # ASCII 罗马数字粘连：IIII / IIIl / IIl
    text = re.sub(r"I{4,}", "III", text)
    text = re.sub(r"III[lL]", "III", text)
    text = re.sub(r"(?<![A-Za-z])IIl(?![A-Za-z])", "III", text)
    text = re.sub(r"(?<![A-Za-z])IIL(?![A-Za-z])", "III", text)

    # 时间复杂度中 O 被误识别为 0 / ○ / 〇，如 0(n) ○(1) -> O(n) O(1)
    # 必须先于「O→0」数字修正，避免误伤后再回不去。
    # 仅匹配复杂度常见形态；排除 0(n=1,2,…) 这类「大于 0，下标从 n=」数学写法。
    text = re.sub(
        r"(?<![A-Za-z0-9_])[0○〇]\(\s*(?![nN]\s*=)"
        r"((?:n|m|N|M|1|log|lg|ln)(?:\s*[\^*²₃]?[^)=]*)?)\s*\)",
        r"O(\1)",
        text,
    )

    # 数字 0 被误识别为字母 O（数组下标、入度、返回值等）
    text = fix_ocr_zero_letter_o(text)
    # rear+l / n+l 等 1 被误识别为 l
    text = fix_ocr_letter_l_as_one(text)
    # 取模 % 丢失
    text = fix_ocr_missing_mod_percent(text)

    # 数组下标 A□ -> A[]（常见于排序/顺序表题）
    text = re.sub(r"([A-Za-z])□", r"\1[]", text)
    # 二进制语境：变成O / 变成０ -> 变成0
    text = re.sub(r"变成\s*[OＯ〇]", "变成0", text)
    text = re.sub(r"([01])\s*变成\s*[OＯ〇]", r"\1变成0", text)
    # Null 误识别
    text = re.sub(r"(?<![A-Za-z])Vull(?![A-Za-z])", "Null", text)
    text = re.sub(r"(?<![A-Za-z])Nuli(?![A-Za-z])", "Null", text)
    # 指数常见 OCR：2"-1 / 2n-1 在滑动窗口题中常为 2^n-1（保守：仅匹配带引号形式）
    text = re.sub(r'2["”″]+\s*-\s*1', "2^n-1", text)
    return text


_CODE_HINT_RE = re.compile(
    r"\b(void|int|for|while|if|else|return|printf|scanf|typedef|struct|char|float|double)\b"
    r"|[;{}]|==|!=|<=|>=|\+\+|--"
)


def looks_like_code(text: str) -> bool:
    if not text:
        return False
    return bool(_CODE_HINT_RE.search(text)) and (
        "{" in text
        or "for(" in text
        or "while(" in text
        or "void " in text
        or "int " in text
    )


def fix_code_ocr_digits(text: str) -> str:
    """代码语境中把 OCR 把数字 1 误识成字母 l 的常见情况改回。"""
    if not text:
        return text
    # n==l / i==l / n<=l / n>=l / n!=l
    text = re.sub(r"\b([A-Za-z_]\w*)\s*(==|!=|<=|>=|<|>)\s*l\b", r"\1\2 1", text)
    # for(i=l; / for(j=l; / for(k=l;
    text = re.sub(r"for\s*\(\s*([A-Za-z_]\w*)\s*=\s*l\b", r"for(\1=1", text)
    # i=l; j=l, 初始化（避免破坏 label / long 等标识符：仅单字母变量）
    text = re.sub(r"\b([ijkmnxyz])\s*=\s*l\b", r"\1=1", text)
    # n-l / n+l / fact(n-l)
    text = re.sub(r"([A-Za-z0-9_\)\]])\s*-\s*l\b", r"\1-1", text)
    text = re.sub(r"([A-Za-z0-9_\)\]])\s*\+\s*l\b", r"\1+1", text)
    # (y+l) (x+l)
    text = re.sub(r"\(\s*([A-Za-z_]\w*)\s*\+\s*l\s*\)", r"(\1+1)", text)
    # A[j+l] 等
    text = re.sub(r"\[\s*([A-Za-z_]\w*)\s*\+\s*l\s*\]", r"[\1+1]", text)
    return text


def balance_c_braces(text: str) -> str:
    """若题干含 C 风格代码且 { 多于 }，尽量补全 }。

    王道 PDF 跨页时结尾大括号常被裁掉，导致「代码不完整」观感。
    额外处理：`...printf(...)\\nelse{` 这种 if 块未闭合直接接 else。
    """
    if not text or not looks_like_code(text):
        return text
    # if { ... else{ 且 else 前缺少 }
    text = re.sub(
        r'([;"\)\n])\s*\n\s*else\s*\{',
        r"\1\n}else{",
        text,
    )
    open_n = text.count("{")
    close_n = text.count("}")
    if open_n > close_n:
        missing = open_n - close_n
        # 插在文本末尾；若末尾是中文说明句则插在代码与说明之间
        m = re.search(r"(\n[^\n{;}]{8,}[。？！；]\s*)$", text)
        if m and looks_like_code(text[: m.start()]):
            text = text[: m.start()] + ("\n" + "}" * missing) + text[m.start() :]
        else:
            text = text.rstrip() + "\n" + "}" * missing
    elif close_n > open_n:
        # 去掉文末多余的 }
        extra = close_n - open_n
        while extra > 0 and re.search(r"\}\s*$", text):
            text = re.sub(r"\}\s*$", "", text.rstrip())
            extra -= 1
        text = text.rstrip()
    return text


def fix_code_in_content(text: str) -> str:
    """综合修复代码题题干：数字误识 + 缺失大括号。"""
    if not text or not looks_like_code(text):
        # 仍修复杂度记号
        text = re.sub(r"(?<![A-Za-z0-9_])[0○〇]\(([^)]+)\)", r"O(\1)", text or "")
        return text
    text = fix_code_ocr_digits(text)
    # A[+1] OCR 漏 j → A[j+1]
    text = re.sub(r"A\[\s*\+\s*1\s*\]", "A[j+1]", text)
    text = balance_c_braces(text)
    # 压缩代码区内多余空行
    text = re.sub(r"\{\n\n+", "{\n", text)
    return text


def fix_big_o_option(text: str) -> str:
    """选项里的复杂度记号规范化。"""
    if not text:
        return text
    t = str(text).strip()
    t = re.sub(r"(?<![A-Za-z0-9_])[0○〇]\(([^)]+)\)", r"O(\1)", t)
    # O(3/n) 常见误识 → O(n^{1/3})（立方根，while i*i*i<=n）
    if re.fullmatch(r"O\s*\(\s*3\s*/\s*n\s*\)", t.replace(" ", "")):
        t = "O(n^{1/3})"
    # O(<n) / O(√n) 保留 √；O(nl/2) → O(n^{1/2})
    t = re.sub(r"O\s*\(\s*nl\s*/\s*2\s*\)", r"O(n^{1/2})", t)
    t = re.sub(r"O\s*\(\s*n1\s*/\s*2\s*\)", r"O(n^{1/2})", t)
    return t


def clean_option_trailing_punct(text):
    """清理选项末尾的异常标点，如 OCR 把题干右括号误识别进选项：'链式存储方式》'。"""
    if not text:
        return text
    # 删除末尾单独的 》，除非文本中包含 《
    if text.endswith("》") and "《" not in text:
        text = text[:-1]
    # 删除末尾单独的 ），除非文本中包含 （
    if text.endswith("）") and "（" not in text:
        text = text[:-1]
    return text.rstrip()


# 选项标签，支持 A./A．/A、 等
OPTION_LABEL_RE = re.compile(r"([B-D])[\.．、]\s*")


def split_merged_options(options):
    """拆分被合并到前一个选项里的选项，如 A: '抽象数据类型B．逻辑结构' -> A+B 分离。
    返回 (是否发生拆分, 新 options)。"""
    if not options:
        return False, options
    changed = False
    new_opts = dict(options)
    for letter in "ABC":
        if letter not in new_opts:
            continue
        text = new_opts[letter]
        nxt = chr(ord(letter) + 1)
        # 在当前选项文本中查找下一个选项标签（如 B. / B．）
        m = OPTION_LABEL_RE.search(text)
        if not m:
            continue
        split_pos = m.start()
        prefix = text[:split_pos].rstrip()
        suffix = text[m.end() :].strip()
        found_label = m.group(1)
        # 仅当发现的标签正好是当前选项的下一个字母时才拆分
        if found_label == nxt and prefix and suffix:
            new_opts[letter] = prefix
            new_opts[found_label] = suffix
            changed = True
    return changed, new_opts


def clean_diagram_artifacts(content, options=None):
    """清理题干中混入的图注/箭头碎片，如 'strl、'、'→n→g'、'str2'、'xau...'。
    同时从碎片行中抢救 A./B./C./D. 选项文本，补充到 options 字典中。"""
    if not content:
        return content
    options = options or {}
    lines = content.split("\n")

    # 1. 清理题干末尾的图注标签块
    lines, _ = _strip_trailing_label_block(lines)
    # 1.5 选择题：最后一个（　）之后的图注碎片（中文标签、单位串、时序标注）
    if options:
        stripped = strip_trailing_after_last_blank("\n".join(lines))
        lines = stripped.split("\n")

    # 2. 清理行内/行间 OCR 箭头碎片
    cleaned_lines = []
    for line in lines:
        if is_diagram_artifact_line(line):
            # 尝试抢救该行中的选项
            for m in OPTION_IN_GARBAGE_RE.finditer(line):
                letter = m.group(1).upper()
                text = m.group(2).strip().replace("\n", " ")
                if letter not in options and text:
                    options[letter] = text
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    cleaned = DIAGRAM_ARTIFACT_RE.sub("", cleaned)
    # OCR 常把 str1 误识别为 strl；在题干中纠正好让正文更自然
    cleaned = re.sub(r"(?<![A-Za-z0-9_])strl(?![A-Za-z0-9_])", "str1", cleaned)
    cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned)
    return cleaned.strip()


def extract_choice_from_explanation(expl):
    """从解析文本中提取答案字母，如 '答案：C'、'【答案】C'、'答案 C'、'答案：B、D'。"""
    if not expl:
        return None
    patterns = [
        r"[\【\[]?答案[\】\]]?[:：\s]+([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)",
        r"答案[:：\s]*([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)",
        r"[\【\[]答案[\】\]][\s:：]*([A-Ga-g](?:[、,，\s]+[A-Ga-g])*)",
    ]
    for p in patterns:
        m = re.search(p, expl)
        if m:
            return "".join(re.findall(r"[A-Ga-g]", m.group(1))).upper()
    return None


# 圆圈数字与阿拉伯数字的映射，用于 OCR 修正和子问题拆分
_CIRCLE_NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLE_TO_ARABIC = {c: i + 1 for i, c in enumerate(_CIRCLE_NUMBERS)}
_ARABIC_TO_CIRCLE = {i + 1: c for i, c in enumerate(_CIRCLE_NUMBERS)}
_CIRCLE_RE = re.compile("[" + _CIRCLE_NUMBERS + "]")
_CODE_LINE_RE = re.compile(
    r"\b(if|else|for|while|return|void|int|char|float|double|printf|scanf)\b|[{};]|=|\+\+|--|\[.*\]"
)


def looks_like_code(line):
    """判断一行文本是否像代码行（用于 OCR 圆圈数字修正）。"""
    return bool(_CODE_LINE_RE.search(line))


def fix_circle_number_ocr(content):
    """修正 OCR 把圆圈数字识别为单独阿拉伯数字行的问题。

    例如：
      i++;
      2 y=0;
    其中单独一行的 '2' 出现在代码段之间，应修正为 '②'。
    """
    if not content:
        return content
    lines = content.split("\n")
    new_lines = []
    for i, line in enumerate(lines):
        s = line.strip()
        # 处理行首单独出现的 2-9，可能后面跟着子问题内容（如 "2 y=0;"）
        m = re.match(r"^([2-9])\s+(.*)$", s)
        if m:
            num, rest = m.group(1), m.group(2)
            prev = lines[i - 1] if i > 0 else ""
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            # 前后都是代码行，或当前行剩余部分像代码，才修正为圆圈数字
            if looks_like_code(prev) and looks_like_code(nxt) and looks_like_code(rest):
                new_lines.append(_ARABIC_TO_CIRCLE.get(int(num), num) + " " + rest)
                continue
        new_lines.append(line)
    return "\n".join(new_lines)


def split_sub_questions(content):
    """识别题干中的子问题标记并拆分。

    支持：
      - 圆圈数字：①、②、③ …
      - 中文括号：（1）、（2）…
      - 半角括号：(1)、(2) …

    如果第一个子问题没有显式标记（如 OCR 漏识别），但主题干后面紧跟着代码段，
    则把主题干之后、第一个标记之前的代码段作为第一个子问题。

    返回 (主题干, [子问1, 子问2, ...])。如果无法拆分，返回 (content, None)。
    """
    if not content:
        return content, None

    # 先修正 OCR 常见的圆圈数字误识别
    content = fix_circle_number_ocr(content)

    # 收集圆圈数字标记位置及其数字
    markers = []
    for m in _CIRCLE_RE.finditer(content):
        markers.append((m.start(), _CIRCLE_TO_ARABIC[m.group(0)]))

    # 按位置排序
    markers.sort(key=lambda x: x[0])

    # 至少需要两个显式圆圈数字标记；如果只有一个标记但主题干后面紧跟着代码段，
    # 且主题干明确提示有多个子问题（如"各程序段""下列""分别"），才可推断第一个
    # 子问题没有标记，按两个子问题处理。
    main_preview = content[: markers[0][0]].strip() if markers else content.strip()
    first_marker_num = markers[0][1] if markers else 0
    implicit_hint_words = ["各", "下列", "分别"]
    has_implicit_hint = any(w in main_preview for w in implicit_hint_words)
    has_implicit_first = (
        len(markers) == 1
        and first_marker_num > 1
        and has_implicit_hint
        and "\n" in content
        and looks_like_code(content)
    )
    if len(markers) < 2 and not has_implicit_first:
        return content, None

    main = content[: markers[0][0]].strip()
    subs = []

    # 如果主题干后面紧跟着代码/内容，说明第一个子问题没有标记
    # 把主题干中第一行之后的部分作为第一个子问题
    if "\n" in main and looks_like_code(main) and has_implicit_hint:
        first_newline = content.find("\n")
        main = content[:first_newline].strip()
        first_sub = content[first_newline + 1 : markers[0][0]].strip()
        if first_sub:
            subs.append(first_sub)

    for i, (pos, num) in enumerate(markers):
        start = pos
        end = markers[i + 1][0] if i + 1 < len(markers) else len(content)
        sub = content[start:end].strip()
        if sub:
            subs.append(sub)
    return main, subs if subs else None


# 题干中暗示图位于右侧/下方的关键词
RIGHT_IMAGE_MARKERS = ["右图", "右下图", "右上图"]
LEFT_IMAGE_MARKERS = ["左图", "左下图", "左上图"]
BELOW_IMAGE_MARKERS = ["下图", "如下图所示", "见下图", "给出下图"]
ABOVE_IMAGE_MARKERS = ["上图", "见上图", "给出上图"]


def crop_question_image(page_path, page, bbox, course_key, qid, content=""):
    """按题目文本 bbox 裁剪对应页图片，保存到 math-bank/crops/<course_key>/ 下。
    若题干含"右图/左图"等提示，会相应扩展裁剪范围以包含插图。
    返回输出路径；若失败返回 None。"""
    try:
        img = Image.open(page_path)
    except Exception as e:
        print(f"[crop error] open {page_path}: {e}")
        return None
    w, h = img.size
    x0, y0, x1, y1 = bbox
    x0 = max(0, int(x0) - CROP_PADDING)
    y0 = max(0, int(y0) - CROP_PADDING)
    x1 = min(w, int(x1) + CROP_PADDING)
    y1 = min(h, int(y1) + CROP_PADDING)

    # 根据题干中的图位置提示扩展裁剪区域。
    # 实践中"右图"的图常在题干右侧，OCR 给出的 bbox 宽度可能未覆盖插图，
    # 因此把右侧边界扩展到页面右边缘（保留少量边距）。
    if content:
        if any(m in content for m in RIGHT_IMAGE_MARKERS):
            x1 = min(w, max(x1, w - 20))
        if any(m in content for m in LEFT_IMAGE_MARKERS):
            x0 = max(0, min(x0, 20))

    if x1 <= x0 or y1 <= y0:
        return None
    cropped = img.crop((x0, y0, x1, y1))
    out_dir = MATH_BANK_DIR / "crops" / course_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"page_{page:03d}_{qid}.png"
    cropped.save(out_path, "PNG")
    return out_path


def existing_stem_crop(course_key, page, qid):
    """已有 auto_recrop / 人工裁图优先于按 bbox 重裁，避免盖掉更准的图。"""
    if not course_key or page is None or not qid:
        return None
    try:
        page_i = int(page)
    except (TypeError, ValueError):
        return None
    path = MATH_BANK_DIR / "crops" / course_key / f"page_{page_i:03d}_{qid}.png"
    if not path.exists():
        return None
    return path.relative_to(MATH_BANK_DIR).as_posix()


def detect_image_ref(q, pdf_images_dir, course_key=None):
    """如果题干含图标记且所在页有截图，返回 image_ref。
    优先沿用已有裁图；否则按题目 bbox 裁剪；没有 bbox 时回退到整页原图。"""
    content = q.get("content") or ""
    if not has_real_image_ref(content):
        return None
    page = q.get("page")
    if not page:
        return None
    existing = existing_stem_crop(course_key, page, q.get("id"))
    if existing:
        return {"page": page, "note": "题干含图，沿用已有裁图", "cropped": existing}
    page_file = f"page_{int(page):03d}.png"
    candidates = [
        pdf_images_dir / page_file,
        PROJECT_ROOT / "assets/pdf_images/ds" / page_file,
    ]
    page_path = None
    for p in candidates:
        if p.exists():
            page_path = p
            break
    if not page_path:
        return None

    bbox = q.get("bbox")
    if bbox and course_key:
        crop_path = crop_question_image(
            page_path, page, bbox, course_key, q.get("id", "00"), content=content
        )
        if crop_path:
            rel = crop_path.relative_to(MATH_BANK_DIR).as_posix()
            return {"page": page, "note": "题干含图，已按题目区域裁剪", "cropped": rel}

    # 回退：关联整页原图
    rel = page_path.relative_to(PROJECT_ROOT).as_posix()
    if not rel.startswith("../"):
        rel = "../" + rel
    return {"page": page, "note": "题干含图，已关联到原题页", "cropped": rel}


def fix_file(path, pdf_images_dir=None, course_key=None, apply_page_review_patches=None):
    path = Path(path)
    if course_key is None:
        course = COURSE_BY_OUT_JSON.get(path.name)
        course_key = getattr(course, "key", None) if course else None
    if apply_page_review_patches is None:
        apply_page_review_patches = path.resolve().parent == (PROJECT_ROOT / "output").resolve()
    page_review_patches = (
        load_page_review_patches() if apply_page_review_patches else {}
    )
    course_page_patches = {
        key: value for key, value in page_review_patches.items()
        if key[0] == course_key
    }
    applied_page_patches = set()
    data = json.load(open(path, encoding="utf-8"))
    fixes = {
        "choice_filled": 0,
        "sub_questions_split": 0,
        "image_ref_added": 0,
        "empty_explanation_cleaned": 0,
        "content_noise_cleaned": 0,
        "curated_option_patched": 0,
        "curated_character_patched": 0,
        "curated_text_patched": 0,
        "curated_answer_patched": 0,
        "page_review_patched": 0,
        "curated_inserted": 0,
    }

    for ch in data.get("chapters", []):
        chapter_name = str(ch.get("name") or ch.get("topic_title") or "").strip()
        existing_ids = {str(item.get("id") or "") for item in ch.get("questions", [])}
        for q in ch.get("questions", []):
            renamed = CURATED_ID_RENAMES.get(
                (course_key, chapter_name, str(q.get("id") or ""))
            )
            if renamed and renamed not in existing_ids:
                existing_ids.discard(str(q.get("id") or ""))
                q["id"] = renamed
                existing_ids.add(renamed)
                fixes["curated_id_renamed"] = fixes.get("curated_id_renamed", 0) + 1
            # 清理历史误拆：选择题不应有 sub_questions
            if q.get("type") == "选择题" and q.get("sub_questions"):
                q["content"] = (
                    q.get("content", "") + "\n" + "\n".join(q.get("sub_questions", []))
                ).strip()
                q["sub_questions"] = None

            ans = q.get("answer") or {}
            expl = (ans.get("explanation") or "").strip()
            # 快照既有答案图片行：下游补丁整段替换 explanation 时若未带上它们，会被静默丢掉
            answer_crop_lines = [m.group(0) for m in ANSWER_CROP_LINE_RE.finditer(expl)]

            # 1. 提取缺失的选择题答案
            if q.get("type") == "选择题" and not ans.get("choice") and expl:
                choice = extract_choice_from_explanation(expl)
                if choice:
                    ans["choice"] = choice
                    q["answer"] = ans
                    fixes["choice_filled"] += 1

            # 2. 清理题干中的页眉/页脚噪音（含跨页「第X章…」掉进代码）
            content = q.get("content") or ""
            cleaned = clean_content(content)
            # 3. 清理图注 / OCR 箭头碎片，同时从碎片中抢救选项
            options = q.get("options") or {}
            cleaned2 = clean_diagram_artifacts(cleaned, options)
            if cleaned2 != content or options != q.get("options"):
                q["content"] = cleaned2
                if options:
                    q["options"] = options
                fixes["content_noise_cleaned"] += 1
            else:
                q["content"] = cleaned2

            # 3.5 全局 OCR 错误修正（Vs→V5 等）+ 代码补全 + 选项页脚
            before_code = q.get("content") or ""
            q["content"] = fix_common_ocr_errors(before_code)
            q["content"] = fix_code_in_content(q["content"])
            if q["content"] != before_code:
                fixes["content_noise_cleaned"] += 1
            if q.get("options"):
                for k, v in list(q["options"].items()):
                    v = clean_option_text(v)
                    v = fix_common_ocr_errors(v)
                    v = fix_big_o_option(v)
                    q["options"][k] = clean_option_trailing_punct(v)
                # 3.6 拆分被合并的选项（如 A 里包含 B.）
                changed, new_opts = split_merged_options(q["options"])
                if changed:
                    q["options"] = new_opts
                    fixes["content_noise_cleaned"] += 1
                # 3.6.5 选项键按 A/B/C/D 排序（OCR 双栏读序常变成 A,C,D,B）
                opts = q.get("options") or {}
                if isinstance(opts, dict) and len(opts) > 1:
                    ordered = {
                        k: opts[k] for k in sorted(opts.keys(), key=lambda x: str(x))
                    }
                    if list(opts.keys()) != list(ordered.keys()):
                        q["options"] = ordered
                        fixes["content_noise_cleaned"] += 1
                # 3.7 选项重复时，尝试把 OCR 坏掉的复杂度选项拉开（常见 A/C 同为 O(n)）
                vals = [
                    str(q["options"].get(k, "")).strip()
                    for k in "ABCD"
                    if k in q["options"]
                ]
                if vals and len(vals) != len(set(vals)):
                    # 仅对「全是 O(...)」且有重复的选择题做轻量修正留给专项补丁
                    pass

            patch = CURATED_OPTION_PATCHES.get(
                (course_key, int(q.get("page") or 0), str(q.get("id") or ""))
            )
            if patch:
                current = q.get("options") or {}
                changed = any(current.get(k) != v for k, v in patch.items())
                if changed:
                    current.update(patch)
                    q["options"] = current
                    fixes["curated_option_patched"] += 1

            if apply_curated_character_replacements(q, course_key):
                ans = q.get("answer") or {}
                expl = (ans.get("explanation") or "").strip()
                fixes["curated_character_patched"] += 1

            text_patch = CURATED_TEXT_PATCHES.get(
                (course_key, int(q.get("page") or 0), str(q.get("id") or ""))
            )
            if text_patch:
                changed = False
                if "content" in text_patch and q.get("content") != text_patch["content"]:
                    q["content"] = text_patch["content"]
                    changed = True
                current_answer = q.get("answer") or {}
                if "explanation" in text_patch and current_answer.get("explanation") != text_patch["explanation"]:
                    current_answer["explanation"] = text_patch["explanation"]
                    q["answer"] = current_answer
                    ans = current_answer
                    expl = current_answer["explanation"]
                    changed = True
                if changed:
                    fixes["curated_text_patched"] += 1

            answer_patch = CURATED_ANSWER_PATCHES.get(
                (course_key, int(q.get("page") or 0), str(q.get("id") or ""))
            )
            if answer_patch and q.get("answer") != answer_patch:
                q["answer"] = dict(answer_patch)
                ans = q["answer"]
                expl = ans["explanation"]
                fixes["curated_answer_patched"] += 1

            # 8. 原书逐页复核补丁：这是正式构建输入，不是仅供审计的报告。
            page_patch_key = (course_key, chapter_name, str(q.get("id") or "").strip())
            page_patch = course_page_patches.get(page_patch_key)
            if page_patch is not None:
                if "content" in page_patch:
                    q["content"] = page_patch["content"]
                if "options" in page_patch:
                    # 整表替换：update 会残留历史垃圾键（邻题 JSON、图注等）
                    current_options = dict(q.get("options") or {})
                    current_options.update(page_patch["options"])
                    if set(page_patch["options"]) >= {"A", "B", "C", "D"}:
                        q["options"] = dict(sorted(page_patch["options"].items()))
                    else:
                        q["options"] = current_options
                if "option_groups" in page_patch:
                    q["option_groups"] = [
                        {
                            "label": str(group.get("label") or index + 1),
                            "options": dict(sorted(group["options"].items())),
                        }
                        for index, group in enumerate(page_patch["option_groups"])
                    ]
                elif "option_groups" in q:
                    q.pop("option_groups", None)
                ans = q.get("answer") or {}
                if "choice" in page_patch:
                    ans["choice"] = str(page_patch["choice"]).strip().upper()
                if "explanation" in page_patch:
                    ans["explanation"] = page_patch["explanation"]
                if ans:
                    q["answer"] = ans
                expl = (ans.get("explanation") or "").strip()
                choice = str(ans.get("choice") or "").strip().upper()
                if choice and q.get("type") == "选择题":
                    option_keys = set(q.get("options") or {})
                    for group in q.get("option_groups") or []:
                        option_keys |= set(group.get("options") or {})
                    if any(letter not in option_keys for letter in choice):
                        raise ValueError(
                            f"page review patch {course_key}/{chapter_name}/{q.get('id')} leaves answer choice without option"
                        )
                applied_page_patches.add(page_patch_key)
                fixes["page_review_patched"] += 1
            ans = q.get("answer") or {}
            if answer_crop_lines and not ANSWER_CROP_LINE_RE.search(
                ans.get("explanation") or ""
            ):
                ans["explanation"] = (
                    "\n".join(answer_crop_lines)
                    + "\n\n"
                    + (ans.get("explanation") or "").strip()
                )
                q["answer"] = ans
            if ans.get("explanation"):
                ans["explanation"] = fix_code_in_content(
                    fix_common_ocr_errors(clean_content(ans["explanation"]))
                )
                q["answer"] = ans

            # 5. 拆分子问题（仅解答题，避免选择题选项中的编号被误拆）
            if not q.get("sub_questions") and q.get("type") != "选择题":
                main, subs = split_sub_questions(cleaned)
                if subs:
                    q["content"] = main
                    q["sub_questions"] = subs
                    fixes["sub_questions_split"] += 1

            # 6. 图片关联
            ref = q.get("image_ref")
            cropped_missing = (
                ref
                and ref.get("cropped")
                and not (MATH_BANK_DIR / ref["cropped"]).exists()
            )
            needs_image = (
                not q.get("has_image")
                or not ref
                or not ref.get("cropped")
                or cropped_missing
            )
            if needs_image:
                new_ref = detect_image_ref(
                    q, pdf_images_dir or image_dir_for(path.name), course_key=course_key
                )
                if new_ref:
                    q["has_image"] = True
                    q["image_ref"] = new_ref
                    fixes["image_ref_added"] += 1

            # 7. 清理空 explanation
            if ans and not ans.get("choice") and not expl:
                if (
                    "answer" in q
                    and q["answer"] is not None
                    and not any(q["answer"].values())
                ):
                    q["answer"] = None
                    fixes["empty_explanation_cleaned"] += 1

        apply_curated_inserts(ch, course_key, fixes)

    missing_page_patches = sorted(set(course_page_patches) - applied_page_patches)
    # 真实 output 构建必须覆盖该课程的所有补丁；小型 fixture 可以显式
    # 只验证单条补丁的应用，不应被整套清单的其它课程题目阻塞。
    strict_page_review_targets = path.resolve().parent == (PROJECT_ROOT / "output").resolve()
    if missing_page_patches and strict_page_review_targets:
        raise ValueError(
            "page review patch target not found in output: "
            + ", ".join("/".join(key) for key in missing_page_patches[:3])
        )

    fixes["curated_choice_reclassified"] = apply_curated_choice_patches(
        data, course_key
    )
    fixes["curated_application_reclassified"] = apply_curated_application_patches(
        data, course_key
    )
    data["total_questions"] = sum(
        ch["question_count"] for ch in data.get("chapters", [])
    )
    out_path = path
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Fixed {path}: {fixes}")
    return fixes


def main():
    files = sys.argv[1:] or [
        "output/questions.json",
        "output/questions_coa.json",
        "output/questions_net.json",
        "output/questions_os.json",
    ]
    total = {}
    for fn in files:
        p = Path(fn)
        if not p.exists():
            print(f"[skip] {fn} not found")
            continue
        fixes = fix_file(p, image_dir_for(p.name))
        for k, v in fixes.items():
            total[k] = total.get(k, 0) + v
    print(f"总计修复: {total}")


if __name__ == "__main__":
    main()
