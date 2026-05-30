"""Headless document model for the GUI app.

Holds the editing state -- the working image, the current paint mask, and an
undo/redo history -- and delegates the actual pixel work to ``engine``. No
Tkinter here, so the whole edit/clean/undo flow is unit-testable without a
display. ``app.py`` is only the widget shell that drives this.

Coordinate convention: everything is in *image* pixels. The view layer scales
canvas <-> image (see picker_core helpers) before calling in.
"""
import cv2
import numpy as np

import engine

SUPPORTED_READ = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def load_image(path):
    """Read any supported image as-is (preserving alpha). Raises on failure."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise IOError(f"cannot read image: {path}")
    return img


def save_image(path, img):
    if not cv2.imwrite(str(path), img):
        raise IOError(f"cannot write image: {path}")


class Document:
    """One open image plus its editable mask and undo/redo history.

    The mask accumulates the user's brush/box strokes (255 = "regenerate").
    ``apply_clean`` runs the engine over the masked pixels, pushes the previous
    image onto the undo stack, and clears the mask for the next edit."""

    MAX_HISTORY = 30

    def __init__(self, img, path=None):
        self.path = path
        self.image = img
        self.h, self.w = img.shape[:2]
        self.mask = np.zeros((self.h, self.w), np.uint8)
        self._undo = []
        self._redo = []
        self.dirty = False

    # -- constructors ------------------------------------------------------- #
    @classmethod
    def open(cls, path):
        return cls(load_image(path), path=path)

    # -- mask painting (image-space coords) --------------------------------- #
    def paint_circle(self, x, y, radius):
        """Add a filled brush dab to the mask."""
        cv2.circle(self.mask, (int(x), int(y)), max(1, int(radius)), 255, -1)

    def paint_line(self, x0, y0, x1, y1, radius):
        """Add a thick stroke between two points (smooth dragging)."""
        cv2.line(self.mask, (int(x0), int(y0)), (int(x1), int(y1)), 255,
                 max(1, int(radius) * 2))
        self.paint_circle(x1, y1, radius)            # round the end caps

    def paint_rect(self, x0, y0, x1, y1):
        """Add an axis-aligned rectangle (box-select) to the mask."""
        x_lo, x_hi = sorted((int(x0), int(x1)))
        y_lo, y_hi = sorted((int(y0), int(y1)))
        self.mask[max(0, y_lo):y_hi + 1, max(0, x_lo):x_hi + 1] = 255

    def erase_circle(self, x, y, radius):
        """Remove from the mask (un-paint), e.g. a right-drag correction."""
        cv2.circle(self.mask, (int(x), int(y)), max(1, int(radius)), 0, -1)

    def clear_mask(self):
        self.mask[:] = 0

    def has_mask(self):
        return bool(self.mask.any())

    # -- the operation ------------------------------------------------------ #
    def apply_clean(self, method=engine.DEFAULT_METHOD, radius=3, dilate=0,
                    palette_match=False, max_colors=16):
        """Inpaint the painted region. No-op (returns False) if nothing is
        painted. On success the image is replaced, the stroke is undoable, and
        the mask is reset."""
        if not self.has_mask():
            return False
        result = engine.clean_image(self.image, self.mask, method=method,
                                    radius=radius, dilate=dilate,
                                    palette_match=palette_match,
                                    max_colors=max_colors)
        self._push_undo()
        self.image = result
        self.clear_mask()
        self.dirty = True
        return True

    # -- undo / redo -------------------------------------------------------- #
    def _push_undo(self):
        self._undo.append(self.image.copy())
        if len(self._undo) > self.MAX_HISTORY:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self.image.copy())
        self.image = self._undo.pop()
        self.clear_mask()
        self.dirty = True
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self.image.copy())
        self.image = self._redo.pop()
        self.clear_mask()
        self.dirty = True
        return True

    # -- output ------------------------------------------------------------- #
    def save(self, path=None):
        """Write the current image. Never defaults to overwriting the source
        silently -- the caller (GUI) decides the path; we just refuse an empty
        one."""
        target = path or self.path
        if not target:
            raise ValueError("no save path given")
        save_image(target, self.image)
        self.dirty = False
        return target

    def overlay(self, mask_color=(0, 0, 255), alpha=0.45):
        """A BGR preview of the image with the current mask tinted on top, for
        display. Does not modify the document."""
        color, _ = engine.split_alpha(self.image)
        if color.ndim == 2:
            color = cv2.cvtColor(color, cv2.COLOR_GRAY2BGR)
        vis = color.copy()
        sel = self.mask > 0
        if sel.any():
            tint = np.zeros_like(vis)
            tint[:] = mask_color
            vis[sel] = (vis[sel] * (1 - alpha) + tint[sel] * alpha).astype(np.uint8)
        return vis
