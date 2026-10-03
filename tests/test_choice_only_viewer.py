"""bank-408 Viewer choice-only 视图：空解答章节/统计/选中回退。

直接跑 math-bank/choice-only.js（与页面同源），不依赖浏览器 DOM。
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHOICE_ONLY_JS = ROOT / "math-bank" / "choice-only.js"
APP_JS = ROOT / "math-bank" / "app.js"
INDEX_HTML = ROOT / "math-bank" / "index.html"
SW_JS = ROOT / "math-bank" / "sw.js"
DATA_FILES = {
    "数据结构": ROOT / "math-bank" / "data-ds.json",
    "计算机组成原理": ROOT / "math-bank" / "data-coa.json",
    "操作系统": ROOT / "math-bank" / "data-os.json",
    "计算机网络": ROOT / "math-bank" / "data-net.json",
}


def _node_eval(expr: str, *, data: dict | None = None, data_path: Path | None = None):
    """Load choice-only.js and eval expr; DATA from path or inline small dict.

    大题库勿塞进 -e（Windows 命令行长度上限），用 data_path 读文件。
    """
    import tempfile

    tmp_script: Path | None = None
    tmp_data: Path | None = None
    try:
        if data_path is not None:
            data_load = f"const DATA = JSON.parse(require('fs').readFileSync({json.dumps(str(data_path))}, 'utf8'));"
        elif data is not None:
            tmp_data = Path(tempfile.gettempdir()) / f"bank408-choice-only-{id(data)}.json"
            tmp_data.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            data_load = f"const DATA = JSON.parse(require('fs').readFileSync({json.dumps(str(tmp_data))}, 'utf8'));"
        else:
            data_load = "const DATA = null;"

        script = textwrap.dedent(
            f"""
            const api = require({json.dumps(str(CHOICE_ONLY_JS))});
            {data_load}
            const result = (function () {{
              {expr}
            }})();
            process.stdout.write(JSON.stringify(result));
            """
        )
        tmp_script = Path(tempfile.gettempdir()) / "bank408-choice-only-runner.js"
        tmp_script.write_text(script, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(tmp_script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"node failed ({proc.returncode}):\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
            )
        return json.loads(proc.stdout or "null")
    finally:
        if tmp_data and tmp_data.is_file():
            try:
                tmp_data.unlink()
            except OSError:
                pass


def _sample_course(
    *,
    choice_n: int = 30,
    essay_n: int = 0,
    empty_essay_chapter: bool = True,
    orphan_parent: bool = True,
) -> dict:
    """构造：选择题 + 空解答章节 + 无有效子节点的父目录。"""
    chapters = [
        {
            "name": "第1章 · 绪论 · 选择题",
            "course": "数据结构",
            "l1_name": "第1章 绪论",
            "l2_name": "1.1 基本概念",
            "section_type": "选择题",
            "question_count": choice_n,
            "questions": [
                {"id": f"C{i}", "type": "选择题", "content": f"choice {i}"}
                for i in range(1, choice_n + 1)
            ],
        },
    ]
    if empty_essay_chapter or essay_n:
        chapters.append(
            {
                "name": "第1章 · 绪论 · 解答题",
                "course": "数据结构",
                "l1_name": "第1章 绪论",
                "l2_name": "1.1 基本概念",
                "section_type": "解答题",
                "question_count": essay_n,
                "questions": [
                    {"id": f"E{i}", "type": "解答题", "content": f"essay {i}"}
                    for i in range(1, essay_n + 1)
                ],
            }
        )
    if orphan_parent:
        # 仅含空解答 → 过滤后父目录应消失
        chapters.append(
            {
                "name": "第9章 · 幽灵 · 解答题",
                "course": "数据结构",
                "l1_name": "第9章 幽灵章",
                "l2_name": "9.1 无选择",
                "section_type": "解答题",
                "question_count": 0,
                "questions": [],
            }
        )
    return {
        "courses": [
            {
                "name": "数据结构",
                "short": "数据结构",
                "question_count": choice_n + essay_n,
            }
        ],
        "chapters": chapters,
        "total_questions": choice_n + essay_n,
    }


def test_choice_only_js_exists():
    assert CHOICE_ONLY_JS.is_file()
    assert "filterCourseDataToChoices" in CHOICE_ONLY_JS.read_text(encoding="utf-8")


def test_filter_drops_empty_essay_and_recounts():
    data = _sample_course(choice_n=30, essay_n=0, empty_essay_chapter=True)
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        return {
          total: filtered.total_questions,
          chapter_count: filtered.chapters.length,
          section_types: filtered.chapters.map(c => c.section_type),
          course_count: filtered.courses[0].question_count,
          names: filtered.chapters.map(c => c.name),
        };
        """,
        data=data,
    )
    assert out["total"] == 30
    assert out["course_count"] == 30
    assert out["chapter_count"] == 1
    assert out["section_types"] == ["选择题"]
    assert all("解答" not in n for n in out["names"])


def test_stats_only_show_choice_when_essay_zero():
    data = _sample_course(choice_n=30, essay_n=0)
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        const types = {};
        filtered.chapters.forEach(ch => ch.questions.forEach(q => {
          types[q.type] = (types[q.type] || 0) + 1;
        }));
        const items = api.buildTypeStatItems(types);
        const labels = items.map(i => i.label);
        const actions = items.map(i => i.action);
        return { types, items, labels, actions, htmlLike: items.map(i => i.label + i.value).join('|') };
        """,
        data=data,
    )
    assert out["types"] == {"选择题": 30}
    assert out["labels"] == ["选择"]
    assert "解答" not in out["labels"]
    assert "解答0" not in out["htmlLike"]
    assert out["items"][0]["value"] == 30


def test_empty_essay_chapter_not_in_tree():
    data = _sample_course(choice_n=5, essay_n=0, empty_essay_chapter=True, orphan_parent=True)
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        const tree = api.buildChapterTreeFromChapters(filtered.chapters, true);
        const sectionTypes = [];
        const l1Names = tree.map(n => n.name);
        tree.forEach(l1 => l1.children.forEach(l2 => l2.sections.forEach(s => {
          sectionTypes.push(s.section_type);
        })));
        return { l1Names, sectionTypes, tree };
        """,
        data=data,
    )
    assert "解答题" not in out["sectionTypes"]
    assert "第9章 幽灵章" not in out["l1Names"]
    assert out["l1Names"] == ["第1章 绪论"]


def test_parent_without_valid_children_hidden():
    data = {
        "courses": [{"name": "X", "question_count": 0}],
        "chapters": [
            {
                "name": "only-essay",
                "course": "X",
                "l1_name": "L1-empty-parent",
                "l2_name": "L2-empty",
                "section_type": "解答题",
                "question_count": 2,
                "questions": [
                    {"id": "1", "type": "解答题"},
                    {"id": "2", "type": "解答题"},
                ],
            }
        ],
        "total_questions": 2,
    }
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        const tree = api.buildChapterTreeFromChapters(filtered.chapters, true);
        return { chapters: filtered.chapters.length, total: filtered.total_questions, treeLen: tree.length };
        """,
        data=data,
    )
    assert out["chapters"] == 0
    assert out["total"] == 0
    assert out["treeLen"] == 0


def test_stale_essay_selection_falls_back():
    data = _sample_course(choice_n=10, essay_n=0, empty_essay_chapter=True)
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        const stale = '第1章 绪论|1.1 基本概念|解答题';
        const r1 = api.sanitizeSelectedChapter(stale, filtered.chapters, true);
        const okKey = '第1章 绪论|1.1 基本概念|选择题';
        const r2 = api.sanitizeSelectedChapter(okKey, filtered.chapters, true);
        const t1 = api.sanitizeTypeFilter('解答题', { '选择题': 10 });
        const t2 = api.sanitizeTypeFilter('选择题', { '选择题': 10 });
        return { r1, r2, t1, t2 };
        """,
        data=data,
    )
    assert out["r1"]["cleared"] is True
    assert out["r1"]["selectedChapter"] == ""
    assert out["r2"]["cleared"] is False
    assert out["r2"]["selectedChapter"].endswith("选择题")
    assert out["t1"]["cleared"] is True
    assert out["t2"]["cleared"] is False


@pytest.mark.parametrize("course_name,path", list(DATA_FILES.items()))
def test_real_course_data_choice_only(course_name, path: Path):
    if not path.is_file():
        pytest.skip(f"missing {path.name}")
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        const tree = api.buildChapterTreeFromChapters(filtered.chapters, true);
        const types = {};
        let qn = 0;
        filtered.chapters.forEach(ch => {
          (ch.questions || []).forEach(q => {
            qn++;
            types[q.type] = (types[q.type] || 0) + 1;
            if (!api.isChoiceQuestionType(q.type)) throw new Error('non-choice leaked: ' + q.type);
          });
        });
        const labels = api.typeStatLabels(types);
        const sectionTypes = [];
        tree.forEach(l1 => l1.children.forEach(l2 => l2.sections.forEach(s => {
          sectionTypes.push(s.section_type || '');
          if ((s.question_count || 0) <= 0) throw new Error('zero section in tree');
          if (String(s.section_type || '').includes('解答')) throw new Error('essay section in tree');
        })));
        // 无子节点父目录
        tree.forEach(l1 => {
          if (!l1.children || !l1.children.length) throw new Error('empty l1');
          l1.children.forEach(l2 => {
            if (!l2.sections || !l2.sections.length) throw new Error('empty l2');
          });
        });
        return {
          course: DATA.courses && DATA.courses[0] && DATA.courses[0].name,
          total: filtered.total_questions,
          qn,
          types,
          labels,
          sectionTypes: Array.from(new Set(sectionTypes)),
          chapter_n: filtered.chapters.length,
          raw_chapter_n: (DATA.chapters || []).length,
        };
        """,
        data_path=path,
    )
    assert out["qn"] == out["total"]
    assert out["total"] > 0, f"{course_name} should keep some choices"
    assert out["chapter_n"] <= out["raw_chapter_n"]
    assert "解答" not in "".join(out["labels"])
    assert "解答题" not in out["sectionTypes"]
    # 过滤后题数应等于选择题数
    choice_types = set(out["types"])
    assert all("解答" not in t for t in choice_types), (
        f"{course_name} still has essay types: {choice_types}"
    )


def test_app_js_no_hardcoded_essay_stat():
    text = APP_JS.read_text(encoding="utf-8")
    # 旧硬编码统计项必须移除
    assert "{label: '解答', value: types['解答题'] || 0, action: '解答题'}" not in text
    assert "buildTypeStatItems" in text
    assert "sanitizeChoiceOnlySelection" in text
    assert "ChoiceOnlyView" in text
    # 两级树：L2 leaf 可点选；render 中不应创建 tree-l3 按钮
    assert "tree-l2 leaf" in text
    assert (
        "makeToggle(" in text
        and "tree-l3"
        not in text.split("function renderChapters")[1].split("function computeChapterMastery")[0]
    )
    assert "selectChapter(filterKey, l2Btn)" in text


def test_choice_detail_binds_reveal_answer():
    """选择题详情也要绑「显示答案」，不能只靠点选项才揭晓。"""
    text = APP_JS.read_text(encoding="utf-8")
    fn = text.split("function bindDetailInteractions")[1].split("function renderModalContent")[0]
    assert "bindRevealAnswer(container)" in fn
    ordered, _, rest = fn.partition("if (q.type === '选择题' && isOrderedChoice(q))")
    assert "bindRevealAnswer(container)" in ordered
    assert "bindRevealAnswer(container)" not in rest.split("if (q.type === '选择题')")[-1]


def test_ds_x22_ternary_tree_explanation_not_ocr_garbage():
    path = DATA_FILES["数据结构"]
    if not path.is_file():
        pytest.skip(f"missing {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    hits = [
        q
        for ch in data.get("chapters") or []
        for q in ch.get("questions") or []
        if q.get("id") == "X22" and "三叉树" in (q.get("content") or "")
    ]
    assert hits, "expected 二叉树的概念 X22 三叉树高度"
    expl = (hits[0].get("answer") or {}).get("explanation") or ""
    assert r"3^{i-1}" in expl
    assert r"\lceil\log_3 101\rceil" in expl
    assert r"\dfrac{3^h-1}{2}" in expl
    assert "3°" not in expl
    assert "log3101" not in expl.replace("log_3 101", "")


def test_flagged_choice_explanations_use_latex_not_ocr_junk():
    cases = [
        ("数据结构", "X15", 139, r"$2^6-1=63$", "2°-1"),
        ("数据结构", "X24", 139, r"$n=2^0+2^1+\cdots+2^{h-1}=2^h-1$", "2°+2'"),
        ("数据结构", "X05", 132, r"$1+4+4^2+\cdots+4^{h-1}$", "4²+…"),
        # coa 三例已按现行约定去 LaTeX 壳（2^{n} 纯文本），58-63 轮修复
        ("计算机组成原理", "X07", 32, "2^{8}=256", "2°=256"),
        ("计算机网络", "X18", 106, "2^i-1", "2'-1"),
        ("计算机网络", "X27", 43, "V=2^6=64", "2°=64"),
        ("计算机组成原理", "X09", 18, "500×10^{6}÷(2.5×10^{6})=200", "10°"),
        ("计算机组成原理", "X20", 20, "5×10^{5}×1.2=6×10^{5}", "10°"),
    ]
    for course_name, qid, page, needle, junk in cases:
        path = DATA_FILES[course_name]
        data = json.loads(path.read_text(encoding="utf-8"))
        hits = [
            q
            for ch in data.get("chapters") or []
            for q in ch.get("questions") or []
            if q.get("id") == qid and q.get("page") == page
        ]
        assert hits, f"missing {course_name} {qid} p{page}"
        expl = (hits[0].get("answer") or {}).get("explanation") or ""
        assert needle in expl, f"{course_name} {qid}: missing {needle}"
        assert junk not in expl, f"{course_name} {qid}: still has {junk}"


def test_index_html_version_and_assets():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "choice-only.js?v=" in html
    assert "app.js?v=" in html
    assert "data.js?v=" in html
    # 版本号一致
    import re

    vers = re.findall(r"\?v=(\d+)", html)
    assert vers, "expected cache-bust versions"
    assert len(set(vers)) == 1, f"asset versions diverged: {vers}"
    assert int(vers[0]) >= 38
    assert "显示答案（解答题）" not in html
    assert "解答题 0" not in html


def test_viewer_release_version_is_consistent_across_shell_sw_and_registration():
    """HTML、SW 预缓存和注册脚本必须指向同一发布版本。"""
    import re

    html = INDEX_HTML.read_text(encoding="utf-8")
    app = APP_JS.read_text(encoding="utf-8")
    sw = SW_JS.read_text(encoding="utf-8")
    html_versions = re.findall(r"\?v=(\d+)", html)
    assert html_versions and len(set(html_versions)) == 1
    version = html_versions[0]
    assert f"__BANK_DATA_VER__='{version}'" in html
    assert f"register('./sw.js?v={version}')" in app
    assert f"wd408-ui-v{version}" in sw
    for asset in ("styles.css", "app.js", "data.js"):
        assert f"./{asset}?v={version}" in sw
    assert "function bankAssetQuery" in app
    assert "function resolveImageSrc" in app
    src = app[app.index("function resolveImageSrc") : app.index("function imageHtml")]
    assert "bankAssetQuery()" in src


def test_filter_preserves_question_ids():
    """不改题目 ID，进度 key 仍可用。"""
    data = _sample_course(choice_n=3, essay_n=2)
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        const ids = [];
        filtered.chapters.forEach(ch => ch.questions.forEach(q => ids.push(q.id)));
        return ids;
        """,
        data=data,
    )
    assert out == ["C1", "C2", "C3"]


def test_tree_is_two_level_with_l2_filter_key():
    """章节树只到二级；L2.filterKey 为 l1|l2|选择题；无 UI 第三级。"""
    data = _sample_course(choice_n=30, essay_n=0, empty_essay_chapter=True)
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        const tree = api.buildChapterTreeFromChapters(filtered.chapters, true);
        const l2s = [];
        tree.forEach(l1 => l1.children.forEach(l2 => l2s.push(l2)));
        const first = l2s[0];
        // UI 层不应再依赖 sections 渲染；但 sections 可保留在数据里
        return {
          depth: 2,
          l1Count: tree.length,
          l2Count: l2s.length,
          l2Names: l2s.map(x => x.name),
          totals: l2s.map(x => x.total),
          filterKey: first && first.filterKey,
          l2Key: first && first.l2Key,
          keyEqualsFilter: first && first.key === first.filterKey,
          hasThirdLevelName: l2s.some(x => x.name === '选择题'),
        };
        """,
        data=data,
    )
    assert out["l1Count"] == 1
    assert out["l2Count"] == 1
    assert out["l2Names"] == ["1.1 基本概念"]
    assert out["totals"] == [30]
    assert out["filterKey"] == "第1章 绪论|1.1 基本概念|选择题"
    assert out["l2Key"] == "第1章 绪论|1.1 基本概念"
    assert out["keyEqualsFilter"] is True
    assert out["hasThirdLevelName"] is False


def test_old_choice_url_normalizes_to_l2_filter_key():
    """旧 URL `一级|二级|选择题` 能定位二级并规范为 filterKey。"""
    data = _sample_course(choice_n=12, essay_n=0)
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        const tree = api.buildChapterTreeFromChapters(filtered.chapters, true);
        const l2 = tree[0].children[0];
        const oldUrl = '第1章 绪论|1.1 基本概念|选择题';
        const r = api.sanitizeSelectedChapter(oldUrl, filtered.chapters, true);
        const match = api.l2MatchesSelection(l2, oldUrl);
        const matchL2Only = api.l2MatchesSelection(l2, '第1章 绪论|1.1 基本概念');
        const essay = api.sanitizeSelectedChapter('第1章 绪论|1.1 基本概念|解答题', filtered.chapters, true);
        // 模拟点击二级：filterKey 对应题目数
        const qCount = filtered.chapters
          .filter(ch => (ch.l1_name||'?')+'|'+(ch.l2_name||'')+'|'+(ch.section_type||'') === r.selectedChapter)
          .reduce((n, ch) => n + (ch.questions||[]).length, 0);
        return { r, match, matchL2Only, essay, qCount, l2Total: l2.total, filterKey: l2.filterKey };
        """,
        data=data,
    )
    assert out["match"] is True
    assert out["matchL2Only"] is True
    assert out["r"]["cleared"] is False
    assert out["r"]["selectedChapter"] == out["filterKey"]
    assert out["essay"]["cleared"] is True
    assert out["qCount"] == 12
    assert out["l2Total"] == 12


def test_real_courses_two_level_tree_no_choice_l3_name():
    """四门课：L2 名为小节名而非「选择题」，filterKey 以 |选择题 结尾，题数一致。"""
    for course_name, path in DATA_FILES.items():
        if not path.is_file():
            pytest.skip(f"missing {path.name}")
        out = _node_eval(
            """
            const filtered = api.filterCourseDataToChoices(DATA);
            const tree = api.buildChapterTreeFromChapters(filtered.chapters, true);
            let badName = null;
            let badKey = null;
            let totalFromL2 = 0;
            let l2Count = 0;
            tree.forEach(l1 => {
              if (!l1.children || !l1.children.length) throw new Error('empty l1 ' + l1.name);
              l1.children.forEach(l2 => {
                l2Count++;
                totalFromL2 += l2.total;
                if (l2.name === '选择题' || l2.name === '解答题') badName = l2.name;
                if (!l2.filterKey || !String(l2.filterKey).includes('|')) badKey = l2.filterKey;
                if (String(l2.filterKey).includes('解答')) badKey = l2.filterKey;
                // UI 两级：filterKey 供筛选；sections 仅内部
                if (!l2.total || l2.total <= 0) throw new Error('zero l2 ' + l2.name);
              });
            });
            return {
              total: filtered.total_questions,
              totalFromL2,
              l2Count,
              l1Count: tree.length,
              badName,
              badKey,
            };
            """,
            data_path=path,
        )
        assert out["badName"] is None, f"{course_name} L2 named {out['badName']}"
        assert out["badKey"] is None, f"{course_name} bad filterKey {out['badKey']}"
        assert out["totalFromL2"] == out["total"], course_name
        assert out["l2Count"] > 0, course_name
        assert out["l1Count"] > 0, course_name


def test_l1_chapter_deep_link_kept():
    """平台「去刷题」整章深链：无 '|' 的 l1 章名应保留，未知章名清空。"""
    path = DATA_FILES["数据结构"]
    if not path.is_file():
        pytest.skip("missing data-ds.json")
    out = _node_eval(
        """
        const filtered = api.filterCourseDataToChoices(DATA);
        const l1 = filtered.chapters[0].l1_name;
        const ok = api.sanitizeSelectedChapter(l1, filtered.chapters, true);
        const bad = api.sanitizeSelectedChapter('不存在的章名', filtered.chapters, true);
        return { l1, ok, bad };
        """,
        data_path=path,
    )
    assert out["ok"]["cleared"] is False
    assert out["ok"]["selectedChapter"] == out["l1"]
    assert out["bad"]["cleared"] is True
