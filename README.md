# 王道 408 精选题题库

基于 27 王道《数据结构》《计算机组成原理》《计算机网络》《操作系统》考研复习指导的精选题题库。

## 项目结构

```
.
├── scripts/                  # Python 构建脚本
│   ├── build_all.py          # 一键构建完整题库
│   ├── parse_questions.py    # OCR 结果解析为结构化题库
│   ├── parse_patterns.py     # 解析用正则与模式集合
│   ├── post_process.py       # 题型拆分（选择/解答）与 id 处理
│   ├── reshape_by_l2.py      # 按 L2 小节重组章节
│   ├── fix_questions.py      # 答案 choice 提取、子问拆分、图片关联
│   ├── merge_courses.py      # 合并四门课程并生成前端懒加载数据
│   ├── auto_recrop_figs.py   # 有图题配图精准重裁 + 题干图区碎片清理（build_all/rebuild_course 在 merge 后自动执行）
│   ├── enhance_audit.py      # 题库质量审计
│   ├── parse_toc.py          # 从 PDF 书签提取目录
│   ├── run_ocr.py            # OCR 流水线
│   └── ...
├── scripts/config.py         # 四门课程的统一配置
├── data/                     # 输入数据
│   ├── ocr/{ds,coa,net,os}/  # OCR 原始输出
│   ├── fig_manual_boxes.json # 有图题人工校准框（含跨页/摘除），auto_recrop_figs 优先采用，重建后依然生效
│   ├── toc/toc_{ds,coa,net,os}.json  # 目录 JSON
│   └── qa/{ds,coa,net,os}_qa_pairs.json  # 题目-答案页边界
├── output/                   # 构建输出
│   ├── questions*.json       # 各科题库 JSON
│   ├── questions_all.json    # 合并后的总题库
│   └── reports/              # 质量报告、补全清单等
├── math-bank/                # 前端题库页面（HTML/CSS/JS）
├── tests/                    # 回归测试
├── assets/pdf_images/{ds,coa,net,os}/  # PDF 切页图片（自行准备）
├── screenshots/              # 本地截图/验证图片（不提交）
└── tmp/                      # 临时/备份文件（不提交）
```

## 构建

需要预先准备好：

1. 四本 PDF 放在 `资料/408/` 目录（`scripts/config.py` 已指向该位置）；若在其他位置可修改 `scripts/config.py` 中的 `_repo_path(...)`
2. PDF 切页图片目录 `assets/pdf_images/ds/`、`assets/pdf_images/coa/`、`assets/pdf_images/net/`、`assets/pdf_images/os/`
3. OCR 结果放在 `data/ocr/ds/`、`data/ocr/coa/` 等（可用 `scripts/run_ocr.py` 生成）
4. 目录 JSON `data/toc/ds.json` 等（可用 `scripts/parse_toc.py` 生成）

然后运行：

```bash
# 发布构建需要本机配置 MOONSHOT_API_KEY；视觉门禁只在本机运行
python scripts/build_all.py
```

`build_all.py` 会在合并前执行全自动章节轮换抽检：每个大章每轮抽 5 题，
并额外检查变更题和历史高风险题。题目区/答案区从原书页图精确裁出，分别交给
Kimi K3、Kimi K2.6 独立读取；答案还必须和 GPU OCR 三方一致。模型一致时才会
生成持久化补丁和回归样例，持续冲突的题目自动写入 `math-bank/quality-hold.json`。
API 或 GPU 故障会阻断构建并保留上一版发布题库。

本地只想生成未核验预览时可显式跳过（该产物不能部署）：

```bash
python scripts/build_all.py --skip-vision-audit
```

需要的本地变量（二选一）：

- Coding Plan：`KIMI_CODE_API_KEY` + 可选 `KIMI_CODE_BASE_URL`（默认
  `https://api.kimi.com/coding/v1`，默认关闭 Thinking、由服务端路由到 K2.6；设置
  `KIMI_CODE_THINKING=on` 才使用 K2.7，绝不调用 K3。也可用
  `KIMI_CODE_KEY_FILE` 指向只含一行 Key 的本地文件。两次盲审默认使用同一低耗模型。
- Open Platform：`MOONSHOT_API_KEY` + 可选 `MOONSHOT_BASE_URL`（默认
  `https://api.moonshot.cn/v1`，使用 `kimi-k3` + `kimi-k2.6`）。

视觉门禁记录在
`math-bank/quality-verification.json`，部署打包只接受 `status=published`。

**单科重抽**（无 PDF 切页 → OCR → 解析 → 合并，适合某一门质量不满意时）：

```bash
# 例：计算机网络
python scripts/rebuild_course.py net
# 已有切页/OCR 时仅重解析
python scripts/rebuild_course.py net --skip-render --skip-ocr
```

辅助脚本：`scripts/render_pdf_pages.py`（PDF→PNG）、`scripts/run_ocr.py`（PNG→OCR JSON）。

构建完成后：

- 题库 JSON：`output/questions.json`、`output/questions_coa.json`、`output/questions_net.json`、`output/questions_os.json`
- 合并题库：`output/questions_all.json`
- 前端数据：`math-bank/data.js`（loader）+ `math-bank/data-*.json`（按课程懒加载）
- 质量报告：`output/reports/quality_report.json`

## 本地预览

推荐使用项目自带的 gzip 静态服务器（可压缩 data-*.json，加载更快）：

```bash
python scripts/serve_bank.py 8080
```

浏览器打开 `http://localhost:8080/`。

或者使用标准库服务器（无压缩）：

```bash
cd math-bank
python -m http.server 8080
```

## 测试

```bash
python -m pytest tests/
```

## 每章抽检

从平台实际读取的四科发布 JSON 中，对每个大章节按题目顺序分层抽样。默认每章
抽 5 题；同一个 `--round` 会得到完全相同的批次，便于复核和追踪问题。

```bash
python scripts/chapter_sample_audit.py --per-chapter 5 --round 2026-08-baseline
```

输出 `output/reports/chapter_sample_audit.json` 和
`output/reports/chapter_sample_audit.html`。HTML 将题库内容和原书页图左右对照，
支持标记“正常/有问题”、浏览器断点保存和导出问题 JSON。

上述 HTML 是人工查看的备用报告；正式构建使用 `scripts/vision_quality_gate.py`
自动抽检，不要求人工确认。

## 说明

本仓库仅包含解析与前端代码，以及处理后的题库 JSON。**不包含原始 PDF、OCR 原始输出和 PDF 切页图片**，请自行准备。
