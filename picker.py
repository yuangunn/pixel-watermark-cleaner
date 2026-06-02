"""Interactive region picker (Tkinter shell).

Shows a representative image in a window; you drag rectangles over the
watermark(s), then those region(s) drive the batch clean. All geometry lives in
``picker_core`` (headless, unit-tested); this file is just the widget layer and
imports Tkinter lazily, so importing the module never requires a display.

Controls
  Left-drag        draw a selection rectangle
  Right-click      delete the rectangle under the cursor
  u / Ctrl-Z       undo last rectangle
  c                clear all
  Enter            confirm and clean
  Esc / q          cancel (no regions)

No Pillow dependency: the OpenCV image is encoded to PNG in memory and handed to
Tk's PhotoImage.
"""
import base64

import cv2
import numpy as np

from picker_core import PickerState

HELP = ("drag: select   right-click: delete   u: undo   c: clear   "
        "Enter: clean   Esc: cancel")


def _to_display_bgr(img):
    """Any cv2 image (gray / BGR / BGRA) -> BGR uint8 for on-screen display.
    Alpha is flattened over a mid-grey checker-ish background just for preview;
    it never touches the actual output pipeline."""
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        bgr = img[:, :, :3].astype(np.float32)
        a = (img[:, :, 3:4].astype(np.float32)) / 255.0
        bg = np.full_like(bgr, 128.0)
        return (bgr * a + bg * (1 - a)).astype(np.uint8)
    return img


def _photoimage(tk, bgr, scale):
    """Build a Tk PhotoImage from a BGR array, scaled for display."""
    vw = max(1, int(round(bgr.shape[1] * scale)))
    vh = max(1, int(round(bgr.shape[0] * scale)))
    interp = cv2.INTER_NEAREST if scale < 1 else cv2.INTER_NEAREST
    view = cv2.resize(bgr, (vw, vh), interpolation=interp)
    ok, buf = cv2.imencode(".png", view)
    if not ok:
        raise RuntimeError("failed to encode preview image")
    return tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))


def pick_regions(image_path, max_w=1280, max_h=800, relative=False, initial=None):
    """Open the picker for ``image_path`` and return the chosen regions as a
    list of [x, y, w, h] (absolute px, or fractions if ``relative``). Returns []
    if the user cancels. Raises RuntimeError if the image can't be read."""
    import tkinter as tk

    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"cannot read image: {image_path}")
    h, w = img.shape[:2]

    state = PickerState(w, h, max_w, max_h, initial=initial)
    disp = _to_display_bgr(img)

    root = tk.Tk()
    root.title(f"pwc region picker — {image_path}")
    photo = _photoimage(tk, disp, state.scale)
    vw, vh = state.view_size()

    canvas = tk.Canvas(root, width=vw, height=vh, highlightthickness=0,
                       cursor="crosshair")
    canvas.pack(side="top")
    canvas.create_image(0, 0, anchor="nw", image=photo)
    status = tk.Label(root, text=HELP, anchor="w", font=("TkDefaultFont", 10))
    status.pack(side="bottom", fill="x")

    drag = {"id": None, "x0": 0, "y0": 0}
    result = {"regions": None}

    def redraw():
        canvas.delete("rect")
        for i, (x, y, rw, rh) in enumerate(state.regions):
            cx0, cy0 = state.to_canvas(x, y)
            cx1, cy1 = state.to_canvas(x + rw, y + rh)
            canvas.create_rectangle(cx0, cy0, cx1, cy1, outline="#ff2d2d",
                                    width=2, tags="rect")
            canvas.create_text(cx0 + 3, cy0 + 3, anchor="nw", text=str(i + 1),
                               fill="#ff2d2d", tags="rect",
                               font=("TkDefaultFont", 9, "bold"))
        status.config(text=f"{len(state.regions)} region(s)   |   {HELP}")

    def on_press(e):
        drag["x0"], drag["y0"] = e.x, e.y
        drag["id"] = canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                             outline="#23d18b", width=2,
                                             dash=(4, 2))

    def on_move(e):
        if drag["id"] is not None:
            canvas.coords(drag["id"], drag["x0"], drag["y0"], e.x, e.y)

    def on_release(e):
        if drag["id"] is not None:
            canvas.delete(drag["id"])
            drag["id"] = None
            ix0, iy0 = state.to_image(drag["x0"], drag["y0"])
            ix1, iy1 = state.to_image(e.x, e.y)
            state.add_drag(ix0, iy0, ix1, iy1)
            redraw()

    def on_right(e):
        ix, iy = state.to_image(e.x, e.y)
        if state.remove_at(ix, iy):
            redraw()

    def undo(_=None):
        state.pop_last()
        redraw()

    def clear(_=None):
        state.clear()
        redraw()

    def confirm(_=None):
        result["regions"] = state.result(relative=relative)
        root.destroy()

    def cancel(_=None):
        result["regions"] = []
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_move)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<ButtonPress-3>", on_right)
    root.bind("u", undo)
    root.bind("<Control-z>", undo)
    root.bind("c", clear)
    root.bind("<Return>", confirm)
    root.bind("<Escape>", cancel)
    root.bind("q", cancel)
    root.protocol("WM_DELETE_WINDOW", cancel)

    redraw()
    root.mainloop()
    return result["regions"] or []


def main(argv=None):
    """Standalone ``pwc-pick`` entry point: pick on an image, print JSON, and
    optionally write a config."""
    import argparse
    import json

    p = argparse.ArgumentParser(
        prog="pwc-pick",
        description="Draw watermark region(s) on an image; print them as JSON.")
    p.add_argument("image", help="image to draw on")
    p.add_argument("--relative", action="store_true",
                   help="emit coords as fractions of width/height (0..1)")
    p.add_argument("--max-view", nargs=2, type=int, default=[1280, 800],
                   metavar=("W", "H"), help="max window size in px")
    p.add_argument("--save-config", metavar="FILE",
                   help="write a pwc config with the chosen regions")
    args = p.parse_args(argv)

    try:
        regions = pick_regions(args.image, args.max_view[0], args.max_view[1],
                               relative=args.relative)
    except ImportError as e:
        raise SystemExit(
            f"error: the region picker needs Tkinter ({e}). On Linux install "
            "it via your OS package manager: `sudo apt install python3-tk` "
            "(Debian/Ubuntu) or `sudo dnf install python3-tkinter` (Fedora).")
    if not regions:
        print("[]")
        return 0
    print(json.dumps(regions))
    if args.save_config:
        cfg = {"regions": regions}
        if args.relative:
            cfg["relative"] = True
        with open(args.save_config, "w") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        print(f"saved config -> {args.save_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
