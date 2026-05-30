"""pixel-watermark-cleaner desktop app (Tkinter shell).

A lightweight "Paint-style" window: open an image, brush or box over the
watermark, hit Clean to regenerate just that area, then Save. Undo/Redo,
original-preserving (Save As by default). All editing state and the pixel work
live in app_core / engine (headless, unit-tested); this file is only the widget
layer and imports Tkinter lazily so the module imports without a display.

Run:  pwc-app   (or  python app.py [image])
"""
import base64
import sys

import cv2
import numpy as np

import engine
import picker_core as pc
from app_core import SUPPORTED_READ, Document, load_image


def _photoimage(tk, bgr, scale):
    """Build a Tk PhotoImage from a BGR array, scaled (nearest, pixel-art)."""
    vw = max(1, int(round(bgr.shape[1] * scale)))
    vh = max(1, int(round(bgr.shape[0] * scale)))
    view = cv2.resize(bgr, (vw, vh), interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", view)
    if not ok:
        raise RuntimeError("failed to encode preview image")
    return tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))


class App:
    """The whole window. Construction requires a display; lazily imports tk."""

    def __init__(self, initial_path=None, max_view=(1100, 750)):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        self.tk = tk
        self.filedialog = filedialog
        self.messagebox = messagebox

        self.max_view = max_view
        self.doc = None
        self.scale = 1.0
        self.photo = None
        self.brush = 14
        self.tool = "brush"          # brush | box
        self._last = None            # last brush point, for smooth strokes
        self._box_start = None
        self._box_id = None

        self.root = tk.Tk()
        self.root.title("pixel-watermark-cleaner")

        self._build_toolbar(ttk)
        self.canvas = tk.Canvas(self.root, width=max_view[0], height=max_view[1],
                                bg="#202020", highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(side="top", fill="both", expand=True)
        self.status = tk.Label(self.root, anchor="w", text="Open an image to start.")
        self.status.pack(side="bottom", fill="x")

        self._bind()
        if initial_path:
            self._load(initial_path)

    # -- UI construction ---------------------------------------------------- #
    def _build_toolbar(self, ttk):
        bar = ttk.Frame(self.root, padding=4)
        bar.pack(side="top", fill="x")

        ttk.Button(bar, text="Open", command=self.on_open).pack(side="left")
        ttk.Button(bar, text="Save As", command=self.on_save).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        self.tool_var = self.tk.StringVar(value="brush")
        ttk.Radiobutton(bar, text="Brush", value="brush", variable=self.tool_var,
                        command=self._sync_tool).pack(side="left")
        ttk.Radiobutton(bar, text="Box", value="box", variable=self.tool_var,
                        command=self._sync_tool).pack(side="left")

        ttk.Label(bar, text="  Size").pack(side="left")
        self.brush_var = self.tk.IntVar(value=self.brush)
        ttk.Scale(bar, from_=2, to=80, variable=self.brush_var, length=110,
                  command=lambda _v: self._set_brush()).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        ttk.Label(bar, text="Engine").pack(side="left")
        self.method_var = self.tk.StringVar(value=engine.DEFAULT_METHOD)
        ttk.Combobox(bar, textvariable=self.method_var, width=7, state="readonly",
                     values=engine.available_methods()).pack(side="left")
        self.palette_var = self.tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Palette", variable=self.palette_var).pack(side="left")
        self.dilate_var = self.tk.IntVar(value=2)
        ttk.Label(bar, text="Grow").pack(side="left")
        self.tk.Spinbox(bar, from_=0, to=20, width=3,
                        textvariable=self.dilate_var).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        ttk.Button(bar, text="Clean ▶", command=self.on_clean).pack(side="left")
        ttk.Button(bar, text="Undo", command=self.on_undo).pack(side="left")
        ttk.Button(bar, text="Redo", command=self.on_redo).pack(side="left")
        ttk.Button(bar, text="Clear", command=self.on_clear).pack(side="left")

    def _bind(self):
        c = self.canvas
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<ButtonPress-3>", self.on_erase)
        c.bind("<B3-Motion>", self.on_erase)
        self.root.bind("<Control-z>", lambda e: self.on_undo())
        self.root.bind("<Control-y>", lambda e: self.on_redo())
        self.root.bind("<Control-s>", lambda e: self.on_save())
        self.root.bind("<Return>", lambda e: self.on_clean())
        self.root.bind("<bracketleft>", lambda e: self._nudge_brush(-2))
        self.root.bind("<bracketright>", lambda e: self._nudge_brush(+2))

    # -- small helpers ------------------------------------------------------ #
    def _sync_tool(self):
        self.tool = self.tool_var.get()

    def _set_brush(self):
        self.brush = int(self.brush_var.get())

    def _nudge_brush(self, d):
        self.brush = max(2, min(80, self.brush + d))
        self.brush_var.set(self.brush)

    def _to_image(self, cx, cy):
        return pc.canvas_to_image(cx, cy, self.scale, self.doc.w, self.doc.h)

    def _set_status(self, msg=None):
        if self.doc is None:
            self.status.config(text=msg or "Open an image to start.")
            return
        bits = [f"{self.doc.w}x{self.doc.h}", f"tool:{self.tool}",
                f"brush:{self.brush}", f"engine:{self.method_var.get()}"]
        if msg:
            bits.insert(0, msg)
        self.status.config(text="   ".join(bits))

    # -- load / render ------------------------------------------------------ #
    def _load(self, path):
        img = load_image(path)
        self.doc = Document(img, path=path)
        self.scale = pc.fit_scale(self.doc.w, self.doc.h, *self.max_view)
        vw, vh = pc.view_size(self.doc.w, self.doc.h, self.scale)
        self.canvas.config(width=vw, height=vh)
        self.redraw()
        self._set_status(f"opened {path}")

    def redraw(self):
        if self.doc is None:
            return
        self.photo = _photoimage(self.tk, self.doc.overlay(), self.scale)
        self.canvas.delete("img")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo, tags="img")
        self.canvas.tag_lower("img")

    # -- mouse: paint / box ------------------------------------------------- #
    def on_press(self, e):
        if self.doc is None:
            return
        if self.tool == "brush":
            ix, iy = self._to_image(e.x, e.y)
            self.doc.paint_circle(ix, iy, self.brush)
            self._last = (ix, iy)
            self.redraw()
        else:
            self._box_start = (e.x, e.y)
            self._box_id = self.canvas.create_rectangle(
                e.x, e.y, e.x, e.y, outline="#23d18b", width=2, dash=(4, 2))

    def on_drag(self, e):
        if self.doc is None:
            return
        if self.tool == "brush":
            ix, iy = self._to_image(e.x, e.y)
            if self._last:
                self.doc.paint_line(self._last[0], self._last[1], ix, iy, self.brush)
            else:
                self.doc.paint_circle(ix, iy, self.brush)
            self._last = (ix, iy)
            self.redraw()
        elif self._box_id is not None:
            self.canvas.coords(self._box_id, self._box_start[0],
                               self._box_start[1], e.x, e.y)

    def on_release(self, e):
        if self.doc is None:
            return
        if self.tool == "brush":
            self._last = None
        elif self._box_id is not None:
            self.canvas.delete(self._box_id)
            self._box_id = None
            ix0, iy0 = self._to_image(*self._box_start)
            ix1, iy1 = self._to_image(e.x, e.y)
            self.doc.paint_rect(ix0, iy0, ix1, iy1)
            self.redraw()

    def on_erase(self, e):
        if self.doc is None:
            return
        ix, iy = self._to_image(e.x, e.y)
        self.doc.erase_circle(ix, iy, self.brush)
        self.redraw()

    # -- toolbar actions ---------------------------------------------------- #
    def on_open(self):
        types = [("Images", " ".join("*" + e for e in SUPPORTED_READ)),
                 ("All files", "*.*")]
        path = self.filedialog.askopenfilename(filetypes=types)
        if path:
            self._load(path)

    def on_clean(self):
        if self.doc is None:
            return
        if not self.doc.has_mask():
            self._set_status("paint over the watermark first")
            return
        try:
            self.doc.apply_clean(method=self.method_var.get(),
                                 dilate=int(self.dilate_var.get()),
                                 palette_match=bool(self.palette_var.get()))
        except Exception as e:                       # e.g. LaMa weights download
            self.messagebox.showerror("Clean failed", str(e))
            return
        self.redraw()
        self._set_status("cleaned")

    def on_save(self):
        if self.doc is None:
            return
        import os
        src = self.doc.path or "cleaned.png"
        base, ext = os.path.splitext(os.path.basename(src))
        suggested = f"{base}_cleaned{ext or '.png'}"
        path = self.filedialog.asksaveasfilename(
            initialfile=suggested,
            defaultextension=ext or ".png",
            filetypes=[("PNG", "*.png"), ("All files", "*.*")])
        if not path:
            return
        if self.doc.path and os.path.abspath(path) == os.path.abspath(self.doc.path):
            if not self.messagebox.askyesno(
                    "Overwrite original?",
                    "That's the original file. Overwrite it anyway?"):
                return
        self.doc.save(path)
        self._set_status(f"saved {path}")

    def on_undo(self):
        if self.doc and self.doc.undo():
            self.redraw()
            self._set_status("undo")

    def on_redo(self):
        if self.doc and self.doc.redo():
            self.redraw()
            self._set_status("redo")

    def on_clear(self):
        if self.doc:
            self.doc.clear_mask()
            self.redraw()
            self._set_status("cleared selection")

    def run(self):
        self.root.mainloop()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    initial = args[0] if args else None
    try:
        App(initial).run()
    except ImportError as e:
        raise SystemExit(
            f"error: the app needs Tkinter ({e}). On Linux install it via your "
            "OS package manager: `sudo apt install python3-tk` (Debian/Ubuntu) "
            "or `sudo dnf install python3-tkinter` (Fedora). On macOS/Windows "
            "use the python.org installer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
