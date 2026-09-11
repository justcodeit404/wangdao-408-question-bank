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


def test_ds_tree_x06_count_is_2_n_minus_1():
    options = _q("ds", "二叉树的概念", "X06")["options"]
    assert options["D"] == "2^{n-1}"
    assert "2^n-1" not in options["D"]


def test_net_ipv4_x37_mask_196():
    options = _q("net", "IPv4", "X37")["options"]
    assert options["D"] == "255.255.255.196"


def test_os_deadlock_x42_option_b_is_i_ii_iv():
    question = _q("os", "死锁", "X42")
    assert question["options"]["B"] == "仅I、II、IV"
    assert question["options"]["B"] != question["options"]["D"]
    assert "III.．" not in question["content"]
    assert question["answer"]["choice"] == "B"


def test_ds_sort_x03_log2_not_logz():
    options = _q("ds", "各种内部排序算法的比较及应用", "X03")["options"]
    assert "logzn" not in options["C"]
    assert "log2n" in options["C"]


def test_ds_dag_x39_outer_parens():
    content = _q("ds", "图的应用", "X39")["content"]
    assert "((x+y)(x+y)/x)" in content.replace(" ", "")


def test_coa_chip_x09_is_8bit():
    content = _q("coa", "主存储器与CPU的连接", "X09")["content"]
    assert "32K×8位" in content
    assert "32Kx16" not in content


def test_ds_huffman_x05_216_nodes():
    content = _q("ds", "树与二叉树的应用", "X05")["content"]
    assert "216个结点" in content


def test_coa_cache_x17_storage_hierarchy():
    content = _q("coa", "高速缓冲存储器", "X17")["content"]
    assert "三级存储层次" in content
    assert "访存时直接根据" in content


def test_ds_tree_x29_option_d_is_4():
    options = _q("ds", "二叉树的概念", "X29")["options"]
    assert options["D"] == "4"


def test_ds_tree_x27_roman_ii_present():
    question = _q("ds", "树形查找", "X27")
    assert "II.若v是T1的叶结点" in question["content"]
    assert "III.若v不是T1的叶结点" in question["content"]
    assert question["content"].count("III.") == 1
    assert question["answer"]["choice"] == "C"


def test_net_ipv6_x07_roman_ii():
    question = _q("net", "IPv6", "X07")
    assert "II.IPv4首部和IPv6基本首部的长度均可变" in question["content"]
    assert question["content"].count("III.") == 1


def test_os_dir_x61_roman_iii_not_il():
    question = _q("os", "目录与文件", "X61")
    assert "III.fd1和fd2" in question["content"]
    assert "Il." not in question["content"]
    assert "fl的硬链接" not in question["content"]


def test_os_sched_x47_mu_and_p1():
    question = _q("os", "CPU调度", "X47")
    assert "1μs" in question["content"]
    assert "P1、P2和P3" in question["content"]
    assert "μus" not in question["content"]
    assert "1uS" not in question["content"]


def test_net_ipv4_x26_no_next_question_bleed():
    question = _q("net", "IPv4", "X26")
    assert "27. CIDR" not in question["content"]
    assert "200.15.10.6/29" in question["content"]


def test_net_phy_x25_no_umum():
    question = _q("net", "通信基础", "X25")
    assert "umum" not in question["content"]
    assert "差分曼彻斯特" in question["content"]


def test_net_ipv4_x63_mac_uses_digit_one():
    question = _q("net", "IPv4", "X63")
    blob = question["content"] + "".join(question["options"].values())
    assert "HI" not in question["content"]
    assert "主机H1" in question["content"].replace("\n", "")
    assert "00-al-" not in blob
    assert question["options"]["A"].startswith("00-a1-")
    assert "H H2" not in question["content"]


def test_ds_shortest_path_x07_stem_not_option_leak():
    question = _q("ds", "图的应用", "X07")
    assert "A." not in question["content"]
    assert "Dijkstra" not in question["content"]
    assert question["options"]["D"].startswith("Dijkstra")


def test_ds_dfs_x08_sequences_separated():
    question = _q("ds", "图的遍历", "X08")
    one_line = question["content"].replace("\n", "")
    assert "acfdeb3." not in one_line
    assert "2. acfdeb" in one_line
    assert "3. aedfcb" in one_line
    assert "4. aefdbc" in one_line


def test_os_fs_x02_options_match_book():
    question = _q("os", "文件系统 ·", "X02")
    assert question["options"]["A"] == "I、II和III"
    assert question["options"]["B"] == "II、III和IV"
    assert "仅I、II" not in question["options"]["A"]


def test_coa_x13_complement_notation():
    question = _q("coa", "数制与编码", "X13")
    compact = question["content"].replace(" ", "")
    assert "[-x*]补=[-x]补" in compact


def test_coa_io_x06_slash_in_io_device():
    question = _q("coa", "I/O接口", "X06")
    assert "I/O设备" in question["options"]["C"]
    assert "IO设备" not in question["options"]["C"]


def test_coa_mem_x11_superscripts():
    question = _q("coa", "存储器概述", "X11")
    assert "°" not in "".join(question["options"].values())
    assert question["options"]["A"] == "4×10^6B/s"
    assert question["options"]["C"] == "8×10^6B/s"
    assert question["options"]["D"] == "8×2^{20}B/s"


def test_os_sync_x50_a_equals_one():
    question = _q("os", "同步与互斥", "X50")
    assert question["options"]["A"] == "a=1与a=2"
    assert "a=l" not in question["options"]["A"]


def test_ds_shortest_x09_keeps_v1_v7():
    question = _q("ds", "图的应用", "X09")
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "源点v1" in compact
    assert "顶点v7" in compact
    assert "(v5,v7)7" in compact
    assert question["options"]["A"].startswith("v1")


def test_ds_stack_x05_function_brace():
    question = _q("ds", "栈和队列的应用", "X05")
    assert "return ((x>0)? x*f(x-1):2);\n}" in question["content"]
    assert question["content"].index("}") < question["content"].index("int i")


def test_ds_forest_x07_t1_subscript():
    question = _q("ds", "树、森林", "X07")
    assert "子树T1的根" in question["options"]["B"]
    assert "子树T1的根" in question["options"]["C"]
    assert "将子树T的根" not in question["options"]["B"]


def test_ds_aoe_x25_roman_iii_not_dup_ii():
    question = _q("ds", "图的应用", "X25")
    lines = [ln.strip() for ln in question["content"].splitlines()]
    assert any(ln.startswith("III.") or ln.startswith("III．") for ln in lines)
    assert not any(
        (ln.startswith("II.") or ln.startswith("II．"))
        and "缩短关键路径上任意一个关键活动的持续时间可缩短关键路径长度" in ln
        and not ln.startswith("III")
        for ln in lines
    )


def test_os_mem_x71_p1_f1_not_pl_fl():
    question = _q("os", "内存管理概念", "X71")
    blob = question["content"] + "".join(question["options"].values())
    assert "pl" not in blob
    assert "fl" not in blob
    assert "p1和p2" in question["content"].replace("\n", "")
    assert "f1和f2" in question["content"].replace("\n", "")
    assert question["options"]["C"].startswith("p1")


def test_os_io_x10_t1_and_option_c():
    question = _q("os", "设备独立性软件", "X10")
    assert "时间为T1" in question["content"].replace("\n", "").replace(" ", "")
    assert question["options"]["C"] == "max(T1,T3)+T2"
    assert question["options"]["C"] != "T1"


def test_os_sched_x18_j1_t1_subscripts():
    question = _q("os", "CPU调度", "X18")
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "作业J1" in compact
    assert "时间分别是T1" in compact
    assert question["options"]["B"] == "(3T1+2T2+T3)/3"


def test_coa_micro_x15_option_a_is_i_ii():
    question = _q("coa", "控制器的功能和工作原理", "X15")
    assert question["options"]["A"] == "I、II"
    assert question["options"]["A"] != "III"


def test_os_deadlock_x32_r1_p1():
    question = _q("os", "死锁", "X32")
    compact = question["content"].replace(" ", "").replace("\n", "")
    assert "资源：R1" in compact
    assert "进程P1和P2" in compact
    assert "释放R1，则" in compact
    assert "R1资源不足" in question["options"]["B"]


def test_coa_alu_x20_complement_brackets():
    question = _q("coa", "运算方法和运算电路", "X20")
    compact = question["content"].replace(" ", "")
    assert "[x]补=44H" in compact
    assert "[y]补=DCH" in compact


def test_net_tcp_x32_t_not_one():
    question = _q("net", "TCP", "X32")
    assert "在t时刻" in question["content"].replace("\n", "").replace(" ", "")
    assert "从t时刻起" in question["content"].replace("\n", "").replace(" ", "")
    assert "在1时刻" not in question["content"]


def test_net_tcp_x18_two_blank_options():
    question = _q("net", "TCP", "X18")
    assert "C. SYN=1，序号=Y" in question["content"]
    assert question["answer"]["choice"] == "AC"


def test_coa_pipeline_x15_option_a_has_iii():
    question = _q("coa", "指令流水线", "X15")
    assert question["options"]["A"] == "I、II、III"


def test_net_arq_x17_sr_window_less_than():
    question = _q("net", "流量控制与可靠传输机制", "X17")
    assert "小于接收窗口" in question["content"]
    assert "等于接收窗口" not in question["content"]


def test_ds_matrix_x03_option_a_matches_book():
    question = _q("ds", "数组和特殊矩阵", "X03")
    assert question["options"]["A"] == "(i+3)i/2"
    assert "+j" not in question["options"]["A"]


def test_net_ipv4_x69_internet_not_intermet():
    question = _q("net", "IPv4", "X69")
    assert "Internet" in question["content"]
    assert "Intermet" not in question["content"]


def test_ds_symmetric_matrix_x02_times_not_x():
    question = _q("ds", "数组和特殊矩阵", "X02")
    assert question["options"]["B"] == "n×n/2"
    assert "nxn" not in question["options"]["B"]
    assert question["options"]["C"] == "n(n+1)/2"
    assert question["options"]["D"] == "n(n-1)/2"


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
