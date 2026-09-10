# bank-408 OCR / 原书对齐修复记录

每次题目文本被确认 OCR 有误并修复后，在本文件追加一节；同时按 monorepo `AGENTS.md` **默认上云**（不再等主人单独说「上云」）。

## 标准流程

1. 对照 `assets/pdf_images/<course>/page_N.png` 确认原书正文。
2. 在 `data/quality/page_review_patches.json` 写入持久补丁（`course` / `chapter` / `qid` / `fields`）。
3. 重应用并合并发布数据：

   ```powershell
   # 在 apps/bank-408
   ..\platform-v2\backend\.venv\Scripts\python.exe scripts\fix_questions.py output\questions.json
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
| 上云 | 见下方部署条目 |

**正确题干**

```
设森林F中有3棵树，第1、2、3棵树的结点数分别为M1、M2和M3，与森林F对应的
二叉树根结点的右子树上的结点数是（）。
A. M1    B. M1 + M2    C. M3    D. M2 + M3
```
