"""Headless geometry/state for the interactive region picker.

All the math the picker needs -- fitting a large image into a window, mapping
canvas <-> image coordinates, normalising drag rectangles, hit-testing for
selection, and emitting absolute or relative region lists -- lives here as pure
functions and a small state class with **no Tkinter dependency**, so it can be
unit-tested in a headless environment. ``picker.py`` is only the thin widget
shell that wires mouse/key events to this state.
"""


def fit_scale(img_w, img_h, max_w, max_h):
    """Scale factor to fit (img_w, img_h) inside (max_w, max_h), never
    upscaling (cap at 1.0). Always > 0."""
    if img_w <= 0 or img_h <= 0:
        return 1.0
    return max(min(max_w / img_w, max_h / img_h, 1.0), 1e-9)


def view_size(img_w, img_h, scale):
    """Pixel size of the scaled view, at least 1x1."""
    return max(1, int(round(img_w * scale))), max(1, int(round(img_h * scale)))


def canvas_to_image(cx, cy, scale, img_w, img_h):
    """Map a canvas point to integer image pixel coords, clamped to bounds."""
    x = int(cx / scale)
    y = int(cy / scale)
    return (max(0, min(img_w - 1, x)), max(0, min(img_h - 1, y)))


def image_to_canvas(x, y, scale):
    """Map an image point to canvas coords."""
    return (x * scale, y * scale)


def normalize_rect(x0, y0, x1, y1):
    """Two corners (any order) -> (x, y, w, h) with non-negative size."""
    x, y = min(x0, x1), min(y0, y1)
    w, h = abs(x1 - x0), abs(y1 - y0)
    return (x, y, w, h)


def clamp_rect(rect, img_w, img_h):
    """Clip (x, y, w, h) to the image; returns None if it collapses to empty."""
    x, y, w, h = rect
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(img_w, x + w), min(img_h, y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def point_in_rect(px, py, rect):
    x, y, w, h = rect
    return x <= px <= x + w and y <= py <= y + h


def to_relative(rect, img_w, img_h):
    """(x, y, w, h) in px -> fractions of (img_w, img_h)."""
    x, y, w, h = rect
    return (x / img_w, y / img_h, w / img_w, h / img_h)


def to_absolute(rect, img_w, img_h):
    """Fractional (x, y, w, h) -> integer pixels."""
    x, y, w, h = rect
    return (int(round(x * img_w)), int(round(y * img_h)),
            int(round(w * img_w)), int(round(h * img_h)))


class PickerState:
    """The picker's data model: the image size, the current scale, and the list
    of selected rectangles (stored in absolute image pixels). Tkinter-free so
    it can be driven and asserted in tests."""

    MIN_SIZE = 3   # ignore stray click-rectangles smaller than this (px)

    def __init__(self, img_w, img_h, max_w, max_h, initial=None):
        self.img_w = img_w
        self.img_h = img_h
        self.scale = fit_scale(img_w, img_h, max_w, max_h)
        self.regions = []
        for r in (initial or []):
            c = clamp_rect(tuple(r), img_w, img_h)
            if c:
                self.regions.append(c)

    # -- view helpers ------------------------------------------------------- #
    def view_size(self):
        return view_size(self.img_w, self.img_h, self.scale)

    def to_image(self, cx, cy):
        return canvas_to_image(cx, cy, self.scale, self.img_w, self.img_h)

    def to_canvas(self, x, y):
        return image_to_canvas(x, y, self.scale)

    # -- editing ------------------------------------------------------------ #
    def add_drag(self, ix0, iy0, ix1, iy1):
        """Commit a drag (two image-space points) as a new region. Returns the
        clamped region, or None if it was too small / empty."""
        rect = clamp_rect(normalize_rect(ix0, iy0, ix1, iy1),
                          self.img_w, self.img_h)
        if rect is None or rect[2] < self.MIN_SIZE or rect[3] < self.MIN_SIZE:
            return None
        self.regions.append(rect)
        return rect

    def hit(self, ix, iy):
        """Index of the top-most region under an image point, else None.
        Iterates last-drawn-first so the visually top rectangle wins."""
        for i in range(len(self.regions) - 1, -1, -1):
            if point_in_rect(ix, iy, self.regions[i]):
                return i
        return None

    def remove_at(self, ix, iy):
        """Delete the top-most region under a point. Returns True if removed."""
        i = self.hit(ix, iy)
        if i is None:
            return False
        del self.regions[i]
        return True

    def pop_last(self):
        """Undo: drop the most recently added region. Returns it, or None."""
        return self.regions.pop() if self.regions else None

    def clear(self):
        self.regions = []

    # -- output ------------------------------------------------------------- #
    def result(self, relative=False):
        """The selected regions as a list of [x, y, w, h] -- integer pixels, or
        float fractions of the image when ``relative`` is True."""
        if relative:
            return [list(to_relative(r, self.img_w, self.img_h))
                    for r in self.regions]
        return [list(r) for r in self.regions]
