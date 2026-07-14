"""
core/simplify_shapes.py — Android port
---------------------------------------
Converts a reference photo into simplified shape outlines grouped by dominant color.
Ported from desktop simplify_shapes.py:
  - tkinter picker UI removed (Kivy screen calls simplify() directly)
  - sklearn.cluster.KMeans replaced with cv2.kmeans (sklearn has no reliable
    python-for-android recipe; cv2 is already a hard dependency here, so this
    removes a whole extra compiled package from the build)

Pipeline unchanged:
1. K-means cluster the image into N dominant color groups
2. For each color group, extract a binary mask
3. Morphologically clean the mask (close gaps, remove noise)
4. Find Canny edges on the mask
5. Find contours and draw them on a white canvas in the group's dominant color
"""

import os
import cv2
import numpy as np

# ─── CONFIG (same defaults as desktop version) ────────────────────────────
N_COLORS = 6
MIN_AREA = 1500
CANNY_LOW = 30
CANNY_HIGH = 90
MORPH_CLOSE_K = 15
MORPH_OPEN_K = 5
CONTOUR_THICKNESS = 2
DOWNSAMPLE_MAX = 800
# ────────────────────────────────────────────────────────────────────────


def load_and_resize(path, max_side=DOWNSAMPLE_MAX):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {path}")
    h, w = img.shape[:2]
    scale = min(max_side / max(h, w), 1.0)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_AREA)
    return img


def kmeans_segment(img_bgr, n_colors):
    """Return (labels 2-D array, centers BGR array) using cv2's built-in kmeans."""
    h, w = img_bgr.shape[:2]
    pixels = img_bgr.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
    _, labels, centers = cv2.kmeans(
        pixels, n_colors, None, criteria, attempts=6,
        flags=cv2.KMEANS_PP_CENTERS
    )
    labels = labels.reshape(h, w)
    centers = centers.astype(np.uint8)
    return labels, centers


def build_mask(labels, label_id, close_k=MORPH_CLOSE_K, open_k=MORPH_OPEN_K):
    mask = (labels == label_id).astype(np.uint8) * 255
    kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
    ko = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kc)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ko)
    return mask


def edges_from_mask(mask):
    blurred = cv2.GaussianBlur(mask, (5, 5), 0)
    return cv2.Canny(blurred, CANNY_LOW, CANNY_HIGH)


def draw_group(canvas, mask, color_bgr, min_area=MIN_AREA):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        if cv2.contourArea(cnt) < min_area:
            continue
        fill_color = tuple(int(255 * 0.65 + c * 0.35) for c in color_bgr)
        cv2.drawContours(canvas, [cnt], -1, fill_color, thickness=cv2.FILLED)
        cv2.drawContours(canvas, [cnt], -1, tuple(int(c) for c in color_bgr),
                          thickness=CONTOUR_THICKNESS)


def simplify(img_path, out_dir, n_colors=N_COLORS, progress_cb=None):
    """
    Run the full pipeline. progress_cb(str) is called with status text if given
    (Kivy screen can wire this to a Label to show progress on-device).
    Returns (out_path, cluster_preview_path).
    """
    def report(msg):
        if progress_cb:
            progress_cb(msg)

    report(f"Loading {os.path.basename(img_path)}")
    img = load_and_resize(img_path)
    h, w = img.shape[:2]

    report(f"Running K-means with {n_colors} colors…")
    labels, centers = kmeans_segment(img, n_colors)

    canvas = np.full((h, w, 3), 255, dtype=np.uint8)

    for i, color in enumerate(centers):
        report(f"Processing color group {i + 1}/{n_colors}")
        mask = build_mask(labels, i)
        draw_group(canvas, mask, color)

    stem = os.path.splitext(os.path.basename(img_path))[0]
    out_path = os.path.join(out_dir, f"{stem}_simplified.png")
    cv2.imwrite(out_path, canvas)

    cluster_img = centers[labels]
    prev_path = os.path.join(out_dir, f"{stem}_clusters.png")
    cv2.imwrite(prev_path, cluster_img)

    report("Done.")
    return out_path, prev_path
