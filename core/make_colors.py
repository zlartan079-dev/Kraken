"""
core/make_colors.py — Android port
======================================
Ported from image_measure_tool_color.py's make_colors() method.
Same algorithm (white-pixel replacement blended by brightness, preserving
pattern detail), refactored from a tkinter method into a standalone
function:
  - takes pattern_image_paths (a list, from a multi-file picker) instead
    of listing a picked folder — Android's directory picker (SAF tree)
    is unreliable via plyer, but multi-file selection works fine
  - takes svg_palette explicitly instead of reading a module global
  - out_root is expected to be an app-managed directory, not something
    the user picks (see README for why)
"""

import os
import numpy as np
from PIL import Image

WHITE_THRESH = 200  # pixels with R,G,B all >= this are treated as white


def make_colors(svg_palette, pattern_image_paths, out_root, progress_cb=None):
    """
    svg_palette          : list of (r,g,b) tuples — unique SVG fill colors
    pattern_image_paths  : list of file paths to source pattern PNGs
    out_root              : directory to write <R>_<G>_<B>/ subfolders into
    Returns out_root.
    """
    def report(msg):
        if progress_cb:
            progress_cb(msg)

    if not svg_palette:
        raise ValueError("No SVG colors provided — load an SVG with filled shapes first.")
    if not pattern_image_paths:
        raise ValueError("No pattern images provided.")

    os.makedirs(out_root, exist_ok=True)

    total = len(svg_palette) * len(pattern_image_paths)
    done = 0

    for (r_svg, g_svg, b_svg) in svg_palette:
        folder_key = f"{r_svg}_{g_svg}_{b_svg}"
        dest_folder = os.path.join(out_root, folder_key)
        os.makedirs(dest_folder, exist_ok=True)

        for src_path in pattern_image_paths:
            fname = os.path.basename(src_path)
            try:
                img = Image.open(src_path).convert("RGBA")
                arr = np.array(img, dtype=np.float32)

                white_mask = (
                    (arr[:, :, 0] >= WHITE_THRESH) &
                    (arr[:, :, 1] >= WHITE_THRESH) &
                    (arr[:, :, 2] >= WHITE_THRESH)
                )

                brightness = arr[:, :, :3].mean(axis=2) / 255.0

                out_arr = arr.copy()
                out_arr[white_mask, 0] = r_svg * brightness[white_mask]
                out_arr[white_mask, 1] = g_svg * brightness[white_mask]
                out_arr[white_mask, 2] = b_svg * brightness[white_mask]

                result = Image.fromarray(out_arr.astype(np.uint8), "RGBA")
                final = Image.new("RGB", result.size, (r_svg, g_svg, b_svg))
                final.paste(result, mask=result.split()[3])
                final.save(os.path.join(dest_folder, fname))
            except Exception as e:
                report(f"Warning: could not process {fname}: {e}")

            done += 1
            if done % 5 == 0 or done == total:
                report(f"Recoloring... {done} / {total}")

    report(f"Done — {len(svg_palette)} color folder(s) in {out_root}")
    return out_root
