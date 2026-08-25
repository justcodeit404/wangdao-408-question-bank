#!/usr/bin/env python3
"""生成可复现的 408 大章节分层抽检批次和原书对照页。"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from config import COURSES, MATH_BANK_DIR, REPORTS_DIR
from quality_hold import source_uid
from utils import write_json_atomic

DEFAULT_JSON = REPORTS_DIR / "chapter_sample_audit.json"
DEFAULT_HTML = REPORTS_DIR / "chapter_sample_audit.html"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_score(round_id: str, uid: str) -> str:
    return hashlib.sha256(f"{round_id}\0{uid}".encode()).hexdigest()


def _held_uids() -> set[str]:
    path = MATH_BANK_DIR / "quality-hold.json"
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(value) for value in payload.get("source_uids", [])}


def _choice_rows(course_key: str, data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for chapter_index, chapter in enumerate(data.get("chapters", [])):
        major = str(chapter.get("l1_name") or chapter.get("name") or "未知章节")
        minor = str(chapter.get("name") or chapter.get("topic_title") or major)
        for question_index, question in enumerate(chapter.get("questions", [])):
            if "选择" not in str(question.get("type") or ""):
                continue
            qid = str(question.get("id") or "").strip()
            if not qid:
                continue
            grouped.setdefault(major, []).append(
                {
                    "course_key": course_key,
                    "major_chapter": major,
                    "minor_chapter": minor,
                    "chapter_index": chapter_index,
                    "question_index": question_index,
                    "source_uid": source_uid(course_key, minor, qid),
                    "question": question,
                }
            )
    for rows in grouped.values():
        rows.sort(
            key=lambda row: (
                int(row["question"].get("page") or 0),
                row["chapter_index"],
                row["question_index"],
                str(row["question"].get("id") or ""),
            )
        )
    return grouped


def sample_major_chapter(
    rows: list[dict[str, Any]], per_chapter: int, round_id: str
) -> list[dict[str, Any]]:
    """按原书顺序等分，每段用稳定哈希抽一题。"""
    if per_chapter < 1:
        raise ValueError("per_chapter must be >= 1")
    count = min(per_chapter, len(rows))
    selected: list[dict[str, Any]] = []
    for index in range(count):
        start = index * len(rows) // count
        end = (index + 1) * len(rows) // count
        chosen = min(
            rows[start:end],
            key=lambda row: _stable_score(round_id, str(row["source_uid"])),
        )
        selected.append({**chosen, "stratum": index + 1})
    return selected


def _sample_payload(row: dict[str, Any], held: set[str]) -> dict[str, Any]:
    question = row["question"]
    page = int(question.get("page") or 0)
    q_pages = [int(value) for value in question.get("q_pages") or [] if value]
    a_pages = [int(value) for value in question.get("a_pages") or [] if value]
    if page and page not in q_pages:
        q_pages.insert(0, page)
    key = row["course_key"]
    return {
        "source_uid": row["source_uid"],
        "stratum": row["stratum"],
        "minor_chapter": row["minor_chapter"],
        "question_id": str(question.get("id") or ""),
        "page": page or None,
        "question_pages": q_pages,
        "answer_pages": a_pages,
        "content": str(question.get("content") or ""),
        "options": question.get("options") or {},
        "answer": question.get("answer") or {},
        "has_image": bool(question.get("has_image")),
        "image_ref": question.get("image_ref"),
        "quality_hold": row["source_uid"] in held,
        "question_page_images": [
            f"../../assets/pdf_images/{key}/page_{value:03d}.png" for value in q_pages
        ],
        "answer_page_images": [
            f"../../assets/pdf_images/{key}/page_{value:03d}.png" for value in a_pages
        ],
        "viewer_url": (
            f"../../math-bank/?course=cs408-{key}"
            f"&chapter={row['minor_chapter']}&search={question.get('id') or ''}"
        ),
    }


def build_batch(per_chapter: int = 5, round_id: str | None = None) -> dict[str, Any]:
    round_value = (round_id or date.today().isoformat()).strip()
    if not round_value:
        raise ValueError("round_id must not be empty")
    held = _held_uids()
    courses: list[dict[str, Any]] = []
    population = sampled = 0
    source_hashes: dict[str, str] = {}
    for course in COURSES:
        published = MATH_BANK_DIR / f"data-{course.key}.json"
        if not published.is_file():
            raise FileNotFoundError(f"published bank is missing: {published}")
        data = json.loads(published.read_text(encoding="utf-8"))
        chapters: list[dict[str, Any]] = []
        for major, rows in _choice_rows(course.key, data).items():
            samples = [
                _sample_payload(row, held)
                for row in sample_major_chapter(rows, per_chapter, round_value)
            ]
            population += len(rows)
            sampled += len(samples)
            chapters.append(
                {
                    "name": major,
                    "population": len(rows),
                    "sample_count": len(samples),
                    "samples": samples,
                }
            )
        source_hashes[course.key] = _sha256(published)
        courses.append(
            {
                "key": course.key,
                "name": course.name,
                "major_chapter_count": len(chapters),
                "chapters": chapters,
            }
        )
    return {
        "schema_version": 1,
        "round_id": round_value,
        "per_chapter": per_chapter,
        "sampling_method": "major chapter source-order strata + stable hash",
        "source_hashes": source_hashes,
        "summary": {
            "courses": len(courses),
            "major_chapters": sum(item["major_chapter_count"] for item in courses),
            "choice_population": population,
            "sampled": sampled,
            "held_in_sample": sum(
                int(sample["quality_hold"])
                for course in courses
                for chapter in course["chapters"]
                for sample in chapter["samples"]
            ),
        },
        "courses": courses,
    }


def render_html(batch: dict[str, Any]) -> str:
    encoded = json.dumps(batch, ensure_ascii=False).replace("</", "<\\/")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>408 章节抽检</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f6f7f9;color:#18202a;font:14px/1.55 system-ui,"PingFang SC",sans-serif}}
header{{position:sticky;top:0;z-index:2;padding:14px 20px;background:#f6f7f9ee;border-bottom:1px solid #dfe3e8}}h1{{margin:0;font-size:20px}}header p{{margin:3px 0;color:#64748b}}main{{max-width:1500px;margin:auto;padding:18px}}button,select,textarea{{font:inherit;border:1px solid #dfe3e8;border-radius:8px;padding:7px 10px}}button{{background:#fff;cursor:pointer}}button.active{{color:#fff;background:#4f46e5}}.toolbar{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.chapter{{margin:22px 0}}.card{{background:#fff;border:1px solid #dfe3e8;border-radius:12px;margin:10px 0;overflow:hidden}}.head,.review{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 14px}}.head{{border-bottom:1px solid #dfe3e8}}.uid{{font-size:12px;color:#64748b}}.hold,.bad{{color:#be123c}}.grid{{display:grid;grid-template-columns:minmax(340px,.8fr) minmax(440px,1.2fr)}}.bank{{padding:16px;border-right:1px solid #dfe3e8}}.source{{padding:12px;background:#eef1f5}}.source img{{display:block;width:100%;max-height:78vh;object-fit:contain;background:#fff;margin:6px 0}}.opts{{display:grid;gap:5px;margin:12px 0}}.answer{{padding:10px;background:#f1f5f9;white-space:pre-wrap}}.review{{border-top:1px solid #dfe3e8}}.review textarea{{flex:1;min-width:260px}}a{{color:#4f46e5}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}.bank{{border-right:0}}}}
</style></head><body><header><h1>408 章节抽检 · {batch['round_id']}</h1><p>每章按原书顺序五等分，每段稳定抽 1 题；左右对照题库和原书。</p><div class="toolbar"><button id="all" class="active">全部</button><button id="pending">未检查</button><button id="bad">有问题</button><button id="export">导出问题 JSON</button><span id="stats"></span></div></header><main id="root"></main>
<script>const BATCH={encoded};const KEY='bank408:chapter-audit:'+BATCH.round_id;let state={{}};try{{state=JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{}}let filter='all';const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));const flat=()=>BATCH.courses.flatMap(c=>c.chapters.flatMap(ch=>ch.samples.map(q=>({{...q,course:c.name,major:ch.name}}))));function save(){{localStorage.setItem(KEY,JSON.stringify(state));stats()}}function result(uid,value){{state[uid]={{...(state[uid]||{{}}),result:value}};save();render()}}function field(uid,key,value){{state[uid]={{...(state[uid]||{{}}),[key]:value}};save()}}function stats(){{const rows=flat(),done=rows.filter(q=>state[q.source_uid]?.result).length,bad=rows.filter(q=>state[q.source_uid]?.result==='bad').length;document.getElementById('stats').textContent=`已检查 ${{done}}/${{rows.length}} · 问题 ${{bad}}`}}function imgs(xs){{return xs.map((x,i)=>`<img loading="lazy" src="${{esc(x)}}" alt="原书页${{i+1}}">`).join('')}}function card(q){{const r=state[q.source_uid]||{{}};if(filter==='pending'&&r.result||filter==='bad'&&r.result!=='bad')return'';const opts=Object.entries(q.options||{{}}).map(([k,v])=>`<div><b>${{esc(k)}}.</b> ${{esc(v)}}</div>`).join(''),ans=q.answer||{{}},uid=esc(q.source_uid);return `<article class="card"><div class="head"><b>${{esc(q.question_id)}} · p${{esc(q.page)}}</b><span class="uid">第${{q.stratum}}段 · ${{esc(q.minor_chapter)}}</span>${{q.quality_hold?'<b class="hold">已隔离</b>':''}}<a href="${{esc(q.viewer_url)}}" target="_blank">题库定位</a></div><div class="grid"><section class="bank"><div>${{esc(q.content).replace(/\\n/g,'<br>')}}</div><div class="opts">${{opts}}</div><div class="answer"><b>答案：</b>${{esc(ans.choice||'—')}}<br><b>解析：</b>${{esc(ans.explanation||'—')}}</div></section><section class="source">${{imgs(q.question_page_images)}}<details><summary>答案原页（${{q.answer_page_images.length}}）</summary>${{imgs(q.answer_page_images)}}</details></section></div><div class="review"><button class="${{r.result==='ok'?'active':''}}" data-action="result" data-result="ok" data-uid="${{uid}}">正常</button><button class="${{r.result==='bad'?'active bad':''}}" data-action="result" data-result="bad" data-uid="${{uid}}">有问题</button><select data-action="issue_type" data-uid="${{uid}}"><option value="">问题类型</option>${{['stem','options','answer','explanation','image','other'].map(x=>`<option ${{r.issue_type===x?'selected':''}}>${{x}}</option>`).join('')}}</select><textarea data-action="description" data-uid="${{uid}}" placeholder="问题描述">${{esc(r.description||'')}}</textarea></div></article>`}}function render(){{document.getElementById('root').innerHTML=BATCH.courses.map(c=>c.chapters.map(ch=>{{const body=ch.samples.map(card).join('');return body?`<section class="chapter"><h2>${{esc(c.name)}} · ${{esc(ch.name)}}（${{ch.sample_count}}/${{ch.population}}）</h2>${{body}}</section>`:''}}).join('')).join('');stats()}}const root=document.getElementById('root');root.addEventListener('click',event=>{{const el=event.target.closest('[data-action="result"]');if(el)result(el.dataset.uid,el.dataset.result)}});root.addEventListener('change',event=>{{const el=event.target.closest('[data-action="issue_type"]');if(el)field(el.dataset.uid,'issue_type',el.value)}});root.addEventListener('input',event=>{{const el=event.target.closest('[data-action="description"]');if(el)field(el.dataset.uid,'description',el.value)}});for(const id of ['all','pending','bad'])document.getElementById(id).onclick=()=>{{filter=id;document.querySelectorAll('.toolbar button').forEach(b=>b.classList.toggle('active',b.id===id));render()}};document.getElementById('export').onclick=()=>{{const items=flat().filter(q=>state[q.source_uid]?.result==='bad').map(q=>({{bank:'408',source_uid:q.source_uid,course:q.course,chapter:q.minor_chapter,question_id:q.question_id,page:q.page,issue_type:state[q.source_uid].issue_type||'other',description:state[q.source_uid].description||'章节抽检发现问题',snapshot:{{title:q.content,options:Object.entries(q.options||{{}}).map(([k,v])=>k+'. '+v),answer:(q.answer||{{}}).choice||'',explanation:(q.answer||{{}}).explanation||''}}}}));const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify({{round_id:BATCH.round_id,items}},null,2)],{{type:'application/json'}}));a.download='chapter-audit-issues-'+BATCH.round_id+'.json';a.click()}};render();</script></body></html>'''


def write_batch(per_chapter: int, round_id: str, json_path: Path, html_path: Path) -> dict[str, Any]:
    batch = build_batch(per_chapter, round_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(json_path, batch, indent=2, ensure_ascii=False)
    html_path.write_text(render_html(batch), encoding="utf-8")
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 408 每章分层抽检批次")
    parser.add_argument("--per-chapter", type=int, default=5)
    parser.add_argument("--round", dest="round_id", default=date.today().isoformat())
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    args = parser.parse_args()
    batch = write_batch(args.per_chapter, args.round_id, args.json, args.html)
    summary = batch["summary"]
    print(f"wrote {args.json}")
    print(f"wrote {args.html}")
    print(f"round={batch['round_id']} chapters={summary['major_chapters']} sampled={summary['sampled']}/{summary['choice_population']} held_in_sample={summary['held_in_sample']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
