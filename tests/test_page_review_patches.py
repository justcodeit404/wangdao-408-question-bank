import json
from pathlib import Path

import pytest

from fix_questions import fix_file, load_page_review_patches

BANK = Path(__file__).resolve().parents[1] / "math-bank"


def _load(course: str) -> dict:
    return json.loads((BANK / f"data-{course}.json").read_text(encoding="utf-8"))


def _q(course: str, chapter_part: str, qid: str) -> dict:
    data = _load(course)
    for chapter in data["chapters"]:
        if chapter_part in str(chapter.get("name") or "") and "选择" in str(
            chapter.get("name") or ""
        ):
            for question in chapter["questions"]:
                if question.get("id") == qid:
                    return question
    raise AssertionError(f"missing {course} {qid}")


def test_coa_trap_has_split_option_d():
    question = _q("coa", "异常和中断机制", "X01")
    assert "D" in question["options"]
    assert "内核" in question["options"]["D"]
    assert "异常情况" in question["options"]["C"]
    assert question["options"]["C"] != question["options"]["D"]


def test_coa_visible_registers_options_and_answer():
    question = _q("coa", "控制器的功能和工作原理", "X26")
    assert question["options"]["B"] != question["options"]["C"]
    assert "III" in question["options"]["C"]
    assert question["answer"]["choice"] == "B"


def test_ds_scan_star_stem_not_truncated():
    question = _q("ds", "栈和队列的应用", "X14")
    assert "当扫描到" in question["content"]
    assert "*" in question["content"]


def test_ds_circular_queue_end_pointers_not_duplicated():
    question = _q("ds", " · 队列 · ", "X22")
    assert question["options"]["A"] != question["options"]["B"]
    assert "end1==end2" in question["options"]["A"]


def test_ds_2012_preorder_uses_latin_a_not_alpha():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X35")
    assert "α" not in question["content"]
    assert "a,e,b,d,c" in question["content"].replace(" ", "")
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "b,c,d,e,a" in compact


def test_ds_x12_preorder_uses_latin_a_not_alpha():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X12")
    assert "α" not in question["content"]
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "先序序列是" in compact
    assert "a...b" in compact or "a.…b" in compact or "...a..." in compact
    assert "b" in compact
    for option in question["options"].values():
        assert "α" not in option


def test_ds_x33_2010_threaded_tree_stem_not_ocr_null():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X33")
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "Null" not in question["content"]
    assert "A.B.C" not in compact
    assert "后序线索树定义的是" in compact
    assert question.get("has_image") is True
    assert (question.get("image_ref") or {}).get("cropped") == "crops/ds/page_154_X33.png"
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "题目图片：crops/ds/page_154_X33.png" in expl


def test_ds_2022_inorder_neighbors_split_roman_items():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X41")
    content = question["content"]
    assert "Iq是p的双亲" not in content
    assert "I. q是p的双亲" in content
    assert "II. q是p的右孩子" in content
    assert "III. q是p的右兄弟" in content
    assert "IV. q是p的双亲的双亲" in content
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "α是p的双亲" not in expl
    assert "{p,9)" not in expl
    assert "{p,q}" in expl
    assert "说法III不可能" in expl
    assert expl.rstrip().endswith("说法III不可能。")


def test_ds_2024_inorder_uses_q_not_nine():
    question = _q("ds", "二叉树的遍历和线索二叉树", "X43")
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "P,V,9" not in compact
    assert "p,v,q" in compact
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "因此g不存在" not in expl
    assert "因此q不存在" in expl


def test_ds_forest_x01_roman_items_and_floor_log():
    question = _q("ds", "树、森林", "X01")
    content = question["content"]
    assert "I对于" not in content
    assert "I. 对于有n个结点的二叉树，其高度为 ⌊log₂ n⌋" in content
    assert "II. 完全二叉树中，若一个结点没有左孩子，则它必是叶结点" in content
    assert "III. 高度为h（h>0）的完全二叉树对应的森林所含的树的个数一定是h" in content
    assert "\nIV. 一棵树中的叶子数一定等于与其对应的二叉树的叶子数" in content
    assert "\n\nIV." not in content
    assert content.count("III.") == 1
    assert "log2n" not in content.replace(" ", "")
    patches = load_page_review_patches()
    fields = patches[("ds", "树与二叉树 · 树、森林 · 选择题", "X01")]
    assert fields["content"] == content
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "答案图片：crops/ds/page_181_X01_forest.png" in expl
    assert "page_181_X01_1.png" not in expl
    assert expl == fields["explanation"]
    crop_dir = BANK / "crops" / "ds"
    assert (crop_dir / "page_181_X01_forest.png").is_file()


def test_ds_forest_x03_keeps_m_subscripts():
    question = _q("ds", "树、森林", "X03")
    content = question["content"].replace(" ", "").replace("\n", "")
    assert "M1、M2和M3" in content
    assert "M,M2和M3" not in content
    assert question["options"]["A"] == "M1"
    assert question["options"]["B"] == "M1 + M2"
    assert question["options"]["C"] == "M3"
    assert question["options"]["D"] == "M2 + M3"
    assert question["answer"]["choice"] == "D"
    assert "M2+M3" in (question["answer"]["explanation"] or "").replace(" ", "")
    patches = load_page_review_patches()
    fields = patches[("ds", "树与二叉树 · 树、森林 · 选择题", "X03")]
    assert fields["options"]["D"] == "M2 + M3"
    assert fields["choice"] == "D"


def test_ds_stack_x12_variable_is_x_not_8():
    question = _q("ds", "栈 · 选择题", "X12")
    content = question["content"]
    assert "变量8" not in content
    assert "变量x的值" in content
    assert "Pop(st, x)" in content


def test_ds_queue_x21_uses_digit_zero():
    question = _q("ds", "队列 · 选择题", "X21")
    content = question["content"]
    assert "A[O" not in content
    assert "A[0]" in content
    assert question["options"]["B"] == "0,n-1"
    assert question["options"]["D"] == "n-1,n-1"
    assert question["answer"]["choice"] == "B"


def test_ds_forest_x19_x20_use_latin_a():
    for qid in ("X19", "X20"):
        content = _q("ds", "树、森林", qid)["content"]
        assert "α" not in content


def test_net_ipv4_a11_2_moved_out_of_choice():
    data = _load("net")
    for chapter in data["chapters"]:
        if "IPv4" in str(chapter.get("name") or "") and "选择" in str(chapter.get("name") or ""):
            assert all(q.get("id") != "X11_2" for q in chapter["questions"])
    question = None
    for chapter in data["chapters"]:
        if "IPv4" in str(chapter.get("name") or "") and "解答" in str(chapter.get("name") or ""):
            for q in chapter["questions"]:
                if q.get("id") == "A11_2":
                    question = q
    assert question is not None
    assert question["type"] == "解答题"
    assert question.get("options") is None
    assert (question.get("answer") or {}).get("choice") is None
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "00:00:5e:00:01:01" in expl
    assert "380B" in expl
    assert question.get("has_image") is True


def test_coa_perf_x20_uses_5e5():
    content = _q("coa", "计算机的性能指标", "X20")["content"]
    assert '5x10"' not in content
    assert "5×10^5" in content


def test_ds_array_x07_has_k_and_aij():
    content = _q("ds", "数组和特殊矩阵", "X07")["content"]
    assert "B[k]" in content
    assert "B[中的" not in content
    assert "áij" not in content


def test_os_deadlock_x40_has_r1_p1():
    content = _q("os", "死锁", "X40")["content"]
    assert "R,,R2" not in content
    assert "P,P2" not in content
    assert "R1,R2和R3" in content
    assert "P1申请R1" in content


def test_net_tcp_x15_power():
    content = _q("net", "TCP", "X15")["content"]
    assert '5x10"' not in content
    assert "5×10^9" in content


def test_os_fat_x28_explicit_link_and_2_16():
    question = _q("os", "目录与文件", "X28")
    assert "显示链接" not in question["content"]
    assert "显式链接" in question["content"]
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "216x2B" not in expl
    assert "2^16×2B" in expl


def test_os_thread_x71_wait_parens():
    question = _q("os", "进程与线程简介", "X71")
    assert question["options"]["D"] == "执行信号量的wait()操作"
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "waitO" not in question["options"]["D"]
    assert "wait)" not in expl
    assert "wait()" in expl


def test_coa_shift_x15_keeps_x0_x1_subscripts():
    question = _q("coa", "运算方法和运算电路", "X15")
    assert "Xo.XX2" not in question["content"]
    assert "x0.x1x2...xn" in question["content"]
    assert question["options"]["A"] == "x0=x1"
    assert question["options"]["B"] == "x0≠x1"
    assert question["options"]["D"] == "x1=1"
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "x0≠x1" in expl


def test_coa_vm_x14_add_xaddr_has_space():
    content = _q("coa", "虚拟存储器", "X14")["content"]
    assert "addxaddr" not in content
    assert "add xaddr,3" in content


def test_net_wlan_x48_uses_microseconds():
    question = _q("net", "局域网", "X48")
    assert "128uS" not in question["content"]
    assert "128μs" in question["content"]
    assert "28μs" in question["content"]
    expl = (question.get("answer") or {}).get("explanation") or ""
    assert "μus" not in expl
    assert "296μs" in expl


def test_coa_cache_x01_option_c_not_double_12mb():
    options = _q("coa", "高速缓冲存储器", "X01")["options"]
    assert options["C"] == "12MB-400KB+400KB"
    assert "12MB-12MB" not in options["C"]


def test_os_memory_x18_multiprogramming():
    content = _q("os", "内存管理概念", "X18")["content"]
    assert "多进程" not in content
    assert "多道程序在内存中" in content


def test_os_cpu_x55_roman_items_split():
    content = _q("os", "CPU调度", "X55")["content"]
    assert "值II." not in content
    assert "I. 更新程序计数器的值" in content
    assert "II. 更新栈基址寄存器的值" in content
    assert "III. 更新页表基地址寄存器的值" in content


def test_ds_algo_x06_multiplies_by_3():
    content = _q("ds", "算法和算法评价", "X06")["content"]
    assert "i=i*2" not in content
    assert "i=i*3" in content


def test_ds_graph_x09_five_vertices():
    question = _q("ds", "图的基本概念", "X09")
    assert "5个顶点" in question["content"]
    assert "6个顶点" not in question["content"]
    assert question["options"] == {"A": "6", "B": "7", "C": "8", "D": "9"}
    assert question["answer"]["choice"] == "B"


def test_net_routing_x04_next_hop_network_ip():
    options = _q("net", "网络层的功能", "X04")["options"]
    assert "MAC" not in options["D"]
    assert "所在网络的IP地址" in options["D"]


def test_net_stopwait_x01_option_d_has_packet():
    options = _q("net", "流量控制与可靠传输", "X01")["options"]
    assert options["D"] == "接收方可以不按序接收分组"


def test_os_runtime_x01_options_not_duplicated():
    options = _q("os", "操作系统的运行环境", "X01")["options"]
    assert options["A"] == "I、II、III、IV"
    assert options["B"] == "I、III"
    assert options["C"] == "I、II、III"
    assert options["D"] == "I"
    assert len(set(options.values())) == 4


def test_os_device_x31_splits_iv():
    content = _q("os", "设备独立性软件", "X31")["content"]
    assert "打印IV." not in content
    assert "IV.缓冲区管理" in content


def test_page_review_manifest_is_valid_and_unique():
    patches = load_page_review_patches()
    # 动态校验：非空且唯一（避免手写总数易碎）
    assert patches
    assert len(patches) == len(set(patches))
    assert all(len(key) == 3 for key in patches)


def test_page_review_manifest_is_applied_by_fix_file(tmp_path):
    (course, chapter, qid), fields = next(iter(load_page_review_patches().items()))
    path = tmp_path / f"questions_{course}.json"
    path.write_text(
        json.dumps(
            {
                "chapters": [
                    {
                        "name": chapter,
                        "questions": [
                            {
                                "id": qid,
                                "type": "选择题",
                                "content": "old",
                                "options": {"A": "a", "B": "b", "C": "old-c", "D": "old-d"},
                                "answer": {"choice": "A", "explanation": "old"},
                            }
                        ],
                        "question_count": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fix_file(path, pdf_images_dir=tmp_path, course_key=course, apply_page_review_patches=True)
    question = json.loads(path.read_text(encoding="utf-8"))["chapters"][0]["questions"][0]
    for key, value in fields.get("options", {}).items():
        assert question["options"][key] == value


def test_page_review_manifest_rejects_duplicate_target(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data" / "quality" / "page_review_patches.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["items"].append(payload["items"][0])
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate page review patch target"):
        load_page_review_patches(path)
