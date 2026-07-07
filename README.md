# 王道 408 精选题题库

基于 27 王道《数据结构》《计算机组成原理》《计算机网络》《操作系统》考研复习指导的精选题题库。

## 项目结构

- `parse_questions.py` — OCR 结果解析为结构化题库
- `post_process.py` / `reshape_by_l2.py` — 题型拆分与章节重组
- `fix_questions.py` — 答案 choice 提取、子问拆分、图片关联
- `merge_courses.py` — 合并四门课程并生成前端懒加载数据
- `build_all.py` — 一键构建完整题库
- `enhance_audit.py` — 题库质量审计
- `math-bank/` — 前端题库页面（HTML/CSS/JS）
- `scripts_output/` — QA 对、质量报告等输出

## 构建

需要预先准备好 OCR 结果（`ocr*/`）和 PDF 切页图片（`pdf_images*/`），然后运行：

```bash
python build_all.py
```

构建完成后：

- 题库 JSON：`questions.json`、`questions_coa.json`、`questions_net.json`、`questions_os.json`
- 前端数据：`math-bank/data.js`（loader）+ `math-bank/data-*.js`（按课程懒加载）
- 质量报告：`quality_report.json`

## 本地预览

```bash
cd math-bank
python -m http.server 8080
```

浏览器打开 `http://localhost:8080/`。

## 说明

本仓库仅包含解析与前端代码，以及处理后的题库 JSON。**不包含原始 PDF、OCR 原始输出和 PDF 切页图片**，请自行准备。
