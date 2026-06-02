"""Shared inpainting engine.

Single source of truth for "given an image + a binary mask, regenerate the
masked pixels". Both the batch CLI (clean.py) and the GUI app (app.py) call
``clean_image`` so the locked invariants hold everywhere:

    * pixels OUTSIDE the mask are byte-for-byte identical to the input
    * the alpha channel is passed through untouched
    * only masked pixels change

Backends
    telea / ns   OpenCV's classical inpainting (default; tiny, instant)
    lama         LaMa deep-learning inpainting (opt-in; needs torch + the
                 ``simple-lama-inpainting`` package -- a heavy, separate
                 install). Imported lazily so the core stays opencv + numpy.

Even though LaMa runs a global pass, we only ever composite the *masked* region
back over the untouched original, so the outside-mask / alpha invariants hold no
matter which backend is used.
"""
import cv2
import numpy as np

CV2_FLAGS = {"telea": cv2.INPAINT_TELEA, "ns": cv2.INPAINT_NS}
DEFAULT_METHOD = "telea"

_LAMA = None  # cached SimpleLama instance (model weights are expensive to load)


# --------------------------------------------------------------------------- #
# channels: keep alpha completely out of the inpaint path
# --------------------------------------------------------------------------- #
def split_alpha(img):
    """Return (colour, alpha). Alpha is None when the image has none. The
    colour array is a contiguous copy ready for inpainting (1 or 3 channels)."""
    if img.ndim == 3 and img.shape[2] == 4:        # BGRA
        return np.ascontiguousarray(img[:, :, :3]), img[:, :, 3].copy()
    if img.ndim == 3 and img.shape[2] == 2:        # gray + alpha
        return np.ascontiguousarray(img[:, :, 0]), img[:, :, 1].copy()
    return img.copy(), None


def merge_alpha(color, alpha):
    if alpha is None:
        return color
    return np.dstack([color, alpha])


# --------------------------------------------------------------------------- #
# palette matching (snap to colours that already exist in the source)
# --------------------------------------------------------------------------- #
def build_palette(color, mask, max_colors):
    """Colours present *outside* the mask (the real content), optionally capped
    to the ``max_colors`` most frequent. Every entry truly occurs in the
    source, so snapping to it can never invent a colour."""
    src = color[mask == 0]
    if src.size == 0:                              # mask covers everything
        src = color.reshape(-1, color.shape[-1]) if color.ndim == 3 \
            else color.reshape(-1)
    src = src.reshape(len(src), -1)
    colors, counts = np.unique(src, axis=0, return_counts=True)
    if 0 < max_colors < len(colors):
        colors = colors[np.argsort(counts)[::-1][:max_colors]]
    return colors


def snap_to_palette(pixels, palette):
    """Snap each pixel (N, C) to its nearest palette colour (Euclidean)."""
    p = pixels.astype(np.int32)[:, None, :]        # (N, 1, C)
    pal = palette.astype(np.int32)[None, :, :]     # (1, K, C)
    idx = ((p - pal) ** 2).sum(axis=2).argmin(axis=1)
    return palette[idx]


# --------------------------------------------------------------------------- #
# mask helpers
# --------------------------------------------------------------------------- #
def dilate_mask(mask, dilate):
    """Grow a binary mask by ~``dilate`` px in every direction (no-op if <= 0)."""
    if dilate and dilate > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                      (2 * dilate + 1, 2 * dilate + 1))
        return cv2.dilate(mask, k)
    return mask


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #
def lama_available():
    """True if the optional LaMa backend can be imported."""
    try:
        import simple_lama_inpainting  # noqa: F401
        return True
    except Exception:
        return False


def available_methods():
    """Inpainting methods usable right now, cheapest first."""
    methods = list(CV2_FLAGS)
    if lama_available():
        methods.append("lama")
    return methods


def _lama_inpaint(color, mask):
    """Run LaMa on a BGR (or gray) image; returns the same channel layout/size.
    Lazy-imports torch + PIL + simple_lama_inpainting only when actually used."""
    from PIL import Image
    from simple_lama_inpainting import SimpleLama

    global _LAMA
    if _LAMA is None:
        _LAMA = SimpleLama()

    gray = color.ndim == 2
    bgr = cv2.cvtColor(color, cv2.COLOR_GRAY2BGR) if gray else color
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    out = _LAMA(Image.fromarray(rgb),
                Image.fromarray(mask).convert("L"))
    out = np.asarray(out)[:, :, :3]                # PIL RGB -> array
    if out.shape[:2] != color.shape[:2]:           # safety: LaMa pads to /8
        out = cv2.resize(out, (color.shape[1], color.shape[0]),
                         interpolation=cv2.INTER_LINEAR)
    out_bgr = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(out_bgr, cv2.COLOR_BGR2GRAY) if gray else out_bgr


def inpaint_color(color, mask, method, radius):
    """Inpaint a colour-only image (1 or 3 channels) with the chosen backend.
    Returns a full image the same shape as ``color``; the caller composites the
    masked region back."""
    if method in CV2_FLAGS:
        return cv2.inpaint(color, mask, radius, CV2_FLAGS[method])
    if method == "lama":
        return _lama_inpaint(color, mask)
    raise ValueError(f"unknown inpaint method: {method!r} "
                     f"(have {available_methods()})")


# --------------------------------------------------------------------------- #
# the one entry point everything shares
# --------------------------------------------------------------------------- #
def clean_image(img, mask, method=DEFAULT_METHOD, radius=3, dilate=0,
                palette_match=False, max_colors=16):
    """Regenerate ``img``'s masked pixels and composite them over the untouched
    original.

    img    HxW, HxWx2 (gray+A), HxWx3 (BGR), or HxWx4 (BGRA), uint8.
    mask   HxW uint8; non-zero = "regenerate this pixel".
    Returns an array the same shape/dtype as ``img``.
    """
    if mask.shape[:2] != img.shape[:2]:
        raise ValueError(f"mask {mask.shape[:2]} != image {img.shape[:2]}")
    mask = np.ascontiguousarray(mask, dtype=np.uint8)
    mask = (mask > 0).astype(np.uint8) * 255       # force strict binary
    mask = dilate_mask(mask, dilate)

    color, alpha = split_alpha(img)
    sel = mask > 0
    if not sel.any():                              # nothing selected: untouched
        return img.copy()

    painted = inpaint_color(color, mask, method, radius)
    region = painted[sel]
    if palette_match and region.size:
        pal = build_palette(color, mask, max_colors)
        region = snap_to_palette(region.reshape(len(region), -1),
                                 pal).reshape(region.shape)

    out = color.copy()
    out[sel] = region
    return merge_alpha(out, alpha)
