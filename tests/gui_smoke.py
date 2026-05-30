#!/usr/bin/env python3
"""Real-Tkinter smoke test for the picker, run under a virtual framebuffer.

This is intentionally *not* a pytest module: it needs a display (Xvfb in CI) and
drives actual Tk widgets/events, which doesn't belong in the headless unit-test
run. CI invokes it as ``xvfb-run python tests/gui_smoke.py``. It exits non-zero
on any failure.

It verifies the parts unit tests can't reach:
  * _to_display_bgr flattens gray / BGR / BGRA to HxWx3 uint8
  * _photoimage builds a correctly-scaled real Tk PhotoImage
  * a scripted mouse drag + Enter returns the drawn region
  * Escape cancels to an empty result
"""
import pathlib
import sys

import cv2
import numpy as np
import tkinter as tk

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import picker  # noqa: E402


def check_render():
    gray = np.full((10, 10), 128, np.uint8)
    bgr = np.zeros((10, 10, 3), np.uint8)
    bgr[...] = (200, 120, 40)
    bgra = np.zeros((10, 10, 4), np.uint8)
    bgra[:, :, :3] = (255, 0, 255)
    bgra[:, :, 3] = 128
    for name, im in [("gray", gray), ("bgr", bgr), ("bgra", bgra)]:
        d = picker._to_display_bgr(im)
        assert d.shape == (10, 10, 3) and d.dtype == np.uint8, (name, d.shape)
    # alpha is flattened for preview, not passed through raw
    assert not np.array_equal(picker._to_display_bgr(bgra)[0, 0], [255, 0, 255])

    root = tk.Tk()
    root.withdraw()
    ph = picker._photoimage(tk, bgr, 0.5)
    assert (ph.width(), ph.height()) == (5, 5), (ph.width(), ph.height())
    ph2 = picker._photoimage(tk, bgr, 1.0)
    assert (ph2.width(), ph2.height()) == (10, 10)
    root.destroy()
    print("ok: render pipeline (_to_display_bgr, _photoimage)")


def _run_scripted(image_path, events, **kw):
    """Replace Tk.mainloop with a scripted sequence, then call pick_regions."""
    def runner(self):
        root = self.winfo_toplevel()
        root.deiconify()
        root.focus_force()
        root.update()
        root.update_idletasks()
        canvas = [w for w in root.winfo_children()
                  if isinstance(w, tk.Canvas)][0]
        canvas.focus_set()
        root.update()
        events(root, canvas)
        root.update()
        root.update_idletasks()
    saved = tk.Misc.mainloop
    tk.Misc.mainloop = runner
    try:
        return picker.pick_regions(image_path, 1280, 800, **kw)
    finally:
        tk.Misc.mainloop = saved


def check_drag_and_cancel(tmp):
    img = np.zeros((64, 64, 4), np.uint8)
    img[:, :, 3] = 255
    path = str(tmp / "one.png")
    cv2.imwrite(path, img)

    def drag_then_enter(root, canvas):
        x0, y0, x1, y1 = 48, 48, 64, 64
        canvas.event_generate("<ButtonPress-1>", x=x0, y=y0, warp=True)
        canvas.update()
        for t in range(1, 6):
            canvas.event_generate("<B1-Motion>",
                                  x=x0 + (x1 - x0) * t // 5,
                                  y=y0 + (y1 - y0) * t // 5, warp=True)
            canvas.update()
        canvas.event_generate("<ButtonRelease-1>", x=x1, y=y1, warp=True)
        canvas.update()
        root.event_generate("<Return>")

    r = _run_scripted(path, drag_then_enter)
    assert len(r) == 1, r
    assert all(abs(a - b) <= 2 for a, b in zip(r[0], [48, 48, 16, 16])), r
    print("ok: drag + Enter ->", r)

    def just_escape(root, canvas):
        root.event_generate("<Escape>")

    r2 = _run_scripted(path, just_escape, initial=[(48, 48, 16, 16)])
    assert r2 == [], r2
    print("ok: Escape cancels ->", r2)


def main():
    import tempfile
    check_render()
    with tempfile.TemporaryDirectory() as d:
        check_drag_and_cancel(pathlib.Path(d))
    print("GUI SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
