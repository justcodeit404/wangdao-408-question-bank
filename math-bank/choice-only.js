/**
 * 408 Viewer choice-only 数据视图纯函数（无 DOM）。
 * 不改源题库；仅在加载后过滤。
 * Node / 浏览器共用，供 app.js 与 tests 引用。
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  root.ChoiceOnlyView = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // 与 platform-v2 question_service.CHOICE_QUESTION_TYPES 对齐
  var CHOICE_QUESTION_TYPES = new Set([
    'single_choice',
    'multiple_choice',
    'ordered_choice',
    '选择题',
    'multiple',
    'multi',
    'single',
    '单选',
    '多选',
  ]);

  function isChoiceQuestionType(type) {
    var t = String(type || '').trim();
    if (!t) return false;
    var low = t.toLowerCase();
    if (CHOICE_QUESTION_TYPES.has(t) || CHOICE_QUESTION_TYPES.has(low)) return true;
    if (t.indexOf('选择') !== -1 && t.indexOf('解答') === -1) return true;
    if (low === 'choice' || /_choice$/.test(low) || /choice$/.test(low)) {
      if ((low.match(/choice/g) || []).length === 1 && low.length <= 32) return true;
    }
    return false;
  }

  /** section_type：选择题保留；解答题等非选择跳过；空标签有题时保留 */
  function isChoiceSectionType(sectionType) {
    var sec = String(sectionType || '').trim();
    if (!sec) return true;
    if (sec.indexOf('解答') !== -1) return false;
    if (isChoiceQuestionType(sec)) return true;
    if (sec.indexOf('选择') !== -1) return true;
    return false;
  }

  function chapterQuestionCount(ch) {
    if (!ch) return 0;
    if (typeof ch.question_count === 'number') return ch.question_count;
    return (ch.questions && ch.questions.length) || 0;
  }

  /**
   * 过滤课程数据为选择题视图：去掉非选择题与题数 0 的章节，重算课程/总题数。
   * 不修改入参对象（浅拷贝）。
   */
  function filterCourseDataToChoices(courseData) {
    if (!courseData || !courseData.chapters) return courseData;
    var total = 0;
    var chapters = [];
    (courseData.chapters || []).forEach(function (ch) {
      var qs = (ch.questions || []).filter(function (q) {
        return isChoiceQuestionType(q.type);
      });
      if (qs.length === 0) return;
      total += qs.length;
      var copy = Object.assign({}, ch, { questions: qs, question_count: qs.length });
      chapters.push(copy);
    });
    var courseTotals = {};
    chapters.forEach(function (ch) {
      var cname = ch.course || '';
      courseTotals[cname] = (courseTotals[cname] || 0) + ch.question_count;
    });
    var courses = (courseData.courses || []).map(function (c) {
      return Object.assign({}, c, { question_count: courseTotals[c.name] || 0 });
    });
    return Object.assign({}, courseData, {
      chapters: chapters,
      courses: courses,
      total_questions: total,
    });
  }

  /** 与 app.js buildAllQuestions 的 chapterKey 一致：空 l2/sec 用 '?' */
  function chapterTreeKey(ch) {
    var l1 = ch.l1_name || '?';
    var l2 = ch.l2_name || '?';
    var sec = ch.section_type || '?';
    return l1 + '|' + l2 + '|' + sec;
  }

  /** UI 二级节点键：一级|二级（不含 section）；空 l2 用 '?' 与 chapterKey 对齐 */
  function chapterL2Key(chOrL1, l2Name) {
    if (typeof chOrL1 === 'object' && chOrL1) {
      return (chOrL1.l1_name || '?') + '|' + (chOrL1.l2_name || '?');
    }
    return String(chOrL1 || '?') + '|' + (l2Name || '?');
  }

  /**
   * 构建章节树（逻辑仍聚合 section；UI 只渲染到 L2）。
   * choiceOnly=true 时跳过非选择题 section 与零题章节。
   * L2 节点：
   *   - key / filterKey：内部筛选键，优先 `l1|l2|选择题`（兼容旧 URL）
   *   - l2Key：`l1|l2`
   *   - total：该小章节可见选择题数
   *   - sections：保留供调试/兼容，渲染层不应再画第三级
   */
  function buildChapterTreeFromChapters(chapters, choiceOnly) {
    if (choiceOnly === undefined) choiceOnly = true;
    var l1Map = new Map();
    (chapters || []).forEach(function (ch) {
      var count = chapterQuestionCount(ch);
      if (count <= 0) return;
      var sec = ch.section_type || '';
      if (choiceOnly && !isChoiceSectionType(sec)) return;
      var l1 = ch.l1_name || '?';
      var l2 = ch.l2_name || '?';
      if (!l1Map.has(l1)) l1Map.set(l1, { name: l1, total: 0, l2Map: new Map() });
      var l1Node = l1Map.get(l1);
      l1Node.total += count;
      if (!l1Node.l2Map.has(l2)) {
        l1Node.l2Map.set(l2, {
          name: l2 === '?' ? (ch.l2_name || l2) : l2,
          total: 0,
          sections: [],
          l2Key: chapterL2Key(l1, l2),
          filterKey: '',
        });
      }
      var l2Node = l1Node.l2Map.get(l2);
      l2Node.total += count;
      var secKey = chapterTreeKey(ch);
      l2Node.sections.push({
        name: ch.name,
        section_type: sec,
        question_count: count,
        key: secKey,
      });
      // 筛选键：优先选择题 section；否则首个可见 section
      if (!l2Node.filterKey || sec === '选择题' || isChoiceSectionType(sec)) {
        if (!l2Node.filterKey || sec === '选择题') l2Node.filterKey = secKey;
      }
    });

    var result = [];
    l1Map.forEach(function (l1Node) {
      var l2List = [];
      l1Node.l2Map.forEach(function (l2Node) {
        if (!l2Node.sections.length || l2Node.total <= 0) return;
        if (!l2Node.filterKey) l2Node.filterKey = l2Node.sections[0].key;
        l2List.push({
          name: l2Node.name,
          total: l2Node.total,
          l2Key: l2Node.l2Key,
          key: l2Node.filterKey,
          filterKey: l2Node.filterKey,
          sections: l2Node.sections.slice(),
        });
      });
      if (!l2List.length || l1Node.total <= 0) return;
      var l1Total = 0;
      l2List.forEach(function (l2) { l1Total += l2.total; });
      result.push({ name: l1Node.name, total: l1Total, children: l2List });
    });
    return result;
  }

  /** Map 形态，供 app.js renderChapters 消费（两级 UI） */
  function buildChapterTreeMap(chapters, choiceOnly) {
    var arr = buildChapterTreeFromChapters(chapters, choiceOnly);
    var l1Map = new Map();
    arr.forEach(function (l1) {
      var l2Map = new Map();
      l1.children.forEach(function (l2) {
        l2Map.set(l2.name, {
          name: l2.name,
          total: l2.total,
          l2Key: l2.l2Key,
          key: l2.key,
          filterKey: l2.filterKey,
          sections: l2.sections,
        });
      });
      l1Map.set(l1.name, { name: l1.name, total: l1.total, l2Map: l2Map });
    });
    return l1Map;
  }

  /**
   * 判断 selectedChapter（可能是 l1|l2|选择题 旧 URL）是否对应某个 L2 节点。
   * 解答题 section 永不匹配。
   */
  function l2MatchesSelection(l2Node, selectedChapter) {
    if (!selectedChapter || !l2Node) return false;
    var sel = String(selectedChapter);
    if (sel.indexOf('解答') !== -1) return false;
    if (sel === l2Node.filterKey || sel === l2Node.key) return true;
    if (l2Node.l2Key && sel === l2Node.l2Key) return true;
    if (l2Node.l2Key && sel.indexOf(l2Node.l2Key + '|') === 0) {
      var rest = sel.slice(l2Node.l2Key.length + 1);
      if (rest.indexOf('解答') !== -1) return false;
      return true;
    }
    // sections 精确命中
    var secs = l2Node.sections || [];
    for (var i = 0; i < secs.length; i++) {
      if (secs[i].key === sel && String(secs[i].section_type || '').indexOf('解答') === -1) {
        return true;
      }
    }
    return false;
  }

  /** 将任意合法选中态规范为 L2.filterKey（内部筛选键） */
  function normalizeToFilterKey(selectedChapter, chapters, choiceOnly) {
    if (!selectedChapter) return '';
    var tree = buildChapterTreeFromChapters(chapters, choiceOnly !== false);
    for (var i = 0; i < tree.length; i++) {
      var kids = tree[i].children || [];
      for (var j = 0; j < kids.length; j++) {
        if (l2MatchesSelection(kids[j], selectedChapter)) {
          return kids[j].filterKey || kids[j].key || '';
        }
      }
    }
    return '';
  }

  /**
   * 题型统计项：仅 count>0 的题型。状态类统计由调用方另行追加。
   * @returns {Array<{label:string,value:number,action:string}>}
   */
  function buildTypeStatItems(typeCounts) {
    var TYPE_LABELS = {
      '选择题': '选择',
      '解答题': '解答',
      'single_choice': '单选',
      'multiple_choice': '多选',
      'ordered_choice': '连续多空',
    };
    var entries = Object.keys(typeCounts || {})
      .map(function (k) { return [k, typeCounts[k] || 0]; })
      .filter(function (e) { return e[1] > 0; });
    entries.sort(function (a, b) {
      if (a[0] === '选择题') return -1;
      if (b[0] === '选择题') return 1;
      return b[1] - a[1] || String(a[0]).localeCompare(String(b[0]));
    });
    return entries.map(function (e) {
      var type = e[0];
      var value = e[1];
      var label = TYPE_LABELS[type];
      if (!label) {
        label = String(type).replace(/题$/, '');
        if (!label) label = type;
      }
      return { label: label, value: value, action: type };
    });
  }

  /** 收集树中全部可筛选 key（section key + l2Key + filterKey） */
  function collectSectionKeys(treeArr) {
    var keys = new Set();
    (treeArr || []).forEach(function (l1) {
      (l1.children || []).forEach(function (l2) {
        if (l2.filterKey) keys.add(l2.filterKey);
        if (l2.key) keys.add(l2.key);
        if (l2.l2Key) keys.add(l2.l2Key);
        (l2.sections || []).forEach(function (s) {
          if (s.key) keys.add(s.key);
        });
      });
    });
    return keys;
  }

  /**
   * 旧 URL / local 状态：
   * - 合法 `l1|l2|选择题` / `l1|l2` → 规范为 filterKey
   * - 解答题 / 无效 → 清空（全部章节）
   * @returns {{ selectedChapter: string, cleared: boolean }}
   */
  function sanitizeSelectedChapter(selectedChapter, chapters, choiceOnly) {
    if (!selectedChapter) return { selectedChapter: '', cleared: false };
    if (String(selectedChapter).indexOf('解答') !== -1) {
      return { selectedChapter: '', cleared: true };
    }
    var normalized = normalizeToFilterKey(selectedChapter, chapters, choiceOnly);
    if (normalized) {
      return {
        selectedChapter: normalized,
        cleared: false,
        changed: normalized !== selectedChapter,
      };
    }
    return { selectedChapter: '', cleared: true };
  }

  /**
   * 题型筛选值：若当前无可匹配题型则清空。
   */
  function sanitizeTypeFilter(typeValue, typeCounts) {
    if (!typeValue) return { type: '', cleared: false };
    if ((typeCounts || {})[typeValue] > 0) return { type: typeValue, cleared: false };
    return { type: '', cleared: true };
  }

  /** 统计文案中是否应出现某标签（count 必须 >0 才出现题型 pill） */
  function typeStatLabels(typeCounts) {
    return buildTypeStatItems(typeCounts).map(function (s) { return s.label; });
  }

  return {
    CHOICE_QUESTION_TYPES: CHOICE_QUESTION_TYPES,
    isChoiceQuestionType: isChoiceQuestionType,
    isChoiceSectionType: isChoiceSectionType,
    filterCourseDataToChoices: filterCourseDataToChoices,
    buildChapterTreeFromChapters: buildChapterTreeFromChapters,
    buildChapterTreeMap: buildChapterTreeMap,
    buildTypeStatItems: buildTypeStatItems,
    typeStatLabels: typeStatLabels,
    sanitizeSelectedChapter: sanitizeSelectedChapter,
    sanitizeTypeFilter: sanitizeTypeFilter,
    chapterTreeKey: chapterTreeKey,
    chapterL2Key: chapterL2Key,
    collectSectionKeys: collectSectionKeys,
    l2MatchesSelection: l2MatchesSelection,
    normalizeToFilterKey: normalizeToFilterKey,
  };
});
