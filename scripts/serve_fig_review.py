# -*- coding: utf-8 -*-
"""
408 有图题审查 + 原地重裁服务。

用法（在 monorepo 或任意目录）:
  python apps/bank-408/scripts/serve_fig_review.py
  python apps/bank-408/scripts/serve_fig_review.py --port 8099

浏览器: http://127.0.0.1:8099/fig-review.html

- 静态: math-bank/*
- PDF 原页: /pdf/{ds|coa|os|net}/page_XXX.png
- API:
  GET  /api/items
  GET  /api/page-size?course=&page=
  POST /api/save-crop  JSON {course, page, id, chapter?, box:[x0,y0,x1,y1]}
  POST /api/regen-thumbs  (可选，重建页缩略图)
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]  # apps/bank-408
BANK = ROOT / "math-bank"
QA_DIR = ROOT / "output" / "qa"
PDF_ROOT = ROOT / "assets" / "pdf_images"
THUMB_DIR = BANK / "fig-review-pages"

COURSE_META = {
    "ds": ("数据结构", "data-ds"),
    "coa": ("计算机组成原理", "data-coa"),
    "os": ("操作系统", "data-os"),
    "net": ("计算机网络", "data-net"),
}
FIG_MARK = ("如下图", "下图所示", "右图", "左图", "如图", "下图", "见下图")

_lock = threading.Lock()


def _trim_expand(img, pad=4, border=12):
    import numpy as np
    from PIL import ImageOps

    g = np.array(img.convert("L"))
    m = g < 248
    if m.any():
        ys, xs = np.where(m)
        img = img.crop(
            (
                max(0, int(xs.min()) - pad),
                max(0, int(ys.min()) - pad),
                min(img.size[0], int(xs.max()) + pad + 1),
                min(img.size[1], int(ys.max()) + pad + 1),
            )
        )
    return ImageOps.expand(img, border, "white")


def looks_fig(q: dict) -> tuple[bool, str]:
    content = q.get("content") or ""
    opts = q.get("options") or {}
    ref = q.get("image_ref") or {}
    cropped = ref.get("cropped") if isinstance(ref, dict) else None
    exp = ""
    ans = q.get("answer")
    if isinstance(ans, dict):
        exp = ans.get("explanation") or ""
    m = re.search(r"(?:题目图片|题图)\s*[：:]\s*(\S+)", exp)
    if m and not cropped:
        cropped = m.group(1).strip()
    ok = bool(
        q.get("has_image")
        or cropped
        or any(x in content for x in FIG_MARK)
        or (
            isinstance(opts, dict)
            and opts
            and all("见图" in str(v) for v in opts.values())
        )
        or m
    )
    return ok, cropped or ""


def collect_items() -> list[dict]:
    items: list[dict] = []
    for code, (cname, stem) in COURSE_META.items():
        path = BANK / f"{stem}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for ch in data.get("chapters", []):
            ch_name = ch.get("name") or ""
            for q in ch.get("questions", []):
                ok, cropped = looks_fig(q)
                if not ok:
                    continue
                rel = (cropped or "").replace("\\", "/").lstrip("./")
                if rel and not rel.startswith("crops/"):
                    if "/" not in rel:
                        rel = f"crops/{code}/{rel}"
                page_raw = q.get("page")
                try:
                    page_i = int(page_raw) if page_raw is not None else None
                except (TypeError, ValueError):
                    page_i = None
                pdf = (
                    PDF_ROOT / code / f"page_{page_i:03d}.png"
                    if page_i is not None
                    else None
                )
                pdf_ok = bool(pdf) and pdf.exists()
                file_ok = bool(rel) and (BANK / rel).exists()
                opts = q.get("options") or {}
                opt_list = []
                if isinstance(opts, dict):
                    for k in sorted(opts.keys()):
                        opt_list.append({"k": k, "v": str(opts[k])})
                ans = q.get("answer")
                choice = ans.get("choice") if isinstance(ans, dict) else ans
                box = None
                if isinstance(q.get("image_ref"), dict):
                    box = q["image_ref"].get("box")
                items.append(
                    {
                        "uid": f"{code}:{page_i}:{q.get('id')}:{ch_name}",
                        "course": code,
                        "course_name": cname,
                        "chapter": ch_name,
                        "id": q.get("id"),
                        "type": q.get("type"),
                        "page": page_i,
                        "topic": q.get("topic_title") or "",
                        "content": (q.get("content") or "").strip(),
                        "options": opt_list,
                        "answer": choice,
                        "image": rel,
                        "file_ok": file_ok,
                        "pdf_ok": pdf_ok,
                        "pdf_url": f"/pdf/{code}/page_{page_i:03d}.png"
                        if pdf_ok and page_i is not None
                        else "",
                        "page_thumb": f"fig-review-pages/{code}/page_{page_i:03d}.jpg"
                        if pdf_ok and page_i is not None
                        else "",
                        "bbox": q.get("bbox"),
                        "crop_box": box,
                        "image_note": (q.get("image_ref") or {}).get("note")
                        if isinstance(q.get("image_ref"), dict)
                        else "",
                    }
                )
    order = {"ds": 0, "coa": 1, "os": 2, "net": 3}
    items.sort(
        key=lambda x: (
            order.get(x["course"], 9),
            x.get("page") or 0,
            str(x.get("id") or ""),
        )
    )
    return items


def write_course_data(course: str, data: dict) -> None:
    cname, stem = COURSE_META[course]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (BANK / f"{stem}.json").write_text(payload, encoding="utf-8")
    (BANK / f"{stem}.js").write_text(
        f"// auto-generated from {stem}.json\n"
        "window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {};\n"
        f'window.__COURSE_CACHE__["{cname}"] = ' + payload + ";\n",
        encoding="utf-8",
    )
    gz = BANK / f"{stem}.json.gz"
    if gz.exists():
        with gzip.open(gz, "wt", encoding="utf-8") as f:
            f.write(payload)


def find_question(data: dict, page: int, qid: str, chapter: str | None) -> dict | None:
    hits = []
    for ch in data.get("chapters", []):
        if chapter and (ch.get("name") or "") != chapter:
            # still allow match without chapter if unique
            pass
        for q in ch.get("questions", []):
            if int(q.get("page") or -1) == int(page) and str(q.get("id")) == str(qid):
                if chapter and (ch.get("name") or "") == chapter:
                    return q
                hits.append(q)
    if len(hits) == 1:
        return hits[0]
    if chapter:
        for ch in data.get("chapters", []):
            if (ch.get("name") or "") != chapter:
                continue
            for q in ch.get("questions", []):
                if int(q.get("page") or -1) == int(page) and str(q.get("id")) == str(
                    qid
                ):
                    return q
    return hits[0] if hits else None


def ensure_img_line(exp: str, rel: str) -> str:
    line = f"题目图片：{rel}"
    exp = (exp or "").rstrip()
    lines = [
        ln
        for ln in exp.splitlines()
        if not ln.strip().startswith("题目图片") and not ln.strip().startswith("题图")
    ]
    body = "\n".join(lines).rstrip()
    return (body + "\n" + line + "\n") if body else (line + "\n")


def save_crop(
    course: str,
    page: int,
    qid: str,
    box: list[float],
    chapter: str | None = None,
    do_trim: bool = True,
) -> dict[str, Any]:
    from PIL import Image

    if course not in COURSE_META:
        raise ValueError(f"unknown course {course}")
    if len(box) != 4:
        raise ValueError("box must be [x0,y0,x1,y1]")

    pdf = PDF_ROOT / course / f"page_{int(page):03d}.png"
    if not pdf.exists():
        raise FileNotFoundError(f"missing pdf page: {pdf}")

    x0, y0, x1, y1 = [float(v) for v in box]
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0

    with _lock:
        page_img = Image.open(pdf).convert("RGB")
        w, h = page_img.size
        ix0 = max(0, min(w - 1, int(round(x0))))
        iy0 = max(0, min(h - 1, int(round(y0))))
        ix1 = max(ix0 + 1, min(w, int(round(x1))))
        iy1 = max(iy0 + 1, min(h, int(round(y1))))
        if ix1 - ix0 < 8 or iy1 - iy0 < 8:
            raise ValueError("selection too small")

        crop = page_img.crop((ix0, iy0, ix1, iy1))
        if do_trim:
            crop = _trim_expand(crop)
        else:
            from PIL import ImageOps

            crop = ImageOps.expand(crop, 12, "white")

        _, stem = COURSE_META[course]
        data = json.loads((BANK / f"{stem}.json").read_text(encoding="utf-8"))
        q = find_question(data, int(page), str(qid), chapter)
        if not q:
            raise KeyError(f"question not found: {course} p{page} {qid}")

        # keep existing path if any
        old_rel = ""
        if isinstance(q.get("image_ref"), dict):
            old_rel = (q["image_ref"].get("cropped") or "").replace("\\", "/")
        rel = old_rel or f"crops/{course}/page_{int(page):03d}_{qid}.png"
        if not rel.startswith("crops/"):
            rel = f"crops/{course}/{Path(rel).name}"

        out = BANK / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        crop.save(out, "PNG")

        q["has_image"] = True
        q["image_ref"] = {
            "page": int(page),
            "note": "题目配图（审查页原地重裁）",
            "cropped": rel,
            "box": [ix0, iy0, ix1, iy1],
        }
        ans = q.get("answer")
        if isinstance(ans, dict):
            ans["explanation"] = ensure_img_line(ans.get("explanation") or "", rel)
        elif ans is None:
            q["answer"] = {
                "choice": None,
                "explanation": ensure_img_line("", rel),
            }

        write_course_data(course, data)

        # refresh fig-review-data.json snapshot
        try:
            items = collect_items()
            (QA_DIR / "fig-review-data.json").write_text(
                json.dumps(
                    {"generated": True, "count": len(items), "items": items},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            print("warn: refresh fig-review-data failed", e, file=sys.stderr)

    return {
        "ok": True,
        "image": rel,
        "box": [ix0, iy0, ix1, iy1],
        "size": [crop.size[0], crop.size[1]],
        "bytes": out.stat().st_size,
        "url": f"/{rel}?t={out.stat().st_mtime_ns}",
    }


def ensure_html() -> None:
    """If fig-review.html missing, tell user to open after first serve (we ship HTML)."""
    html = QA_DIR / "fig-review.html"
    if not html.exists():
        print("missing fig-review.html — run will write bundled page on first start")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BANK), **kwargs)

    def log_message(self, format, *args):  # noqa: A003
        sys.stderr.write("[fig-review] " + (format % args) + "\n")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, obj: Any):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        text = raw.decode("utf-8-sig") if raw else "{}"
        return json.loads(text or "{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/api/ping", "/api/health"):
            self._json(200, {"ok": True, "bank": str(BANK)})
            return

        if path == "/api/items":
            try:
                items = collect_items()
                self._json(200, {"count": len(items), "items": items})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/api/page-size":
            qs = parse_qs(parsed.query)
            course = (qs.get("course") or [""])[0]
            page = (qs.get("page") or [""])[0]
            try:
                from PIL import Image

                pdf = PDF_ROOT / course / f"page_{int(page):03d}.png"
                if not pdf.exists():
                    self._json(404, {"ok": False, "error": "page not found"})
                    return
                im = Image.open(pdf)
                self._json(200, {"ok": True, "width": im.size[0], "height": im.size[1]})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if path.startswith("/pdf/"):
            # /pdf/{course}/page_XXX.png
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "pdf" and parts[1] in COURSE_META:
                f = PDF_ROOT / parts[1] / parts[2]
                if f.exists() and f.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                    data = f.read_bytes()
                    ctype = "image/png" if f.suffix.lower() == ".png" else "image/jpeg"
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "private, max-age=60")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.send_error(404, "pdf page not found")
            return

        # no-cache for review html/json
        if path in ("/fig-review.html", "/fig-review-data.json") or path.endswith(
            ".html"
        ):
            return self._serve_nocache(path.lstrip("/"))

        return super().do_GET()

    def _serve_nocache(self, rel: str):
        f = QA_DIR / rel
        if not f.is_file():
            f = BANK / rel
        if not f.exists() or not f.is_file():
            self.send_error(404)
            return
        data = f.read_bytes()
        ctype = "text/html; charset=utf-8"
        if rel.endswith(".json"):
            ctype = "application/json; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/save-crop":
            try:
                body = self._read_json()
                result = save_crop(
                    course=str(body.get("course") or ""),
                    page=int(body["page"]),
                    qid=str(body.get("id") or ""),
                    box=list(body.get("box") or []),
                    chapter=body.get("chapter") or None,
                    do_trim=bool(body.get("trim", True)),
                )
                self._json(200, result)
            except Exception as e:
                self._json(400, {"ok": False, "error": str(e)})
            return

        if path == "/api/ping":
            self._json(200, {"ok": True, "bank": str(BANK)})
            return

        self._json(404, {"ok": False, "error": "not found"})


def main():
    ap = argparse.ArgumentParser(description="408 fig review + in-place crop server")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    if not BANK.exists():
        raise SystemExit(f"math-bank not found: {BANK}")

    # refresh items snapshot
    items = collect_items()
    (BANK / "fig-review-data.json").write_text(
        json.dumps(
            {"generated": True, "count": len(items), "items": items},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"items: {len(items)}")
    print(f"bank:  {BANK}")
    print(f"pdf:   {PDF_ROOT}")

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/fig-review.html"
    print(f"serve: {url}")
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
