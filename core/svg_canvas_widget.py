"""
core/svg_canvas_widget.py — Android port of image_measure_tool_color.py's
SVG canvas/picking behavior (render_svg + svg_pick), rebuilt for touch.

Desktop used a tkinter Canvas with scroll-wheel zoom and right-click to
pick a shape. Touch equivalent here: shapes are fit to the widget and
tapping picks the smallest-area filled shape under the tap (verified
against the desktop's svg_pick — same "smallest area wins" rule for
overlapping shapes).

Filled polygon rendering uses kivy.graphics.tesselator.Tesselator, which
handles concave shapes correctly (a simple triangle-fan would render
concave letterform/illustration shapes wrong).
"""

from kivy.uix.widget import Widget
from kivy.graphics import Color, Mesh, Line
from kivy.graphics.tesselator import Tesselator, WINDING_ODD, TYPE_POLYGONS
from kivy.properties import ListProperty, ObjectProperty

from core.svg_parser import point_in_polygon, polygon_area

UNFILLED_LINE_COLOR = (0.55, 0.55, 0.55, 1)
NO_COLOR_FILL = (0.6, 0.6, 0.6, 1)
PICKED_FILL = (1, 1, 1, 1)
HIGHLIGHT_OUTLINE = (0.2, 1, 0.2, 1)


class SvgCanvasWidget(Widget):
    shapes = ListProperty([])       # from svg_parser.parse_svg()
    viewbox = ObjectProperty(None)  # (vbx, vby, vbw, vbh)

    # NOTE: deliberately not named on_shape_picked — Kivy's EventDispatcher
    # treats "on_<x>" attribute assignment as event-binding magic, which
    # caused this callback to fire twice per touch in testing. Plain name
    # avoids that entirely.
    pick_callback = ObjectProperty(None, allownone=True)  # callback(shape_index)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._shape_color_instr = {}   # shape index -> Color instruction (for filled shapes)
        self._picked = set()
        self._current_pick = None
        self.bind(shapes=self._redraw, viewbox=self._redraw,
                  size=self._redraw, pos=self._redraw)

    # ─── coordinate transform: SVG space <-> widget-local pixel space ─────

    def _fit_transform(self):
        if not self.viewbox or self.width <= 0 or self.height <= 0:
            return None
        vbx, vby, vbw, vbh = self.viewbox
        if vbw <= 0 or vbh <= 0:
            return None
        scale = min(self.width / vbw, self.height / vbh)
        draw_w, draw_h = vbw * scale, vbh * scale
        off_x = self.x + (self.width - draw_w) / 2
        off_y = self.y + (self.height - draw_h) / 2
        return (vbx, vby, scale, off_x, off_y)

    def svg_to_widget(self, sx, sy):
        t = self._fit_transform()
        if not t:
            return (0, 0)
        vbx, vby, scale, off_x, off_y = t
        wx = off_x + (sx - vbx) * scale
        # SVG y grows downward from top; widget/canvas y grows upward from bottom
        wy = off_y + self.height - (sy - vby) * scale
        return (wx, wy)

    def widget_to_svg(self, wx, wy):
        t = self._fit_transform()
        if not t:
            return (0, 0)
        vbx, vby, scale, off_x, off_y = t
        sx = (wx - off_x) / scale + vbx
        sy = (self.height - (wy - off_y)) / scale + vby
        return (sx, sy)

    # ─── rendering ──────────────────────────────────────────────────────

    def _redraw(self, *args):
        self.canvas.clear()
        self._shape_color_instr = {}
        t = self._fit_transform()
        if not t or not self.shapes:
            return

        with self.canvas:
            for idx, shape in enumerate(self.shapes):
                pts_widget = [self.svg_to_widget(x, y) for x, y in shape["points"]]

                if not shape["filled"]:
                    Color(*UNFILLED_LINE_COLOR)
                    flat = [c for p in pts_widget for c in p]
                    Line(points=flat, close=True, width=1)
                    continue

                color = shape["color"]
                rgba = (color[0]/255, color[1]/255, color[2]/255, 1) if color else NO_COLOR_FILL

                tess = Tesselator()
                flat = [c for p in pts_widget for c in p]
                tess.add_contour(flat)
                if not tess.tesselate(WINDING_ODD, TYPE_POLYGONS):
                    continue  # degenerate polygon, skip rendering (still pickable via point_in_polygon)

                col_instr = Color(*rgba)
                self._shape_color_instr[idx] = col_instr
                for verts, indices in tess.meshes:
                    Mesh(vertices=verts, indices=indices, mode='triangle_fan')

    # ─── picking ────────────────────────────────────────────────────────

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        if not self.shapes:
            return super().on_touch_down(touch)

        sx, sy = self.widget_to_svg(*touch.pos)
        hits = []
        for idx, shape in enumerate(self.shapes):
            if not shape["filled"]:
                continue
            if point_in_polygon(sx, sy, shape["points"]):
                hits.append((polygon_area(shape["points"]), idx))

        if not hits:
            return True  # consumed the touch, nothing to pick

        hits.sort(key=lambda h: h[0])
        picked_idx = hits[0][1]

        if self.pick_callback:
            self.pick_callback(picked_idx)

        return True

    def highlight_pick(self, idx):
        """Whiten all previous picks, outline the new one in green —
        matches the desktop's visual feedback."""
        self._picked.add(idx)
        for i in self._picked:
            instr = self._shape_color_instr.get(i)
            if instr:
                instr.rgba = PICKED_FILL

        self._current_pick = idx
        # redraw a highlight outline for the newly picked shape on top
        shape = self.shapes[idx]
        pts_widget = [self.svg_to_widget(x, y) for x, y in shape["points"]]
        with self.canvas:
            Color(*HIGHLIGHT_OUTLINE)
            Line(points=[c for p in pts_widget for c in p], close=True, width=2)

    def reset_picks(self):
        self._picked = set()
        self._current_pick = None
        self._redraw()
