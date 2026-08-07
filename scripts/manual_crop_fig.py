# -*- coding: utf-8 -*-
"""
有图选择题 — 手动框选裁图工具

用法（在 monorepo 下）:
  python apps/bank-408/scripts/manual_crop_fig.py
  python apps/bank-408/scripts/manual_crop_fig.py --course ds
  python apps/bank-408/scripts/manual_crop_fig.py --start 213

操作:
  左键拖拽  框选裁剪区域
  S / 保存  写入 crop + 更新 data-*.json/js
  N / →     下一题
  P / ←     上一题
  R         重置框选
  滚轮      缩放页面
  中键拖    平移页面
  Esc       退出
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:
    print("需要 tkinter")
    sys.exit(1)

from PIL import Image, ImageTk, ImageOps
import numpy as np

ROOT = Path(__file__).resolve().parents[1]  # apps/bank-408
BANK = ROOT / "math-bank"
PDF_ROOT = ROOT / "assets" / "pdf_images"

COURSE_META = {
    "ds": ("数据结构", "data-ds"),
    "coa": ("计算机组成原理", "data-coa"),
    "os": ("操作系统", "data-os"),
    "net": ("计算机网络", "data-net"),
}

FIG_MARK = ("如下图", "下图所示", "右图", "左图", "如图", "下图")


def list_fig_choices(course: str) -> list[dict]:
    stem = COURSE_META[course][1]
    data = json.loads((BANK / f"{stem}.json").read_text(encoding="utf-8"))
    items = []
    for ch in data["chapters"]:
        for q in ch["questions"]:
            if q.get("type") != "选择题":
                continue
            content = q.get("content") or ""
            opts = q.get("options") or {}
            pure = (
                isinstance(opts, dict)
                and opts
                and all("见图" in str(v) for v in opts.values())
            )
            has_fig = (
                q.get("has_image")
                or (q.get("image_ref") or {}).get("cropped")
                or any(x in content for x in FIG_MARK)
                or pure
            )
            if not has_fig:
                continue
            items.append(
                {
                    "course": course,
                    "page": int(q["page"]),
                    "id": q["id"],
                    "content": content.replace("\n", " ")[:80],
                    "pure": pure,
                    "ref": (q.get("image_ref") or {}).get("cropped") or "",
                    "bbox": q.get("bbox"),
                    "chapter": ch.get("name") or "",
                }
            )
    return items, data


def trim_expand(img: Image.Image, pad=4, border=12) -> Image.Image:
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


class CropApp:
    def __init__(self, course: str = "ds", start_page: int | None = None):
        self.course = course
        self.course_name, self.stem = COURSE_META[course]
        self.items, self.data = list_fig_choices(course)
        if not self.items:
            raise SystemExit(f"{course} 没有有图选择题")

        self.idx = 0
        if start_page is not None:
            for i, it in enumerate(self.items):
                if it["page"] >= start_page:
                    self.idx = i
                    break

        self.root = tk.Tk()
        self.root.title("有图选择题 · 手动裁图")
        self.root.geometry("1280x900")
        self.root.minsize(900, 600)

        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.page_img: Image.Image | None = None
        self.tk_img = None
        self.drag_start = None
        self.sel_rect = None  # canvas coords
        self.sel_box_page = None  # page pixel coords (x0,y0,x1,y1)
        self.pan_start = None
        self.space_down = False
        self.do_trim = tk.BooleanVar(value=True)
        self.auto_next = tk.BooleanVar(value=False)  # 默认不自动跳，避免只落最后一题
        self._fit_pending = False
        self.dirty = False  # 有未保存框选
        self.saved_this_session: set[tuple[int, str]] = set()

        self._build_ui()
        self.root.bind("<KeyPress>", self._on_key)
        self.root.bind("<KeyRelease>", self._on_key_up)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # 等窗口真正布局完再载入，避免 canvas 宽高=1
        self.root.after(80, self._load_item)

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill=tk.X)

        self.info = ttk.Label(top, text="", font=("Microsoft YaHei UI", 10))
        self.info.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Checkbutton(top, text="自动去白边", variable=self.do_trim).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Checkbutton(
            top, text="保存后跳下一题", variable=self.auto_next
        ).pack(side=tk.RIGHT, padx=4)
        ttk.Button(top, text="保存并下一题 (Enter)", command=self.save_and_next).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(top, text="保存 (S)", command=self.save).pack(side=tk.RIGHT, padx=2)
        ttk.Button(top, text="下一题 (N)", command=self.next_item).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(top, text="上一题 (P)", command=self.prev_item).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(top, text="对准本题 (F)", command=self.fit_question).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(top, text="整页适应", command=self.fit_page).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(top, text="重置框 (R)", command=self.reset_sel).pack(
            side=tk.RIGHT, padx=2
        )

        mid = ttk.Frame(self.root)
        mid.pack(fill=tk.BOTH, expand=True)

        # left: canvas
        self.canvas = tk.Canvas(mid, bg="#1e1e1e", cursor="crosshair", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_ldown)
        self.canvas.bind("<B1-Motion>", self._on_ldrag)
        self.canvas.bind("<ButtonRelease-1>", self._on_lup)
        self.canvas.bind("<ButtonPress-2>", self._on_mdown)
        self.canvas.bind("<B2-Motion>", self._on_mdrag)
        self.canvas.bind("<ButtonRelease-2>", self._on_mup)
        self.canvas.bind("<ButtonPress-3>", self._on_mdown)  # 右键也平移
        self.canvas.bind("<B3-Motion>", self._on_mdrag)
        self.canvas.bind("<ButtonRelease-3>", self._on_mup)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom(1.12, e.x, e.y))
        self.canvas.bind("<Button-5>", lambda e: self._zoom(0.9, e.x, e.y))

        # right: preview + list
        right = ttk.Frame(mid, width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)

        ttk.Label(right, text="裁剪预览", font=("Microsoft YaHei UI", 9, "bold")).pack(
            anchor=tk.W, padx=6, pady=(8, 2)
        )
        self.preview_label = ttk.Label(right)
        self.preview_label.pack(padx=6, pady=4)

        self.status = ttk.Label(right, text="", wraplength=280, justify=tk.LEFT)
        self.status.pack(anchor=tk.W, padx=6, pady=4)

        ttk.Label(right, text="题目列表（双击跳转）").pack(anchor=tk.W, padx=6, pady=(12, 2))
        self.listbox = tk.Listbox(right, font=("Consolas", 9), height=20)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        for i, it in enumerate(self.items):
            mark = "✓" if it["ref"] else "·"
            self.listbox.insert(
                tk.END, f"{mark} {it['id']} p{it['page']} {it['content'][:28]}"
            )
        self.listbox.bind("<Double-Button-1>", self._on_list_jump)

        bot = ttk.Label(
            self.root,
            text="左键框选 → S只保存 / Enter保存并下一题 · 有未保存框选时翻题会提示 · 右键平移 · 滚轮缩放 · F对准",
            font=("Microsoft YaHei UI", 8),
            foreground="#666",
        )
        bot.pack(fill=tk.X, padx=8, pady=4)

        self.save_banner = tk.Label(
            self.root,
            text="",
            font=("Microsoft YaHei UI", 10, "bold"),
            fg="#1b5e20",
            bg="#c8e6c9",
            pady=4,
        )
        # 默认隐藏，保存成功时显示

    def _canvas_size(self) -> tuple[int, int]:
        self.root.update_idletasks()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 50:
            cw = max(self.root.winfo_width() - 320, 800)
        if ch < 50:
            ch = max(self.root.winfo_height() - 100, 600)
        return cw, ch

    def _focus_region(self) -> tuple[float, float, float, float]:
        """本题应优先显示的页面区域（page 像素）。"""
        assert self.page_img is not None
        pw, ph = self.page_img.size
        it = self.items[self.idx]
        bb = it.get("bbox")
        if bb:
            x0, y0, x1, y1 = [float(v) for v in bb]
            # 右图题：向右扩；下图题：向下扩
            pad_x, pad_y_top, pad_y_bot = 40, 30, 180
            if it.get("pure"):
                pad_y_bot = 220
            # 右图通常在题干右侧
            x1 = max(x1, min(pw - 20, x1 + 280))
            x0 = max(0, x0 - pad_x)
            y0 = max(0, y0 - pad_y_top)
            y1 = min(ph, y1 + pad_y_bot)
            # 至少覆盖一定高度，方便框图
            if y1 - y0 < 280:
                y1 = min(ph, y0 + 320)
            return x0, y0, x1, y1
        # 无 bbox：整页
        return 0, 0, pw, ph

    def fit_question(self):
        """把本题区域放大铺满画布（默认视图）。"""
        if self.page_img is None:
            return
        cw, ch = self._canvas_size()
        x0, y0, x1, y1 = self._focus_region()
        rw, rh = max(1.0, x1 - x0), max(1.0, y1 - y0)
        margin = 16
        self.scale = min((cw - margin * 2) / rw, (ch - margin * 2) / rh)
        self.scale = max(0.25, min(2.8, self.scale))
        # 区域中心对准画布中心
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        self.offset_x = cw / 2 - cx * self.scale
        self.offset_y = ch / 2 - cy * self.scale
        self._redraw()

    def fit_page(self):
        """整页适应窗口。"""
        if self.page_img is None:
            return
        cw, ch = self._canvas_size()
        pw, ph = self.page_img.size
        margin = 12
        self.scale = min((cw - margin * 2) / pw, (ch - margin * 2) / ph)
        self.scale = max(0.15, min(2.0, self.scale))
        self.offset_x = (cw - pw * self.scale) / 2
        self.offset_y = (ch - ph * self.scale) / 2
        self._redraw()

    def _on_canvas_configure(self, _e=None):
        # 首次有有效尺寸时对准本题
        if self._fit_pending and self.page_img is not None:
            cw, ch = self._canvas_size()
            if cw > 100 and ch > 100:
                self._fit_pending = False
                self.fit_question()

    def _load_item(self):
        it = self.items[self.idx]
        pdf = PDF_ROOT / self.course / f"page_{it['page']:03d}.png"
        if not pdf.exists():
            messagebox.showerror("缺少页面", str(pdf))
            return
        self.page_img = Image.open(pdf).convert("RGB")
        self.sel_rect = None
        self.sel_box_page = None
        self._fit_pending = True

        self.dirty = False
        pure = "【纯图选项】" if it["pure"] else ""
        sess = " ★本会话已存" if (it["page"], it["id"]) in self.saved_this_session else ""
        self.info.config(
            text=f"[{self.idx+1}/{len(self.items)}] {it['id']}  p{it['page']}  "
            f"{pure}{sess}  {it['content'][:50]}"
        )
        self.status.config(
            text=f"当前配图: {it['ref'] or '（无）'}\n"
            f"章节: {it['chapter'][:40]}\n"
            f"本会话已保存 {len(self.saved_this_session)} 题\n"
            f"框选后按 S 保存（默认不跳题）\n"
            f"或 Enter = 保存并下一题"
        )
        self._refresh_list_marks()
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self.idx)
        self.listbox.see(self.idx)

        # 立即尝试对准；若 canvas 尚未布局好，等 Configure
        self.root.update_idletasks()
        cw, ch = self._canvas_size()
        if cw > 100 and ch > 100:
            self._fit_pending = False
            self.fit_question()
        else:
            self.scale = 0.8
            self.offset_x = 20
            self.offset_y = 20
            self._redraw()
            self.root.after(120, self.fit_question)

        self._show_existing_preview()
        self._hide_save_banner()

    def _refresh_list_marks(self):
        self.listbox.delete(0, tk.END)
        for i, it in enumerate(self.items):
            if (it["page"], it["id"]) in self.saved_this_session:
                mark = "★"
            elif it["ref"]:
                mark = "✓"
            else:
                mark = "·"
            self.listbox.insert(
                tk.END, f"{mark} {it['id']} p{it['page']} {it['content'][:28]}"
            )

    def _hide_save_banner(self):
        try:
            self.save_banner.pack_forget()
        except Exception:
            pass

    def _show_existing_preview(self):
        it = self.items[self.idx]
        ref = it["ref"]
        if ref and (BANK / ref).exists():
            img = Image.open(BANK / ref)
            img.thumbnail((260, 200))
            self._prev_tk = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self._prev_tk)
        else:
            self.preview_label.config(image="", text="（尚无裁图）")

    def _page_to_canvas(self, x, y):
        return x * self.scale + self.offset_x, y * self.scale + self.offset_y

    def _canvas_to_page(self, x, y):
        return (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale

    def _redraw(self):
        if self.page_img is None:
            return
        self.canvas.delete("all")
        w = max(1, int(self.page_img.size[0] * self.scale))
        h = max(1, int(self.page_img.size[1] * self.scale))
        # 限制超大位图，避免卡顿
        if w * h > 25_000_000:
            factor = (25_000_000 / (w * h)) ** 0.5
            w, h = max(1, int(w * factor)), max(1, int(h * factor))
        disp = self.page_img.resize((w, h), Image.Resampling.BILINEAR)
        self.tk_img = ImageTk.PhotoImage(disp)
        self.canvas.create_image(
            self.offset_x, self.offset_y, anchor=tk.NW, image=self.tk_img
        )

        # 浅蓝：题目 bbox；青绿：建议关注区
        it = self.items[self.idx]
        if it.get("bbox"):
            x0, y0, x1, y1 = it["bbox"]
            c0 = self._page_to_canvas(x0, y0)
            c1 = self._page_to_canvas(x1, y1)
            self.canvas.create_rectangle(
                *c0, *c1, outline="#4fc3f7", width=1, dash=(4, 3)
            )
        fx0, fy0, fx1, fy1 = self._focus_region()
        self.canvas.create_rectangle(
            *self._page_to_canvas(fx0, fy0),
            *self._page_to_canvas(fx1, fy1),
            outline="#66bb6a",
            width=1,
            dash=(6, 4),
        )

        if self.sel_rect:
            self.canvas.create_rectangle(
                *self.sel_rect, outline="#ff5252", width=2, fill="", dash=()
            )
            x0, y0, x1, y1 = self.sel_rect
            self.canvas.create_text(
                min(x0, x1) + 4,
                min(y0, y1) - 14,
                anchor=tk.NW,
                text=self._sel_label(),
                fill="#ff8a80",
                font=("Consolas", 9),
            )

    def _sel_label(self) -> str:
        if not self.sel_box_page:
            return ""
        x0, y0, x1, y1 = self.sel_box_page
        return f"({int(x0)},{int(y0)})-({int(x1)},{int(y1)})  {int(x1-x0)}×{int(y1-y0)}"

    def _on_ldown(self, e):
        # 空格按下时左键改为平移
        if self.space_down:
            self._on_mdown(e)
            return
        self.drag_start = (e.x, e.y)
        self.sel_rect = (e.x, e.y, e.x, e.y)
        self.pan_start = None

    def _on_ldrag(self, e):
        if self.space_down or self.pan_start:
            self._on_mdrag(e)
            return
        if not self.drag_start:
            return
        x0, y0 = self.drag_start
        self.sel_rect = (x0, y0, e.x, e.y)
        self._update_sel_page()
        self._redraw()

    def _on_lup(self, e):
        if self.space_down or (self.pan_start and not self.drag_start):
            self.pan_start = None
            return
        if not self.drag_start:
            return
        x0, y0 = self.drag_start
        self.sel_rect = (x0, y0, e.x, e.y)
        self._update_sel_page()
        self.drag_start = None
        if self.sel_box_page:
            self.dirty = True
        self._redraw()
        self._update_live_preview()

    def _update_sel_page(self):
        if not self.sel_rect or self.page_img is None:
            return
        x0, y0, x1, y1 = self.sel_rect
        px0, py0 = self._canvas_to_page(min(x0, x1), min(y0, y1))
        px1, py1 = self._canvas_to_page(max(x0, x1), max(y0, y1))
        w, h = self.page_img.size
        px0, py0 = max(0, px0), max(0, py0)
        px1, py1 = min(w, px1), min(h, py1)
        if px1 - px0 < 5 or py1 - py0 < 5:
            self.sel_box_page = None
            return
        self.sel_box_page = (px0, py0, px1, py1)

    def _update_live_preview(self):
        if not self.sel_box_page or self.page_img is None:
            return
        x0, y0, x1, y1 = [int(v) for v in self.sel_box_page]
        crop = self.page_img.crop((x0, y0, x1, y1))
        if self.do_trim.get():
            crop = trim_expand(crop)
        crop.thumbnail((280, 220))
        self._prev_tk = ImageTk.PhotoImage(crop)
        self.preview_label.config(image=self._prev_tk)

    def _on_mdown(self, e):
        self.pan_start = (e.x, e.y, self.offset_x, self.offset_y)
        self.canvas.config(cursor="fleur")

    def _on_mdrag(self, e):
        if not self.pan_start:
            return
        sx, sy, ox, oy = self.pan_start
        self.offset_x = ox + (e.x - sx)
        self.offset_y = oy + (e.y - sy)
        self._redraw()

    def _on_mup(self, _e=None):
        self.pan_start = None
        if not self.space_down:
            self.canvas.config(cursor="crosshair")

    def _on_wheel(self, e):
        factor = 1.12 if e.delta > 0 else 0.9
        self._zoom(factor, e.x, e.y)

    def _zoom(self, factor, cx, cy):
        px, py = self._canvas_to_page(cx, cy)
        self.scale = max(0.2, min(3.5, self.scale * factor))
        nx, ny = self._page_to_canvas(px, py)
        self.offset_x += cx - nx
        self.offset_y += cy - ny
        self._redraw()

    def _on_key(self, e):
        k = e.keysym.lower()
        if k in ("space",):
            self.space_down = True
            self.canvas.config(cursor="fleur")
            return
        if k == "s":
            self.save(go_next=False)
        elif k in ("return", "kp_enter"):
            self.save_and_next()
        elif k in ("n", "right"):
            self.next_item()
        elif k in ("p", "left"):
            self.prev_item()
        elif k == "r":
            self.reset_sel()
        elif k == "f":
            self.fit_question()
        elif k == "g":
            self.fit_page()
        elif k == "escape":
            self._on_close()

    def _on_key_up(self, e):
        if e.keysym.lower() == "space":
            self.space_down = False
            self.canvas.config(cursor="crosshair")
            self.pan_start = None

    def reset_sel(self):
        self.sel_rect = None
        self.sel_box_page = None
        self.dirty = False
        self._redraw()
        self._show_existing_preview()

    def _confirm_leave(self) -> bool:
        """有未保存框选时询问。True=可以离开。"""
        if not self.dirty or not self.sel_box_page:
            return True
        it = self.items[self.idx]
        ans = messagebox.askyesnocancel(
            "未保存的框选",
            f"{it['id']} p{it['page']} 有未保存的框选。\n\n"
            f"是 = 先保存再走\n否 = 丢弃框选\n取消 = 留下",
        )
        if ans is None:
            return False
        if ans:
            return self.save(go_next=False)
        self.dirty = False
        return True

    def next_item(self):
        if not self._confirm_leave():
            return
        if self.idx < len(self.items) - 1:
            self.idx += 1
            self._load_item()

    def prev_item(self):
        if not self._confirm_leave():
            return
        if self.idx > 0:
            self.idx -= 1
            self._load_item()

    def _on_list_jump(self, _e):
        sel = self.listbox.curselection()
        if not sel:
            return
        if not self._confirm_leave():
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(self.idx)
            return
        self.idx = sel[0]
        self._load_item()

    def save_and_next(self):
        if self.save(go_next=False):
            if self.idx < len(self.items) - 1:
                self.idx += 1
                self._load_item()

    def save(self, go_next: bool | None = None) -> bool:
        if go_next is None:
            go_next = self.auto_next.get()
        if not self.sel_box_page or self.page_img is None:
            messagebox.showwarning("未框选", "请先在页面上拖拽框选区域，再按 S 保存")
            return False
        it = self.items[self.idx]
        x0, y0, x1, y1 = [int(v) for v in self.sel_box_page]
        crop = self.page_img.crop((x0, y0, x1, y1))
        if self.do_trim.get():
            crop = trim_expand(crop)
        else:
            crop = ImageOps.expand(crop, 12, "white")

        rel = f"crops/{self.course}/page_{it['page']:03d}_{it['id']}.png"
        out = BANK / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        crop.save(out, "PNG")

        pure = it["pure"]
        note = "选项配图（A-D·手动）" if pure else "题目配图（手动框选）"
        for ch in self.data["chapters"]:
            for q in ch["questions"]:
                if q.get("page") == it["page"] and q.get("id") == it["id"]:
                    q["has_image"] = True
                    q["image_ref"] = {
                        "page": it["page"],
                        "note": note,
                        "cropped": rel,
                        "box": [x0, y0, x1, y1],
                    }
        payload = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        json_path = BANK / f"{self.stem}.json"
        js_path = BANK / f"{self.stem}.js"
        json_path.write_text(payload, encoding="utf-8")
        js_path.write_text(
            f"// auto-generated from {self.stem}.json\n"
            "window.__COURSE_CACHE__ = window.__COURSE_CACHE__ || {};\n"
            f'window.__COURSE_CACHE__["{self.course_name}"] = '
            + payload
            + ";\n",
            encoding="utf-8",
        )

        it["ref"] = rel
        self.dirty = False
        self.saved_this_session.add((it["page"], it["id"]))
        self._refresh_list_marks()
        self.listbox.selection_set(self.idx)
        self.listbox.see(self.idx)

        msg = (
            f"✓ 已写入磁盘  {it['id']} p{it['page']}  "
            f"{crop.size[0]}×{crop.size[1]}  →  {rel}  "
            f"（本会话共 {len(self.saved_this_session)} 题）"
        )
        self.status.config(
            text=f"已保存 {rel}\n尺寸 {crop.size[0]}×{crop.size[1]}\n"
            f"框 {x0},{y0},{x1},{y1}\n"
            f"本会话已存 {len(self.saved_this_session)} 题\n"
            f"json mtime 已更新"
        )
        self.info.config(
            text=f"[{self.idx+1}/{len(self.items)}] {it['id']}  p{it['page']}  ★已保存  "
            f"{it['content'][:45]}"
        )
        self._show_existing_preview()
        self._flash_saved(msg)

        if go_next and self.idx < len(self.items) - 1:
            self.root.after(400, self._go_next_after_save)
        return True

    def _go_next_after_save(self):
        if self.idx < len(self.items) - 1:
            self.idx += 1
            self._load_item()

    def _flash_saved(self, text: str):
        self.save_banner.config(text=text)
        try:
            self.save_banner.pack_forget()
        except Exception:
            pass
        self.save_banner.pack(fill=tk.X, side=tk.TOP)
        self.root.after(2500, self._hide_save_banner)

    def _on_close(self):
        if self.dirty and self.sel_box_page:
            if not self._confirm_leave():
                return
        n = len(self.saved_this_session)
        if n:
            messagebox.showinfo(
                "退出",
                f"本会话共保存 {n} 题到本机。\n"
                f"若要上云，请跟助手说「同步云」。\n\n"
                f"已存: "
                + ", ".join(f"{p}-{i}" for p, i in sorted(self.saved_this_session)[:20])
                + ("…" if n > 20 else ""),
            )
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    ap = argparse.ArgumentParser(description="有图选择题手动裁图")
    ap.add_argument(
        "--course",
        default="ds",
        choices=list(COURSE_META.keys()),
        help="科目: ds/coa/os/net",
    )
    ap.add_argument("--start", type=int, default=None, help="从某页开始")
    args = ap.parse_args()
    CropApp(course=args.course, start_page=args.start).run()


if __name__ == "__main__":
    main()
