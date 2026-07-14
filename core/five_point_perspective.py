"""
core/five_point_perspective.py — Android port
------------------------------------------------
Renders an image in true 5-point (spherical) perspective.
Ported from desktop five_point_perspective.py: identical math, tkinter
file dialogs removed — the Kivy screen supplies input_path/out_dir directly.
"""

import math
import os

import numpy as np
from PIL import Image, ImageDraw

FOV_DEG = 40
OUTPUT_SIZE = 2048
BORDER_WIDTH = 3


def five_point_spherical(img_array, fov_deg=FOV_DEG, output_size=OUTPUT_SIZE):
    h, w = img_array.shape[:2]
    out_r = output_size // 2

    ys, xs = np.meshgrid(np.arange(output_size),
                          np.arange(output_size), indexing='ij')
    dx = (xs - out_r).astype(np.float64)
    dy = (ys - out_r).astype(np.float64)
    r_pix = np.sqrt(dx ** 2 + dy ** 2)
    mask = r_pix <= out_r

    theta = (r_pix / out_r) * (math.pi / 2.0)
    phi = np.arctan2(dy, dx)

    sin_t = np.sin(theta)
    vx = sin_t * np.cos(phi)
    vy = sin_t * np.sin(phi)
    vz = np.cos(theta)

    fov_rad = math.radians(fov_deg)
    f = (w / 2.0) / math.tan(fov_rad / 2.0)

    good = mask & (vz > 0.001)

    src_x = np.full_like(r_pix, -1.0)
    src_y = np.full_like(r_pix, -1.0)
    src_x[good] = f * vx[good] / vz[good] + w / 2.0
    src_y[good] = f * vy[good] / vz[good] + h / 2.0

    valid = (good
             & (src_x >= 0) & (src_x <= w - 1.001)
             & (src_y >= 0) & (src_y <= h - 1.001))

    sx = np.clip(src_x, 0, w - 1.001)
    sy = np.clip(src_y, 0, h - 1.001)
    x0 = sx.astype(np.int32)
    y0 = sy.astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    wx = (sx - x0)[..., np.newaxis]
    wy = (sy - y0)[..., np.newaxis]

    s = img_array.astype(np.float32)
    sampled = (s[y0, x0] * (1 - wx) * (1 - wy)
               + s[y0, x1] * wx * (1 - wy)
               + s[y1, x0] * (1 - wx) * wy
               + s[y1, x1] * wx * wy)
    sampled = np.clip(sampled, 0, 255).astype(np.uint8)

    canvas = np.full((output_size, output_size, 3), 255, dtype=np.uint8)
    canvas[valid] = sampled[valid]

    img_out = Image.fromarray(canvas)
    draw = ImageDraw.Draw(img_out)
    draw.ellipse([1, 1, output_size - 2, output_size - 2],
                 outline=(0, 0, 0), width=BORDER_WIDTH)
    return img_out


def run(input_path, out_dir, fov_deg=FOV_DEG, output_size=OUTPUT_SIZE):
    """Kivy-facing entry point: takes real paths, returns the saved output path."""
    base = os.path.splitext(os.path.basename(input_path))[0]
    out_path = os.path.join(out_dir, f"{base}_5pt_fov{int(fov_deg)}.png")

    img = Image.open(input_path).convert("RGB")
    result = five_point_spherical(np.array(img), fov_deg, output_size)
    result.save(out_path)
    return out_path
