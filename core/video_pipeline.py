"""
core/video_pipeline.py — Android port of main.py
=====================================================
main.py on desktop records its animation by grabbing a LIVE tkinter Canvas
each frame (`screen.getcanvas().postscript(...)`) and rasterizing that EPS
with Ghostscript. Neither tkinter's windowing Canvas nor Ghostscript exist
on Android, so this isn't a dialog swap like pv.py was — the capture
mechanism itself has to be rebuilt.

What this does instead, functionally equivalent to the original two-pass
desktop version (animate outlines → composite partial fills into saved
frames → compile video):

  - A persistent PIL RGBA "line layer" stands in for the turtle's on-screen
    trace. Each incremental step of an outline draws directly onto it with
    ImageDraw.line(), instead of moving a real turtle and screenshotting.
  - drawer.build_partial_fills(count) (already used by desktop main.py's
    second pass) gives the fill state for "count" finished polygons — reused
    as-is here.
  - Frames are composited (fills + in-progress line layer) and written
    straight to cv2.VideoWriter, with no per-frame PNGs touching disk. The
    desktop version wrote thousands of individual PNGs to OUT_DIR and read
    them back in a second pass — fine on a PC, a real bottleneck on a
    phone's storage, so this collapses it into one pass.
  - The fill layer is only rebuilt when a polygon actually finishes, not on
    every single tiny movement frame (cached and reused across all the
    animation frames within one polygon's trace) — build_partial_fills()
    re-renders every finished polygon's colored-pencil strokes from
    scratch, which is expensive; recomputing it every frame would be very
    slow on mobile hardware.
  - `frame_stride` controls how many of the original per-step frames are
    actually captured (desktop main.py captured literally every step —
    fine for local disk, wasteful for a phone-rendered video). Default
    keeps every 3rd step; raise it for faster/shorter renders.

The baked sequence of draw_polygon_animated(...) calls below is copied
verbatim from main.py — it's this artwork's specific polygon/colour data,
unrelated to the platform it runs on.
"""

import os
import math

import numpy as np
import cv2
from PIL import Image, ImageDraw

from core.polygon_render import setup_image_drawer
from core.sample_artwork import VIDEO_SAMPLE_POLYGONS

W = 1080
H = 1080
LOGICAL_W = 360
LOGICAL_H = 360
FPS = 60
DRAW_STEP = 2
FRAME_STRIDE = 3  # capture every Nth sub-step; raise to shorten render time


class _LineTracer:
    """Stand-in for the turtle's on-screen trace: an RGBA layer we draw
    incremental line segments onto directly, instead of moving a real
    turtle and screenshotting a tkinter Canvas."""

    def __init__(self, canvas_w, canvas_h):
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h
        self.layer = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)
        self.pen_color = (0, 0, 0)
        self.pensize = 1
        self.pos_px = (0, 0)

    def clear(self):
        self.layer = Image.new('RGBA', (self.canvas_w, self.canvas_h), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)

    def set_pos_px(self, px):
        self.pos_px = px

    def line_to_px(self, px):
        self.draw.line([self.pos_px, px], fill=(*self.pen_color, 255),
                        width=max(1, self.pensize))
        self.pos_px = px


class _VideoRecorder:
    """Composites (finished-polygon fills + in-progress line trace) and
    writes straight to cv2.VideoWriter — no per-frame PNGs on disk."""

    def __init__(self, video_path, w, h, fps):
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.writer = cv2.VideoWriter(video_path, fourcc, fps, (w, h))
        self.frame_count = 0

    def write(self, fill_rgb_image, line_layer_rgba):
        composite = fill_rgb_image.convert('RGBA')
        composite.alpha_composite(line_layer_rgba)
        frame_bgr = cv2.cvtColor(np.array(composite.convert('RGB')), cv2.COLOR_RGB2BGR)
        self.writer.write(frame_bgr)
        self.frame_count += 1

    def release(self):
        self.writer.release()


class _FillCache:
    """build_partial_fills() re-renders every finished polygon's
    colored-pencil strokes from scratch — expensive. Only recompute when
    the finished-polygon count actually changes."""

    def __init__(self, drawer):
        self.drawer = drawer
        self.count = -1
        self.image = None

    def get(self, count):
        if count != self.count:
            self.image = self.drawer.build_partial_fills(count)
            self.count = count
        return self.image


def _move_to(tracer, drawer, recorder, fill_cache, finished_count,
             target_x, target_y, draw, step, frame_stride, step_counter):
    """Mirrors main.py's move_to(): subdivides the movement into small
    steps and captures frames along the way. Returns updated step_counter."""
    x0_log, y0_log = getattr(tracer, '_logical_pos', (0, 0))
    dx, dy = target_x - x0_log, target_y - y0_log
    dist = math.hypot(dx, dy)

    target_px = drawer.logical_to_pixel(target_x, target_y)

    if not draw:
        tracer.set_pos_px(target_px)
        tracer._logical_pos = (target_x, target_y)
        return step_counter

    steps = max(1, int(dist / step))
    for i in range(steps):
        nx = x0_log + dx * (i + 1) / steps
        ny = y0_log + dy * (i + 1) / steps
        px = drawer.logical_to_pixel(nx, ny)
        tracer.line_to_px(px)

        step_counter += 1
        if step_counter % frame_stride == 0:
            fill_img = fill_cache.get(finished_count)
            recorder.write(fill_img, tracer.layer)

    tracer._logical_pos = (target_x, target_y)
    return step_counter


def _draw_polygon_animated(tracer, drawer, recorder, fill_cache, state,
                            points, img_number, pen_color, pensize=1,
                            desaturation=0, draw_step=DRAW_STEP,
                            frame_stride=FRAME_STRIDE):
    tracer.pensize = pensize
    tracer.pen_color = pen_color

    step_counter = state['step_counter']
    finished = state['finished']

    first_px = drawer.logical_to_pixel(points[0][0], points[0][1])
    tracer.set_pos_px(first_px)
    tracer._logical_pos = points[0]

    for p in points[1:]:
        step_counter = _move_to(tracer, drawer, recorder, fill_cache, finished,
                                 p[0], p[1], True, draw_step, frame_stride, step_counter)
    step_counter = _move_to(tracer, drawer, recorder, fill_cache, finished,
                             points[0][0], points[0][1], True, draw_step,
                             frame_stride, step_counter)

    # polygon trace complete: wipe the transient outline (matches
    # turtle_obj.clear() in the desktop version) and register the fill
    tracer.clear()
    drawer.register_polygon(points, img_number, pen_color, pensize, desaturation)
    finished += 1

    state['step_counter'] = step_counter
    state['finished'] = finished


def run(image_lib_path, output_dir, polygons=None, progress_cb=None,
        frame_stride=FRAME_STRIDE, fps=FPS):
    """
    image_lib_path : folder of RGB-keyed reference images (as on desktop)
    output_dir     : folder to save output_video.mp4 into
    polygons       : list of dicts: {points, img_number, pen_color,
                      pensize, desaturation} — one per shape, drawn in
                      order. Falls back to a bundled sample artwork if
                      omitted.
    frame_stride   : capture every Nth animation sub-step (higher = faster,
                     choppier render — tune for phone performance)
    Returns the saved video file path.
    """
    def report(msg):
        if progress_cb:
            progress_cb(msg)
        print(msg)

    if polygons is None:
        report("No polygons supplied — using bundled sample artwork.")
        polygons = VIDEO_SAMPLE_POLYGONS

    os.makedirs(output_dir, exist_ok=True)
    video_path = os.path.join(output_dir, "output_video.mp4")

    report("Setting up drawer…")
    drawer = setup_image_drawer(
        image_lib_path=image_lib_path,
        canvas_w=W, canvas_h=H,
        logical_w=LOGICAL_W, logical_h=LOGICAL_H
    )

    tracer = _LineTracer(W, H)
    recorder = _VideoRecorder(video_path, W, H, fps)
    fill_cache = _FillCache(drawer)
    state = {'step_counter': 0, 'finished': 0}

    for i, poly in enumerate(polygons, 1):
        report(f"Polygon {i}/{len(polygons)}")
        _draw_polygon_animated(tracer, drawer, recorder, fill_cache, state, **poly)

    # final frame: everything finished, no in-progress trace
    report("Writing final frame…")
    final_fill = fill_cache.get(state['finished'])
    tracer.clear()
    recorder.write(final_fill, tracer.layer)

    recorder.release()
    report(f"Saved: {video_path}  ({recorder.frame_count} frames)")
    return video_path
