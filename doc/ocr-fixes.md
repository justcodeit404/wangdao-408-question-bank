# bank-408 OCR / 原书对齐修复记录

每次题目文本被确认 OCR 有误并修复后，在本文件追加一节；同时按 monorepo `AGENTS.md` **默认上云**（不再等主人单独说「上云」）。

## 标准流程

1. 对照 `assets/pdf_images/<course>/page_N.png` 确认原书正文。
2. 在 `data/quality/page_review_patches.json` 写入持久补丁（`course` / `chapter` / `qid` / `fields`）。
3. 重应用并合并发布数据：

   ```powershell
   # 在 apps/bank-408
   ..\platform-v2\backend\.venv\Scripts\python.exe scripts\fix_questions.py
   ..\platform-v2\backend\.venv\Scripts\python.exe scripts\merge_courses.py output\questions_all.json
   ..\platform-v2\backend\.venv\Scripts\python.exe -m pytest tests\test_page_review_patches.py tests\test_notes_katex.py -q
   ```

4. 若改了 `math-bank` 题面/壳层：三处缓存戳同步 `+1`（`index.html` 全部 `?v=N` + `__BANK_DATA_VER__` + `sw.js` 的 `wd408-ui-vN`）。
5. 在本文件追加修复条目；`git add` 相关文件并 commit（子模块 + monorepo 指针）。
6. 按 `docs/server.md` / `apps/platform-v2/deploy/README.md`：`pack-for-upload.ps1` → scp → `apply-v2-deploy.sh`。收尾写明「云端已部署」。

---

## 2026-09-10 · ds 树、森林 · X03 · M 下标丢失

| 项 | 值 |
|----|-----|
| 课程 / 章节 | ds · 树与二叉树 · 树、森林 · 选择题 |
| 题号 | X03（原书第 177 页 · 03） |
| 现象 | 题干「分别为 M,M2和M3」；选项 A=`M`、B=`M + M2`、D=`M2 + M`。解析已是 `M2+M3`，与题干/选项不一致。 |
| 原书 | `assets/pdf_images/ds/page_177.png`：`M₁、M₂ 和 M₃`；A=`M₁` B=`M₁+M₂` C=`M₃` D=`M₂+M₃`；答案 D |
| 修复 | `page_review_patches.json` 增补 X03：content/options/choice/explanation 对齐原书；重建 `output/questions.json` → `math-bank/data-ds.json`；缓存戳 61→62；回归测试 `test_ds_forest_x03_keeps_m_subscripts` |
| 上云 | 2026-09-10 已部署 release `20260910T144824Z-bb2ca1906f56` |

**正确题干**

```
设森林F中有3棵树，第1、2、3棵树的结点数分别为M1、M2和M3，与森林F对应的
二叉树根结点的右子树上的结点数是（）。
A. M1    B. M1 + M2    C. M3    D. M2 + M3
```

---

## 2026-09-10 · 全库扫描 · 选择题 OCR 二次修复

全库模式扫描后，对照原书页图修复下列**选择题**（解答题大量乱码已在 hold，另案处理）：

| 课程 | 题 | 错误 → 正确 |
|------|----|-------------|
| ds 栈 X12 | 变量8 → 变量x；Pop(st，x) → Pop(st, x) |
| ds 栈 X17/X20/X21 | `",` 省略号 → `…`；`P的值` → `P1的值` |
| ds 队列 X21 | `A[O]`/`O,n-1`/`n-l` → `A[0]`/`0,n-1`/`n-1` |
| ds 链式 X06 | `在α和p之间` → `在q和p之间` |
| ds 链式 X17 | `插入指针α` → `插入指针q` |
| ds 二叉树 X08 | `1,2,",n` → `1,2,…,n` |
| ds 森林 X19/X20 | 遍历序列 `α` → 拉丁 `a` |
| ds 树形查找 X15 | `高度为〇`、`1,2,3,"` → `高度为0`、`1,2,3,…` |
| coa 性能 X20 | `5x10"` → `5×10^5` |

- 缓存戳 62→63
- 回归：`test_ds_stack_x12_variable_is_x_not_8` 等
- 上云：2026-09-10 已部署 release `20260910T150251Z-35c2338ca74f`

**仍待处理（解答题 hold，模式扫描命中）**：`",` 省略号、α/a、`1ist`、代码乱码等，多见于线性表/图/排序解答题；需按原书页逐题重做 vision hold 修复，不在本批选择题补丁范围内。

---

## 2026-09-10 · 选择题残留二次扫描

深扫 2440 道选择题题干/选项，再修：

| 题 | 错误 → 正确 |
|----|-------------|
| ds 链式 X05 | 选项 D `i=0.",n-1` → `i=0,…,n-1` |
| ds 数组 X07 | `B[中的`→`B[k]中的`；`áij`→`aij` |
| ds 链式 X36 | 选项 B/D `P/α` → `p/q` |
| ds 树形查找 X28 | `平衡因子为〇` → `0` |
| os 死锁 X36 | `R,,R2,R3`、`Po` → `R1,R2,R3`、`P0` |
| os 死锁 X40 | `R,,R2`、`P,P2` → `R1,R2`、`P1,P2` |
| os 内存 X55 | `0,1,2,, 255` → `0,1,2,…,255` |
| net TCP X15 | `5x10"` → `5×10^9` |
| coa 浮点 X30 | `OxC008` → `0xC008` |

缓存戳 63→64。选择题题干/选项高置信 OCR 病征已清零；剩余命中多为中文全角逗号（非错误）或合法 α（装填因子等）。
上云：2026-09-10 已部署 release `20260910T151545Z-0fbbc714f541`。

---

## 2026-09-10 · net IPv4 · X11_2 → A11_2 · 综合题误分类

ledger 里唯一 hold 的「选择题」实为综合题 11（主机 A 收帧 + 报文十六进制图 + 三小问）。

| 项 | 内容 |
|----|------|
| 问题 | 被塞进 `IPv4 · 选择题`，选项=乱码报文+三小问，解析误串 X11 片偏移，choice=C |
| 原书 | 题页 OCR net/page_166（印刷页 161）综合应用题 11；答案 OCR page_182 |
| 答案 | 网关 MAC `00:00:5e:00:01:01`；数据量 `380B`；DF=1 丢弃并 ICMP 报告 |
| 修复 | `CURATED_APPLICATION_PATCHES`：移回 `IPv4 · 解答题` 为 `A11_2`；重建裁图 `page_166_X11_2.png` |
| 缓存 | 64→65 |
| 上云 | 2026-09-10 已部署 release `20260910T153133Z-5811312cd0f8` |

---

## 2026-09-10 · 随机抽检 7 题

seed=20260910，各科 certified 选择题/解答题各抽 1（net 缺 1 道解答抽样后共 7）。

| 题 | 结果 |
|----|------|
| ds 队列 X15 | 通过 |
| ds 外排 A02 | 通过 |
| coa 运算 X13 | **失败**：C0/C1 下标丢失、罗马数字乱码、解析损坏 → 已修 |
| net 介质访问 X19 | 通过（空解析与原书一致，原书仅有 “19.A”） |
| net 多播 A01 | 通过 |
| os 内存 X36 | 通过 |
| os 引导 A08 | 通过 |

coa X13 修复：题干恢复 C0/C1 与 I–VI；解析改为 C0⊕C1。缓存 65→66。

---

## 2026-09-10 · 随机抽检第二批（13 题，seed=20260911）

| 题 | 结果 |
|----|------|
| ds 排序 X21 | 通过 |
| **ds 图 X11** | **失败**：II/III 罗马数字乱码 → 已修 |
| **ds 外排 A01** | 解析天花板符号乱码（保持 hold，不本批重写） |
| ds 外排 A02 | 通过 |
| **coa 运算 X27** | **失败**：`[杯` → `[y]补` → 已修 |
| coa 主存 X21 | 通过 |
| net FTP X05 / UDP X04 / 多播 A01 | 通过 |
| os 文件保护 X46 | 通过 |
| **os 同步 X43** | **失败**：II 被 OCR 成 III → 已修 |
| **os 磁盘 A02** | `A,B,"，I` → `A,B,…,I` → 已修 |
| os 磁盘 A04 | 通过 |

两批合计：7+13=20 抽，修复 5 题（coa X13/X27、ds X11、os X43/A02），1 题（ds A01）仍待 hold 重做。缓存 66→67。

---

## 2026-09-10 · 选择题定向全库扫描（不碰解答题）

对 2440 道选择题按病征全扫（罗马数字 II/III 乱、补码标记、0/O、省略号等），确认并修复：

**题干/选项（20 题）**  
net X20/X21；coa X19/X37；ds 队列 X22；  
os：X07/X09/X10/X18/X31（运行环境等）、X41/X51/X55/X56/X73（进程）、X61/X46/X48（虚存）、X02/X06/X15（文件）、X45（设备）

主要病征：
- 列表项 `II` 被 OCR 成 `III`/`IL`/重复
- 选项里 `1、II`、`III、III`、`I、I`
- `[x补`/`[补` 丢 `]补`
- `A［0M-1]` → `A[0..M-1]`

缓存 67→68。解答题未动（按你的要求只做选择题）。

