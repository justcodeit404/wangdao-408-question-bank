"""题干尾部图注碎片清理（选择题空格符之后的非陈述行）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fix_questions import strip_trailing_after_last_blank  # noqa: E402


def test_strips_chinese_label_tail():
    src = (
        "【2020统考真题】下图所示的网络中，冲突域和广播域的个数分别是（）。"
        "以太网交换机甲端100Base-T集线器"
    )
    assert strip_trailing_after_last_blank(src) == (
        "【2020统考真题】下图所示的网络中，冲突域和广播域的个数分别是（）。"
    )


def test_strips_inline_label_between_blank_and_statements():
    src = "右图描述的协议要素是（）。接收方发送方\nI.语法\nII.语义\nIII.时序"
    assert strip_trailing_after_last_blank(src) == (
        "右图描述的协议要素是（）。\nI.语法\nII.语义\nIII.时序"
    )


def test_keeps_routing_table_rows():
    src = (
        "该分组应该被转发到（）下一跳路由器。目的网络 下一跳路由器\n"
        "132.0.0.0/8 R1\n132.0.0.0/11 R2\n0.0.0.0/0 R4"
    )
    assert strip_trailing_after_last_blank(src) == src


def test_keeps_mac_table_and_markdown():
    src = "端口与地址如下（）。交换机 转发表\n| 接口 | MAC |\n00-E5-78-4A-09-B2"
    assert strip_trailing_after_last_blank(src) == (
        "端口与地址如下（）。\n| 接口 | MAC |\n00-E5-78-4A-09-B2"
    )


def test_keeps_code_and_no_blank_content():
    code = "下列程序段的时间复杂度是（）。\nint i=1;\nwhile(i<=n) i=i*2;"
    assert strip_trailing_after_last_blank(code) == code
    plain = "下列关于Cookie的说法中，错误的是（）。"
    assert strip_trailing_after_last_blank(plain) == plain
