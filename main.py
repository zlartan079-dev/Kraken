"""
Kraken Paint — Android app shell (Kivy)
=========================================
Rebuilt after learning the real desktop workflow:
  Illustrator (live-paint SVG) -> image_measure_tool_color.py picks shapes
  off the SVG + generates a recolored pattern library -> pv.py/main.py
  render using that generated polygon data.

Key design decisions from that correction:

  - Folder-picking is gone. plyer's directory chooser (choose_dir) is
    unreliable on Android's Storage Access Framework — that's why "Choose
    output folder" did nothing when tested on-device. image_lib_path and
    output_dir are now fixed app-managed directories (App.user_data_dir),
    which need no picker and no special permission. Only genuine FILE
    selection uses plyer's open_file (confirmed working on-device).

  - pv_pipeline.run()/video_pipeline.run() now take an explicit `polygons`
    list instead of only ever replaying one baked sample — the SVG picker
    screen is what generates that list now, in-app, no clipboard/text
    round-trip needed.

Screens:
  HomeScreen
  SvgPickerScreen    — load SVG, tap shapes to pick / Pick All, ports
                        image_measure_tool_color.py's SVG mode
  MakeColorsScreen   — generate the recolored pattern library from the
                        loaded SVG's palette
  PvScreen           — core/pv_pipeline.run() (still image)
  VideoScreen        — core/video_pipeline.run() (animated MP4)
  FivePointScreen    — core/five_point_perspective.run()
  SimplifyScreen     — core/simplify_shapes.simplify()
  ColorWheelScreen   — real RGB-slider picker wired to core/color_wheel.py
  ImageMeasureScreen — STUB: the raster flood-fill fallback mode from
                        image_measure_tool_color.py isn't ported (SVG mode
                        is the primary workflow per confirmed usage)
"""

import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.image import Image as KivyImage
from kivy.graphics import Color, Rectangle

try:
    from plyer import filechooser
except ImportError:
    filechooser = None  # desktop test-run fallback

from core import (pv_pipeline, video_pipeline, five_point_perspective,
                   simplify_shapes, color_wheel, make_colors)
from core.svg_parser import parse_svg, svg_to_cart
from core.color_classify import classify_color_group
from core.svg_canvas_widget import SvgCanvasWidget


def pick_file(callback, multiple=False, filters=None):
    if filechooser:
        filechooser.open_file(
            on_selection=lambda sel: callback(sel if multiple else (sel[0] if sel else None)),
            multiple=multiple,
            filters=filters or [])
    else:
        callback([] if multiple else None)


class ToolScreenBase(Screen):
    """Common status-label + run-in-background-thread plumbing."""

    def build_status_ui(self, layout):
        self.status_label = Label(text="Ready", size_hint_y=None, height=60)
        layout.add_widget(self.status_label)

    def set_status(self, msg):
        Clock.schedule_once(lambda dt: setattr(self.status_label, "text", str(msg)))

    def run_in_thread(self, fn, on_done=None):
        def worker():
            try:
                result = fn()
                if on_done:
                    Clock.schedule_once(lambda dt: on_done(result))
            except Exception as e:
                self.set_status(f"Error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def back_button(self, layout):
        back = Button(text="Back", size_hint_y=None, height=48)
        back.bind(on_release=lambda i: setattr(self.manager, "current", "home"))
        layout.add_widget(back)


class HomeScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        layout.add_widget(Label(text="Kraken Paint", font_size=28, size_hint_y=None, height=60))
        for name, target in [
            ("1. Pick Shapes from SVG", "svgpicker"),
            ("2. Make Colors (build pattern library)", "makecolors"),
            ("3. Colored-Pencil Render (pv)", "pv"),
            ("3. Animated Video Render (main)", "video"),
            ("Five-Point Perspective", "fivepoint"),
            ("Shape Simplifier", "simplify"),
            ("Color Wheel Lookup", "colorwheel"),
            ("Image Region Tool (WIP)", "imagemeasure"),
        ]:
            btn = Button(text=name, size_hint_y=None, height=52)
            btn.bind(on_release=lambda inst, t=target: self.goto(t))
            layout.add_widget(btn)
        self.add_widget(layout)

    def goto(self, name):
        self.manager.current = name


# ─── 1. SVG Picker ──────────────────────────────────────────────────────

class SvgPickerScreen(ToolScreenBase):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.svg_path = None
        root = BoxLayout(orientation="vertical", padding=10, spacing=8)

        top = BoxLayout(orientation="horizontal", size_hint_y=None, height=48, spacing=6)
        load_btn = Button(text="Load SVG")
        load_btn.bind(on_release=lambda i: pick_file(self.load_svg,
                       filters=[("SVG files", "*.svg")]))
        top.add_widget(load_btn)
        pickall_btn = Button(text="Pick All Shapes")
        pickall_btn.bind(on_release=lambda i: self.pick_all())
        top.add_widget(pickall_btn)
        clear_btn = Button(text="Clear Picks")
        clear_btn.bind(on_release=lambda i: self.clear_picks())
        top.add_widget(clear_btn)
        root.add_widget(top)

        self.canvas_widget = SvgCanvasWidget()
        self.canvas_widget.pick_callback = self.on_shape_tapped
        root.add_widget(self.canvas_widget)

        self.build_status_ui(root)
        self.back_button(root)
        self.add_widget(root)

    def load_svg(self, path):
        if not path:
            return
        app = App.get_running_app()
        try:
            shapes, viewbox = parse_svg(path)
        except Exception as e:
            self.set_status(f"Failed to parse SVG: {e}")
            return

        self.svg_path = path
        app.svg_shapes = shapes
        app.svg_viewbox = viewbox
        # unique fill colors across all filled shapes -> the palette used
        # both for picking (classify_color_group) and Make Colors
        app.svg_palette = sorted({s["color"] for s in shapes if s["filled"] and s["color"]})

        self.canvas_widget.viewbox = viewbox
        self.canvas_widget.shapes = shapes
        self.canvas_widget.reset_picks()

        n_filled = sum(1 for s in shapes if s["filled"])
        self.set_status(
            f"Loaded {os.path.basename(path)}: {n_filled} filled shape(s), "
            f"{len(app.svg_palette)} unique color(s). Tap shapes or 'Pick All'.")

    def on_shape_tapped(self, idx):
        app = App.get_running_app()
        shape = app.svg_shapes[idx]
        pts = [svg_to_cart(x, y, app.svg_viewbox) for x, y in shape["points"]]

        color = shape["color"]
        if color:
            img_num, desat, pensize = classify_color_group(*color, app.svg_palette)
        else:
            img_num, desat, pensize = "random_midtone", 0, 8  # matches desktop svg_pick fallback

        app.picked_polygons.append(dict(
            points=pts, img_number=img_num, pen_color=(45, 45, 48),
            pensize=pensize, desaturation=desat))
        self.canvas_widget.highlight_pick(idx)
        self.set_status(f"Added shape ({len(pts)} pts, {img_num}) — "
                         f"{len(app.picked_polygons)} queued.")

    def pick_all(self):
        app = App.get_running_app()
        if not app.svg_shapes:
            self.set_status("Load an SVG first.")
            return
        filled = [s for s in app.svg_shapes if s["filled"]]
        if not filled:
            self.set_status("No filled shapes found in this SVG.")
            return

        def bbox_area(s):
            xs = [p[0] for p in s["points"]]; ys = [p[1] for p in s["points"]]
            return (max(xs) - min(xs)) * (max(ys) - min(ys))
        filled = sorted(filled, key=bbox_area, reverse=True)  # large-to-small, correct z-order

        result = []
        for shape in filled:
            pts = [svg_to_cart(x, y, app.svg_viewbox) for x, y in shape["points"]]
            color = shape["color"]
            if color:
                img_num, desat, pensize = classify_color_group(*color, app.svg_palette)
            else:
                img_num, desat, pensize = "random_midtone", 0, 6  # matches desktop copy_all_shapes fallback
            result.append(dict(points=pts, img_number=img_num, pen_color=(45, 45, 48),
                                pensize=pensize, desaturation=desat))

        app.picked_polygons = result
        self.set_status(f"Picked all {len(result)} filled shape(s), sorted for z-order.")

    def clear_picks(self):
        app = App.get_running_app()
        app.picked_polygons = []
        self.canvas_widget.reset_picks()
        self.set_status("Cleared queued picks.")


# ─── 2. Make Colors ─────────────────────────────────────────────────────

class MakeColorsScreen(ToolScreenBase):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.pattern_paths = []
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        layout.add_widget(Label(text="Make Colors", size_hint_y=None, height=40))
        layout.add_widget(Label(
            text="Recolors pattern PNGs to match every unique color in the\n"
                 "currently-loaded SVG, building the pattern library pv/video\n"
                 "render from. Load an SVG on the previous screen first.",
            size_hint_y=None, height=80))

        self.palette_label = Label(text="No SVG loaded yet.", size_hint_y=None, height=40)
        layout.add_widget(self.palette_label)

        pattern_btn = Button(text="Choose pattern images", size_hint_y=None, height=48)
        pattern_btn.bind(on_release=lambda i: pick_file(self.set_patterns, multiple=True))
        layout.add_widget(pattern_btn)

        run_btn = Button(text="Generate", size_hint_y=None, height=48)
        run_btn.bind(on_release=lambda i: self.run())
        layout.add_widget(run_btn)

        self.build_status_ui(layout)
        self.back_button(layout)
        self.add_widget(layout)

    def on_pre_enter(self):
        app = App.get_running_app()
        if app.svg_palette:
            self.palette_label.text = f"{len(app.svg_palette)} color(s) from loaded SVG."
        else:
            self.palette_label.text = "No SVG loaded yet — go load one first."

    def set_patterns(self, paths):
        self.pattern_paths = paths or []
        self.set_status(f"{len(self.pattern_paths)} pattern image(s) selected.")

    def run(self):
        app = App.get_running_app()
        if not app.svg_palette:
            self.set_status("Load an SVG with filled shapes first.")
            return
        if not self.pattern_paths:
            self.set_status("Choose pattern images first.")
            return
        self.set_status("Starting…")

        def work():
            return make_colors.make_colors(
                app.svg_palette, self.pattern_paths, app.image_lib_dir,
                progress_cb=self.set_status)

        def done(out_dir):
            self.set_status(f"Done: {out_dir}")

        self.run_in_thread(work, done)


# ─── 3. Render screens ──────────────────────────────────────────────────

class PvScreen(ToolScreenBase):
    def __init__(self, **kw):
        super().__init__(**kw)
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        layout.add_widget(Label(text="Colored-Pencil Render", size_hint_y=None, height=40))
        layout.add_widget(Label(
            text="Uses whatever's queued from the SVG picker; falls back to\n"
                 "a bundled sample artwork if nothing's queued.",
            size_hint_y=None, height=50))

        run_btn = Button(text="Run", size_hint_y=None, height=48)
        run_btn.bind(on_release=lambda i: self.run())
        layout.add_widget(run_btn)

        self.build_status_ui(layout)
        self.preview = KivyImage(size_hint_y=1)
        layout.add_widget(self.preview)
        self.back_button(layout)
        self.add_widget(layout)

    def run(self):
        app = App.get_running_app()
        polygons = app.picked_polygons if app.picked_polygons else None
        self.set_status("Starting…")

        def work():
            return pv_pipeline.run(app.image_lib_dir, app.output_dir,
                                    polygons=polygons, progress_cb=self.set_status)

        def done(path):
            self.set_status(f"Done: {path}")
            self.preview.source = path
            self.preview.reload()

        self.run_in_thread(work, done)


class VideoScreen(ToolScreenBase):
    def __init__(self, **kw):
        super().__init__(**kw)
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        layout.add_widget(Label(text="Animated Video Render", size_hint_y=None, height=40))
        layout.add_widget(Label(
            text="Uses whatever's queued from the SVG picker; falls back to\n"
                 "a bundled sample artwork if nothing's queued. Heaviest tool\n"
                 "— renders straight to MP4, can take a while.",
            size_hint_y=None, height=70))

        run_btn = Button(text="Run", size_hint_y=None, height=48)
        run_btn.bind(on_release=lambda i: self.run())
        layout.add_widget(run_btn)

        self.build_status_ui(layout)
        self.back_button(layout)
        self.add_widget(layout)

    def run(self):
        app = App.get_running_app()
        polygons = app.picked_polygons if app.picked_polygons else None
        self.set_status("Starting…")

        def work():
            return video_pipeline.run(app.image_lib_dir, app.output_dir,
                                       polygons=polygons, progress_cb=self.set_status)

        def done(path):
            self.set_status(f"Done: {path}")

        self.run_in_thread(work, done)


class FivePointScreen(ToolScreenBase):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.input_path = None
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        layout.add_widget(Label(text="Five-Point Perspective", size_hint_y=None, height=40))

        self.in_btn = Button(text="Choose input image", size_hint_y=None, height=48)
        self.in_btn.bind(on_release=lambda i: pick_file(self.set_in_path))
        layout.add_widget(self.in_btn)

        run_btn = Button(text="Run", size_hint_y=None, height=48)
        run_btn.bind(on_release=lambda i: self.run())
        layout.add_widget(run_btn)

        self.build_status_ui(layout)
        self.preview = KivyImage(size_hint_y=1)
        layout.add_widget(self.preview)
        self.back_button(layout)
        self.add_widget(layout)

    def set_in_path(self, path):
        self.input_path = path
        self.in_btn.text = path or "Choose input image"

    def run(self):
        if not self.input_path:
            self.set_status("Pick an input image first.")
            return
        app = App.get_running_app()
        self.set_status("Rendering…")

        def work():
            return five_point_perspective.run(self.input_path, app.output_dir)

        def done(path):
            self.set_status(f"Done: {path}")
            self.preview.source = path
            self.preview.reload()

        self.run_in_thread(work, done)


class SimplifyScreen(ToolScreenBase):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.input_path = None
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        layout.add_widget(Label(text="Shape Simplifier", size_hint_y=None, height=40))

        self.in_btn = Button(text="Choose input image", size_hint_y=None, height=48)
        self.in_btn.bind(on_release=lambda i: pick_file(self.set_in_path))
        layout.add_widget(self.in_btn)

        run_btn = Button(text="Run (6 colors)", size_hint_y=None, height=48)
        run_btn.bind(on_release=lambda i: self.run())
        layout.add_widget(run_btn)

        self.build_status_ui(layout)
        self.preview = KivyImage(size_hint_y=1)
        layout.add_widget(self.preview)
        self.back_button(layout)
        self.add_widget(layout)

    def set_in_path(self, path):
        self.input_path = path
        self.in_btn.text = path or "Choose input image"

    def run(self):
        if not self.input_path:
            self.set_status("Pick an input image first.")
            return
        app = App.get_running_app()
        self.set_status("Starting…")

        def work():
            out_path, _ = simplify_shapes.simplify(
                self.input_path, app.output_dir, n_colors=6, progress_cb=self.set_status)
            return out_path

        def done(path):
            self.set_status(f"Done: {path}")
            self.preview.source = path
            self.preview.reload()

        self.run_in_thread(work, done)


# ─── Color Wheel (real implementation, not a placeholder) ────────────────

class _SwatchWidget(BoxLayout):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas:
            self._color = Color(0.5, 0.5, 0.5, 1)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_rect, size=self._update_rect)

    def _update_rect(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_color(self, r, g, b):
        self._color.rgba = (r/255, g/255, b/255, 1)


class ColorWheelScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        layout.add_widget(Label(text="Color Wheel Lookup", size_hint_y=None, height=40))

        self.swatch = _SwatchWidget(size_hint_y=None, height=100)
        layout.add_widget(self.swatch)

        self.result_label = Label(text="", size_hint_y=None, height=60)
        layout.add_widget(self.result_label)

        self.sliders = {}
        for ch in ("R", "G", "B"):
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=44, spacing=8)
            row.add_widget(Label(text=ch, size_hint_x=None, width=24))
            s = Slider(min=0, max=255, value=128)
            s.bind(value=self.on_slider_change)
            self.sliders[ch] = s
            row.add_widget(s)
            layout.add_widget(row)

        back = Button(text="Back", size_hint_y=None, height=48)
        back.bind(on_release=lambda i: setattr(self.manager, "current", "home"))
        layout.add_widget(back)

        self.add_widget(layout)
        self.on_slider_change(None, None)

    def on_slider_change(self, instance, value):
        r = int(self.sliders["R"].value)
        g = int(self.sliders["G"].value)
        b = int(self.sliders["B"].value)
        self.swatch.set_color(r, g, b)
        name, tone, rgb = color_wheel.closest_color(r, g, b)
        self.result_label.text = f"RGB({r},{g},{b}) -> {name} ({tone})  match RGB{rgb}"


class ImageMeasureScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        layout.add_widget(Label(
            text="Image Region Tool (raster flood-fill fallback) — not ported.\n\n"
                 "The SVG-based picker (screen 1) covers the confirmed primary\n"
                 "workflow. This mode — click-to-flood-fill on a plain raster\n"
                 "photo when no SVG is available — is a separate, still-unbuilt\n"
                 "feature if it turns out you need it too.",
            size_hint_y=None, height=160))
        back = Button(text="Back", size_hint_y=None, height=48)
        back.bind(on_release=lambda i: setattr(self.manager, "current", "home"))
        layout.add_widget(back)
        self.add_widget(layout)


class KrakenPaintApp(App):
    def build(self):
        self.image_lib_dir = os.path.join(self.user_data_dir, "image_library")
        self.output_dir = os.path.join(self.user_data_dir, "output")
        os.makedirs(self.image_lib_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        self.svg_shapes = []
        self.svg_viewbox = None
        self.svg_palette = []
        self.picked_polygons = []

        sm = ScreenManager()
        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(SvgPickerScreen(name="svgpicker"))
        sm.add_widget(MakeColorsScreen(name="makecolors"))
        sm.add_widget(PvScreen(name="pv"))
        sm.add_widget(VideoScreen(name="video"))
        sm.add_widget(FivePointScreen(name="fivepoint"))
        sm.add_widget(SimplifyScreen(name="simplify"))
        sm.add_widget(ColorWheelScreen(name="colorwheel"))
        sm.add_widget(ImageMeasureScreen(name="imagemeasure"))
        return sm


if __name__ == "__main__":
    KrakenPaintApp().run()
