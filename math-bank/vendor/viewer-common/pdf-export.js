/**
 * Shared A4 landscape workbook print preview for the independent question banks.
 * Hosts keep their own stem/KaTeX/image renderers; this module only owns the
 * print document, pagination, resource readiness and print interaction.
 */
(function (global) {
  'use strict';

  var LARGE_BATCH_THRESHOLD = 100;
  var RENDER_CHUNK_SIZE = 20;
  var RESOURCE_TIMEOUT_MS = 15000;

  var PRINT_CSS = `
@page { size: A4 landscape; margin: 12mm 14mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #e5e7eb; }
body.viewer-pdf-body {
  color: #111827;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", system-ui, sans-serif;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}
.viewer-pdf-toolbar {
  position: sticky; top: 0; z-index: 10; display: flex; flex-wrap: wrap; align-items: center;
  gap: 10px; padding: 12px 18px; color: #111827; background: #fff;
  border-bottom: 1px solid #d1d5db; box-shadow: 0 2px 8px rgb(0 0 0 / 8%);
  font: 14px/1.5 "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
}
.viewer-pdf-toolbar-title { font-weight: 700; }
.viewer-pdf-toolbar-status { color: #4b5563; }
.viewer-pdf-toolbar-status.is-error { color: #b91c1c; font-weight: 700; }
.viewer-pdf-toolbar button {
  appearance: none; padding: 7px 12px; border: 1px solid #9ca3af; border-radius: 6px;
  color: #111827; background: #fff; cursor: pointer; font: inherit;
}
.viewer-pdf-toolbar button.viewer-pdf-print-button { color: #fff; background: #1f2937; border-color: #1f2937; }
.viewer-pdf-toolbar button:disabled { opacity: .45; cursor: wait; }
.viewer-pdf-toolbar-hint { flex-basis: 100%; padding: 7px 10px; border-radius: 6px; color: #92400e; background: #fef3c7; border: 1px solid #fcd34d; font-size: 12px; line-height: 1.5; }
.viewer-pdf-items { padding: 24px 12px 60px; }
.viewer-pdf-item {
  width: 297mm; min-height: 210mm; margin: 0 auto 24px; padding: 12mm 14mm;
  color: #111827; background: #fff; box-shadow: 0 2px 14px rgb(0 0 0 / 14%);
  font-size: 11pt; line-height: 1.65;
}
.viewer-pdf-qhead {
  display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
  margin-bottom: 6mm; padding-bottom: 2mm; border-bottom: 1px solid #d1d5db;
  color: #4b5563; font-size: 9pt; line-height: 1.4; break-after: avoid; page-break-after: avoid;
}
.viewer-pdf-qhead-title { min-width: 0; overflow-wrap: anywhere; }
.viewer-pdf-qhead-count { flex: none; white-space: nowrap; }
.viewer-pdf-question { max-width: none; color: #111827; overflow-wrap: break-word; }
.viewer-pdf-question::after { content: ''; display: block; clear: both; }
.viewer-pdf-meta { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-bottom: 4mm; color: #4b5563; font-size: 9pt; }
.viewer-pdf-options { margin-top: 4mm; }
.viewer-pdf-option { display: flex; align-items: flex-start; gap: 6px; margin: 2mm 0; break-inside: avoid; page-break-inside: avoid; }
.viewer-pdf-option strong { flex: none; }
.viewer-pdf-question img { max-width: 92mm !important; max-height: 58mm !important; height: auto; object-fit: contain; }
/* 题图改为右侧浮动小图：正文绕排，不再独占整行版面 */
.viewer-pdf-question .q-image,
.viewer-pdf-question figure {
  float: right; max-width: 92mm; margin: 0 0 3mm 8mm; padding: 0; border: 0; border-radius: 0;
  background: transparent; box-shadow: none; text-align: center;
}
.viewer-pdf-question .q-image-content { padding: 0 !important; }
.viewer-pdf-question .q-image-note { display: none !important; }
.viewer-pdf-question .option-item .q-image,
.viewer-pdf-question .option-item figure,
.viewer-pdf-question table .q-image,
.viewer-pdf-question table figure { float: none; margin: 2mm 0; }
.viewer-pdf-question .sub-item {
  padding: 0; margin: 2mm 0; border: 0; border-radius: 0; background: transparent;
}
.viewer-pdf-question input,
.viewer-pdf-question textarea,
.viewer-pdf-question select,
.viewer-pdf-question button { display: none !important; }
.viewer-pdf-question .q-image img,
.viewer-pdf-question figure img { display: block; margin: 4mm auto; }
.viewer-pdf-question .q-image,
.viewer-pdf-question figure,
.viewer-pdf-question .option-item,
.viewer-pdf-question .opt,
.viewer-pdf-question tr { break-inside: avoid; page-break-inside: avoid; }
.viewer-pdf-question pre {
  max-width: 100% !important; white-space: pre-wrap !important;
  overflow-wrap: anywhere; word-break: break-word; overflow: visible !important;
}
.viewer-pdf-question table { max-width: 100%; border-collapse: collapse; }
.viewer-pdf-question .stem-table { overflow: visible !important; }
.viewer-pdf-question .q-image-zoom,
.viewer-pdf-question .zoom-overlay { display: none !important; }
/* 首页目录：每题一行、双栏铺满 A4 横版；行高固定，才能按行数切页 */
.viewer-pdf-toc-head {
  display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
  margin: 0 0 4mm; padding-bottom: 2mm; border-bottom: 1px solid #6b7280;
  color: #111827; font-size: 15pt; font-weight: 700; line-height: 1.3;
  break-after: avoid; page-break-after: avoid;
}
.viewer-pdf-toc-head-meta { color: #6b7280; font-size: 9pt; font-weight: 400; }
.viewer-pdf-toc-columns { display: flex; align-items: flex-start; gap: 0 12mm; }
.viewer-pdf-toc-column { flex: 1 1 0; min-width: 0; }
.viewer-pdf-toc-row {
  display: flex; align-items: baseline; height: 6.5mm; line-height: 6.2mm;
  border-bottom: 1px solid #f1f5f9; color: #111827; font-size: 9.5pt;
  break-inside: avoid; page-break-inside: avoid;
}
.viewer-pdf-toc-num { flex: none; width: 17mm; color: #6b7280; font-variant-numeric: tabular-nums; }
.viewer-pdf-toc-label { flex: 0 1 auto; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.viewer-pdf-toc-leader { flex: 1 1 8mm; min-width: 8mm; margin: 0 2mm; border-bottom: 1px dotted #9ca3af; }
.viewer-pdf-toc-page { flex: none; min-width: 9mm; text-align: right; color: #374151; font-variant-numeric: tabular-nums; }
.viewer-pdf-toc-note { margin: 3mm 0 0; color: #9ca3af; font-size: 8pt; line-height: 1.4; }
.viewer-pdf-toolbar label.viewer-pdf-bookmark {
  display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px;
  border: 1px solid #9ca3af; border-radius: 6px; color: #111827; background: #fff;
  cursor: pointer; font: inherit;
}
.viewer-pdf-toolbar label.viewer-pdf-bookmark:hover { background: #f3f4f6; }
.viewer-pdf-toolbar label.viewer-pdf-bookmark.is-busy { opacity: .45; cursor: wait; }
@media print {
  html, body, body.viewer-pdf-body { background: #fff !important; }
  body.viewer-pdf-body > *:not(.viewer-pdf-items) { display: none !important; }
  .viewer-pdf-items { padding: 0; }
  .viewer-pdf-item {
    width: auto; min-height: 0; margin: 0; padding: 0; border: 0; box-shadow: none;
    break-after: page; page-break-after: always;
  }
  .viewer-pdf-item:last-child { break-after: auto; page-break-after: auto; }
  .viewer-pdf-question a { color: inherit; text-decoration: none; }
}
`;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function alertHost(message) {
    if (typeof global.alert === 'function') global.alert(message);
  }

  function confirmHost(message) {
    return typeof global.confirm === 'function' ? global.confirm(message) : true;
  }

  function yieldToBrowser() {
    return new Promise(function (resolve) { global.setTimeout(resolve, 0); });
  }

  function sourceStylesHtml() {
    if (!global.document || !global.document.querySelectorAll) return '';
    var nodes = global.document.querySelectorAll('link[rel="stylesheet"], style');
    var html = '';
    for (var i = 0; i < nodes.length; i++) html += nodes[i].outerHTML + '\n';
    return html;
  }

  function documentShell(title, count) {
    var sourceDoc = global.document || {};
    var baseURI = sourceDoc.baseURI || (global.location && global.location.href) || '';
    return '<!doctype html><html lang="zh-CN" data-theme="light"><head>' +
      '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
      (baseURI ? '<base href="' + escapeHtml(baseURI) + '">' : '') +
      '<title>' + escapeHtml(title) + '</title>' + sourceStylesHtml() +
      '<style>' + PRINT_CSS + '</style></head><body class="viewer-pdf-body">' +
      '<div class="viewer-pdf-toolbar" role="region" aria-label="做题本打印工具栏">' +
      '<span class="viewer-pdf-toolbar-title">' + escapeHtml(title) + '</span>' +
      '<span class="viewer-pdf-toolbar-status" id="viewerPdfStatus">正在准备 ' + count + ' 道题…</span>' +
      '<button type="button" class="viewer-pdf-print-button" id="viewerPdfPrint" disabled>打印 / 保存 PDF</button>' +
      '<label class="viewer-pdf-bookmark" title="保存 PDF 后选中该文件，在浏览器内直接写入每页书签">' +
      '为 PDF 加书签<input type="file" id="viewerPdfBookmarkFile" accept="application/pdf,.pdf" hidden>' +
      '</label>' +
      '<span class="viewer-pdf-toolbar-status" id="viewerPdfBookmarkStatus"></span>' +
      '<button type="button" id="viewerPdfClose">关闭</button>' +
      '<span class="viewer-pdf-toolbar-hint">打印设置：目标打印机选 <b>“另存为 PDF”</b>，纸张 A4、布局<b>横向</b>，并<b>取消勾选“页眉和页脚”</b>。' +
      '若用 Microsoft Print to PDF 等系统打印机且布局为纵向，横版页面会被旋转 90° 塞进竖纸。首页为目录（可关闭），其后每题一页、不含答案，超长题自动续页。保存后点「为 PDF 加书签」再选一次该文件，就会在浏览器内写入每页可点击跳转的书签（不上传）。</span>' +
      '</div><main class="viewer-pdf-items" id="viewerPdfItems"></main></body></html>';
  }

  function questionShell(title, html, index, total) {
    return '<section class="viewer-pdf-item">' +
      '<header class="viewer-pdf-qhead"><span class="viewer-pdf-qhead-title">' + escapeHtml(title) + '</span>' +
      '<span class="viewer-pdf-qhead-count">第 ' + (index + 1) + ' / ' + total + ' 题</span></header>' +
      '<div class="viewer-pdf-question">' + String(html || '') + '</div></section>';
  }

  /**
   * 题干级配图默认排在文字之后，右侧浮动无法绕排；打印前把它提到最前，
   * 正文才会贴着图排。选项/表格里的图保持原位。
   */
  function hoistFigures(printDoc) {
    if (!printDoc.querySelectorAll) return;
    var questions = printDoc.querySelectorAll('.viewer-pdf-question');
    for (var i = 0; i < questions.length; i++) {
      var q = questions[i];
      var kids = Array.prototype.slice.call(q.children);
      for (var j = 0; j < kids.length; j++) {
        var el = kids[j];
        if (!el.classList || !el.classList.contains('q-image')) continue;
        if (el.parentNode !== q || q.firstChild === el) continue;
        q.insertBefore(el, q.firstChild);
      }
    }
  }

  function prepareImages(printDoc) {
    if (!printDoc.querySelectorAll) return [];
    var nodes = printDoc.querySelectorAll('.viewer-pdf-question img');
    var images = [];
    for (var i = 0; i < nodes.length; i++) {
      var img = nodes[i];
      img.setAttribute('loading', 'eager');
      img.removeAttribute('onclick');
      if (img.getAttribute('src')) images.push(img);
    }
    return images;
  }

  async function waitForResources(printDoc, images) {
    var fontReady = printDoc.fonts && printDoc.fonts.ready
      ? Promise.resolve(printDoc.fonts.ready).catch(function () {})
      : Promise.resolve();
    var imageReady = Promise.all(images.map(function (img) {
      if (img.complete) return Promise.resolve();
      return new Promise(function (resolve) {
        img.addEventListener('load', resolve, { once: true });
        img.addEventListener('error', resolve, { once: true });
      });
    }));
    var timer = null;
    var timeout = new Promise(function (resolve) {
      timer = global.setTimeout(resolve, RESOURCE_TIMEOUT_MS);
    });
    await Promise.race([Promise.all([fontReady, imageReady]), timeout]);
    global.clearTimeout(timer);
    return images.filter(function (img) { return !img.complete || img.naturalWidth === 0; }).length;
  }

  var TOC_FALLBACK_ROWS_PER_PAGE = 40;
  var TOC_LABEL_MAX_CHARS = 46;
  // 打印页内容区：A4 横版 297x210mm 去掉 @page 的 14mm/12mm 页边距
  var TOC_PAGE_WIDTH_MM = 269;
  var TOC_PAGE_HEIGHT_MM = 186;
  var TOC_NOTE = '每题单独起页 · 页码按版面高度推算，超长题续页时其后页码可能有偏差';
  var BOOKMARK_LABEL_MAX_CHARS = 52;
  // 书签在浏览器内写入：pdf-lib 与本文件同目录，丢失时回退 CDN
  var PDFLIB_FILE = 'pdf-lib.min.js';
  var PDFLIB_CDN = 'https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.min.js';
  // pdf-export.js 自身所在目录：独立端口是 vendor/viewer-common/，平台是 /banks/common/
  var SCRIPT_BASE = (function () {
    var script = global.document && global.document.currentScript;
    if (!script || !script.src) return '';
    return script.src.replace(/[?#].*$/, '').replace(/[^/]*$/, '');
  })();

  /**
   * 浏览器打印接口不暴露“总共分了多少页”，目录要标页码只能自己量：
   * 屏幕预览与打印共用同一套 mm 尺寸（297x210 减页边距），按外观高度除以单页
   * 可用高度即可推出每题占几页，再逐题累加得到起始页码。
   */
  function measurePrintPage(printDoc) {
    if (!printDoc || !printDoc.body || typeof printDoc.createElement !== 'function') return null;
    var probe = printDoc.createElement('div');
    probe.setAttribute('aria-hidden', 'true');
    probe.style.cssText = 'position:absolute;left:-10000px;top:0;visibility:hidden;' +
      'width:' + TOC_PAGE_WIDTH_MM + 'mm;height:' + TOC_PAGE_HEIGHT_MM + 'mm;';
    printDoc.body.appendChild(probe);
    var rect = typeof probe.getBoundingClientRect === 'function' ? probe.getBoundingClientRect() : null;
    printDoc.body.removeChild(probe);
    return rect && rect.height ? { width: rect.width, height: rect.height } : null;
  }

  function boxHeight(printDoc, el, includeMargins) {
    if (!el || typeof el.getBoundingClientRect !== 'function') return 0;
    var height = el.getBoundingClientRect().height || 0;
    var view = printDoc.defaultView || global;
    if (includeMargins && view && typeof view.getComputedStyle === 'function') {
      var style = view.getComputedStyle(el);
      height += (parseFloat(style.marginTop) || 0) + (parseFloat(style.marginBottom) || 0);
    }
    return height > 0 ? height : 0;
  }

  /** 题目页在屏幕上是 297x210mm 加内边距，减掉内边距才是正文实际高度。 */
  function itemContentHeight(printDoc, item) {
    if (!item || typeof item.getBoundingClientRect !== 'function') return 0;
    var height = item.getBoundingClientRect().height || 0;
    var view = printDoc.defaultView || global;
    if (view && typeof view.getComputedStyle === 'function') {
      var style = view.getComputedStyle(item);
      height -= (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
    }
    return height > 0 ? height : 0;
  }

  /** 用与真实目录同类的探针量标题/行/脚注高度，算出一页能排多少行。 */
  function measureTocRowsPerPage(printDoc, pageBox) {
    if (!pageBox || !printDoc || !printDoc.body || typeof printDoc.createElement !== 'function') return 0;
    var probe = printDoc.createElement('section');
    probe.className = 'viewer-pdf-item viewer-pdf-toc';
    probe.setAttribute('aria-hidden', 'true');
    probe.style.cssText = 'position:absolute;left:-10000px;top:0;visibility:hidden;';
    probe.innerHTML = tocHeadHtml(1, 1, 1) +
      '<div class="viewer-pdf-toc-columns"><div class="viewer-pdf-toc-column">' +
      tocRowHtml({ index: 1, label: '示例题目', page: 9 }) +
      '</div><div class="viewer-pdf-toc-column"></div></div>' +
      '<p class="viewer-pdf-toc-note">' + escapeHtml(TOC_NOTE) + '</p>';
    printDoc.body.appendChild(probe);
    var row = typeof probe.querySelector === 'function' ? probe.querySelector('.viewer-pdf-toc-row') : null;
    var head = typeof probe.querySelector === 'function' ? probe.querySelector('.viewer-pdf-toc-head') : null;
    var note = typeof probe.querySelector === 'function' ? probe.querySelector('.viewer-pdf-toc-note') : null;
    var rows = 0;
    if (row && head && note) {
      var rowHeight = boxHeight(printDoc, row, false);
      // 留 2mm 余量：mm 取整若把最后一行挤到新页，后面所有页码都会漂移
      var slack = (pageBox.height / TOC_PAGE_HEIGHT_MM) * 2;
      var usable = pageBox.height - slack - boxHeight(printDoc, head, true) - boxHeight(printDoc, note, true);
      if (rowHeight > 0 && usable > rowHeight * 2) rows = Math.floor(usable / rowHeight) * 2;
    }
    printDoc.body.removeChild(probe);
    return rows;
  }

  function tocHeadHtml(pageNo, pageCount, total) {
    return '<header class="viewer-pdf-toc-head"><span>目录</span>' +
      '<span class="viewer-pdf-toc-head-meta">共 ' + total + ' 题 · 目录第 ' + pageNo + ' / ' + pageCount + ' 页</span></header>';
  }

  function tocRowHtml(entry) {
    return '<div class="viewer-pdf-toc-row">' +
      '<span class="viewer-pdf-toc-num">第 ' + entry.index + ' 题</span>' +
      '<span class="viewer-pdf-toc-label">' + escapeHtml(entry.label) + '</span>' +
      '<span class="viewer-pdf-toc-leader" aria-hidden="true"></span>' +
      '<span class="viewer-pdf-toc-page">' + entry.page + '</span></div>';
  }

  function tocColumnHtml(rows) {
    var html = '<div class="viewer-pdf-toc-column">';
    for (var i = 0; i < rows.length; i++) html += tocRowHtml(rows[i]);
    return html + '</div>';
  }

  /** 目录标签：宿主可用 tocLabel(q, index) 覆盖，否则取题干前几十字。 */
  function tocEntryLabel(item, question, index, options) {
    if (options && typeof options.tocLabel === 'function') {
      try {
        var custom = options.tocLabel(question, index);
        if (custom != null && String(custom).trim()) return String(custom).trim();
      } catch (error) {
        // 宿主标签出错时退回题干摘要，别让目录拖垮整份导出
      }
    }
    var body = item && typeof item.querySelector === 'function' ? item.querySelector('.viewer-pdf-question') : null;
    var text = body && body.textContent ? String(body.textContent) : '';
    text = text.replace(/\s+/g, ' ').trim();
    if (!text) return '第 ' + (index + 1) + ' 题';
    return text.length > TOC_LABEL_MAX_CHARS ? text.slice(0, TOC_LABEL_MAX_CHARS) + '…' : text;
  }

  /**
   * 每题起新页：量一遍版面高度，得到每题占几页。
   * 目录页码和 PDF 书签都基于这份映射，所以即使关掉目录也要算。
   */
  function measureWorkbook(printDoc, items) {
    var nodes = typeof items.querySelectorAll === 'function' ? items.querySelectorAll('.viewer-pdf-item') : [];
    var pageBox = measurePrintPage(printDoc);
    var spans = [];
    for (var i = 0; i < nodes.length; i++) {
      spans.push(pageBox
        ? Math.max(1, Math.ceil((itemContentHeight(printDoc, nodes[i]) - 0.5) / pageBox.height))
        : 1);
    }
    return { nodes: nodes, pageBox: pageBox, spans: spans };
  }

  function tocPagesFor(printDoc, layout) {
    if (!layout.nodes.length) return 0;
    var perPage = Math.max(2, measureTocRowsPerPage(printDoc, layout.pageBox) || TOC_FALLBACK_ROWS_PER_PAGE);
    return Math.max(1, Math.ceil(layout.nodes.length / perPage));
  }

  function buildEntries(questions, layout, options, tocPageCount) {
    var entries = [];
    var page = tocPageCount + 1;
    for (var i = 0; i < layout.nodes.length; i++) {
      entries.push({
        index: i + 1,
        label: tocEntryLabel(layout.nodes[i], questions[i], i, options),
        page: page,
        span: layout.spans[i],
      });
      page += layout.spans[i];
    }
    return entries;
  }

  function tocPagesHtml(entries, tocPageCount) {
    // 按页数均分：ceil(total/pages) 恒 ≤ 实测每页容量
    var perPage = Math.max(2, Math.ceil(entries.length / tocPageCount));
    var html = '';
    for (var p = 0; p < tocPageCount; p++) {
      var slice = entries.slice(p * perPage, (p + 1) * perPage);
      var half = Math.ceil(slice.length / 2);
      html += '<section class="viewer-pdf-item viewer-pdf-toc">' +
        tocHeadHtml(p + 1, tocPageCount, entries.length) +
        '<div class="viewer-pdf-toc-columns">' +
        tocColumnHtml(slice.slice(0, half)) +
        tocColumnHtml(slice.slice(half)) +
        '</div>' +
        (p === tocPageCount - 1 ? '<p class="viewer-pdf-toc-note">' + escapeHtml(TOC_NOTE) + '</p>' : '') +
        '</section>';
    }
    return html;
  }

  function shorten(text, max) {
    return text.length > max ? text.slice(0, max) + '\u2026' : text;
  }

  /** 书签标题：一页一条，续页标「续 n」；目录页也各占一条。 */
  function buildPageTitles(entries, tocPageCount) {
    var titles = [];
    for (var p = 1; p <= tocPageCount; p++) {
      titles.push(tocPageCount > 1 ? '目录 ' + p + '/' + tocPageCount : '目录');
    }
    for (var i = 0; i < entries.length; i++) {
      var entry = entries[i];
      for (var s = 0; s < entry.span; s++) {
        titles.push(shorten(s === 0
          ? '第 ' + entry.index + ' 题 · ' + entry.label
          : '第 ' + entry.index + ' 题（续 ' + (s + 1) + '）', BOOKMARK_LABEL_MAX_CHARS));
      }
    }
    return titles;
  }

  function loadScript(url) {
    return new Promise(function (resolve, reject) {
      var doc = global.document;
      if (!doc || typeof doc.createElement !== 'function') {
        reject(new Error('当前环境不支持加载脚本'));
        return;
      }
      var script = doc.createElement('script');
      script.src = url;
      script.async = true;
      script.onload = function () { resolve(); };
      script.onerror = function () { reject(new Error('无法加载 ' + url)); };
      (doc.head || doc.body || doc.documentElement).appendChild(script);
    });
  }

  var pdfLibPromise = null;

  /** 惰性加载 pdf-lib：先本地目录，不行再走 CDN（国内 CDN 时好时坏）。 */
  function loadPdfLib() {
    if (global.PDFLib) return Promise.resolve(global.PDFLib);
    if (pdfLibPromise) return pdfLibPromise;
    var urls = [];
    if (SCRIPT_BASE) urls.push(SCRIPT_BASE + PDFLIB_FILE);
    urls.push(PDFLIB_CDN);
    pdfLibPromise = (async function () {
      var lastError = null;
      for (var i = 0; i < urls.length; i++) {
        try {
          await loadScript(urls[i]);
          if (global.PDFLib) return global.PDFLib;
          lastError = new Error(urls[i] + ' 未暴露 PDFLib');
        } catch (error) {
          lastError = error;
        }
      }
      pdfLibPromise = null;
      throw lastError || new Error('书签组件未加载');
    })();
    return pdfLibPromise;
  }

  /** 把原 PDF 每页写成一条可点击跳转的书签（目录树 /Outlines）。 */
  async function injectBookmarks(file, titles) {
    var PDFLib = await loadPdfLib();
    var doc = await PDFLib.PDFDocument.load(new Uint8Array(await file.arrayBuffer()), {
      ignoreEncryption: true,
      updateMetadata: false,
    });
    var pages = doc.getPages();
    if (!pages.length) throw new Error('这份 PDF 没有页面');
    var name = PDFLib.PDFName.of;
    var context = doc.context;
    var items = [];
    for (var i = 0; i < pages.length; i++) {
      var dict = context.obj({});
      dict.set(name('Title'), PDFLib.PDFHexString.fromText(titles[i] || '第 ' + (i + 1) + ' 页'));
      dict.set(name('Dest'), context.obj([
        pages[i].ref, name('XYZ'), PDFLib.PDFNull, PDFLib.PDFNull, PDFLib.PDFNull,
      ]));
      items.push({ dict: dict, ref: context.register(dict) });
    }
    var outlines = context.obj({});
    var outlinesRef = context.register(outlines);
    for (var j = 0; j < items.length; j++) {
      items[j].dict.set(name('Parent'), outlinesRef);
      if (j > 0) items[j].dict.set(name('Prev'), items[j - 1].ref);
      if (j < items.length - 1) items[j].dict.set(name('Next'), items[j + 1].ref);
    }
    outlines.set(name('Type'), name('Outlines'));
    outlines.set(name('First'), items[0].ref);
    outlines.set(name('Last'), items[items.length - 1].ref);
    outlines.set(name('Count'), PDFLib.PDFNumber.of(items.length));
    // PageMode=UseOutlines：打开 PDF 时书签栏直接展开
    doc.catalog.set(name('Outlines'), outlinesRef);
    doc.catalog.set(name('PageMode'), name('UseOutlines'));
    return { bytes: await doc.save(), pageCount: pages.length, mismatch: pages.length !== titles.length };
  }

  function setToolbarStatus(el, text, isError) {
    if (!el) return;
    el.textContent = text;
    if (!el.classList) return;
    if (isError) el.classList.add('is-error');
    else el.classList.remove('is-error');
  }

  function downloadBlob(printDoc, blob, filename) {
    var url = global.URL.createObjectURL(blob);
    var link = printDoc.createElement('a');
    link.href = url;
    link.download = filename;
    printDoc.body.appendChild(link);
    link.click();
    printDoc.body.removeChild(link);
    global.setTimeout(function () { global.URL.revokeObjectURL(url); }, 60000);
  }

  function wireBookmarkInput(printDoc, input, statusEl, titles) {
    var label = input.parentNode;
    input.onchange = function () {
      var file = input.files && input.files[0];
      if (!file) return;
      input.disabled = true;
      if (label && label.classList) label.classList.add('is-busy');
      setToolbarStatus(statusEl, '正在为 ' + file.name + ' 写入 ' + titles.length + ' 条书签…', false);
      injectBookmarks(file, titles).then(function (result) {
        downloadBlob(printDoc, new Blob([result.bytes], { type: 'application/pdf' }),
          file.name.replace(/\.pdf$/i, '') + '-带书签.pdf');
        setToolbarStatus(statusEl, result.mismatch
          ? '已写入 ' + result.pageCount + ' 条书签，但这份 PDF 实际 ' + result.pageCount +
            ' 页，与预览推算的 ' + titles.length + ' 页不一致，标题可能错位；请按提示的打印设置重新另存。'
          : '已写入 ' + result.pageCount + ' 条书签，正在下载。', result.mismatch);
      }).catch(function (error) {
        setToolbarStatus(statusEl, '写入书签失败：' + (error && error.message ? error.message : String(error)), true);
      }).then(function () {
        input.disabled = false;
        input.value = '';
        if (label && label.classList) label.classList.remove('is-busy');
      });
    };
  }

  /**
   * Open a printable workbook. The popup is created before the first await so
   * browsers still treat it as part of the user's click gesture.
   */
  async function open(options) {
    options = options || {};
    var questions = Array.isArray(options.questions) ? options.questions.slice() : [];
    var title = String(options.title || '题库做题本');
    if (!questions.length) {
      alertHost('当前没有可导出的题目，请先调整筛选条件。');
      return false;
    }
    if (typeof options.renderQuestion !== 'function') {
      alertHost('导出组件缺少题目渲染器。');
      return false;
    }
    var threshold = Number(options.confirmAbove) > 0 ? Number(options.confirmAbove) : LARGE_BATCH_THRESHOLD;
    if (questions.length > threshold && !confirmHost(
      '当前共 ' + questions.length + ' 道题，预计至少生成 ' + questions.length + ' 页 PDF（超长题会续页）。继续吗？'
    )) return false;

    var printWindow = global.open('', '_blank');
    if (!printWindow) {
      alertHost('浏览器拦截了打印窗口。请允许本站打开弹窗后重试。');
      return false;
    }

    var status = null;
    try {
      var printDoc = printWindow.document;
      printDoc.open();
      printDoc.write(documentShell(title, questions.length));
      printDoc.close();
      printDoc.title = title;

      var items = printDoc.getElementById('viewerPdfItems');
      status = printDoc.getElementById('viewerPdfStatus');
      var printButton = printDoc.getElementById('viewerPdfPrint');
      var bookmarkInput = printDoc.getElementById('viewerPdfBookmarkFile');
      var bookmarkStatus = printDoc.getElementById('viewerPdfBookmarkStatus');
      var closeButton = printDoc.getElementById('viewerPdfClose');
      printButton.onclick = function () { printWindow.focus(); printWindow.print(); };
      closeButton.onclick = function () { printWindow.close(); };

      var html = [];
      for (var i = 0; i < questions.length; i++) {
        if (printWindow.closed) return false;
        var rendered = options.renderQuestion(questions[i], i);
        html.push(questionShell(title, rendered, i, questions.length));
        if ((i + 1) % RENDER_CHUNK_SIZE === 0 || i === questions.length - 1) {
          items.insertAdjacentHTML('beforeend', html.join(''));
          html = [];
          status.textContent = '正在排版 ' + (i + 1) + ' / ' + questions.length + ' 题…';
          await yieldToBrowser();
        }
      }
      hoistFigures(printDoc);
      var images = prepareImages(printDoc);
      status.textContent = images.length ? '正在等待字体与 ' + images.length + ' 张题图加载…' : '正在等待字体加载…';
      var failedImages = await waitForResources(printDoc, images);
      var layout = measureWorkbook(printDoc, items);
      var tocPageCount = 0;
      if (options.toc !== false && layout.nodes.length) {
        status.textContent = '正在生成目录…';
        await yieldToBrowser();
        tocPageCount = tocPagesFor(printDoc, layout);
      }
      var entries = buildEntries(questions, layout, options, tocPageCount);
      if (tocPageCount) items.insertAdjacentHTML('afterbegin', tocPagesHtml(entries, tocPageCount));
      if (bookmarkInput) wireBookmarkInput(printDoc, bookmarkInput, bookmarkStatus, buildPageTitles(entries, tocPageCount));
      printButton.disabled = false;
      if (printWindow.closed) return false;
      if (failedImages) {
        status.textContent = failedImages + ' 张题图未加载成功。请检查预览，勿直接导出缺图 PDF。';
        status.classList.add('is-error');
        alertHost('有 ' + failedImages + ' 张题图未加载成功，已暂停自动打印。请检查网络或刷新打印窗口后重试。');
        return false;
      }

      status.textContent = tocPageCount
        ? '已准备好 ' + questions.length + ' 道题（含 ' + tocPageCount + ' 页目录），可选择“另存为 PDF”。'
        : '已准备好 ' + questions.length + ' 道题，可选择“另存为 PDF”。';
      if (options.autoPrint === false) return true;
      await yieldToBrowser();
      printWindow.focus();
      printWindow.print();
      return true;
    } catch (error) {
      if (status) {
        status.textContent = '排版失败：' + (error && error.message ? error.message : String(error));
        status.classList.add('is-error');
      }
      alertHost('生成做题本失败：' + (error && error.message ? error.message : String(error)));
      return false;
    }
  }

  global.ViewerPdfExport = { open: open, _bookmarkTitles: buildPageTitles };
})(typeof window !== 'undefined' ? window : globalThis);
