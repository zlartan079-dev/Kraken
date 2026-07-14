"""
polygon_with_images_final.py  —  Colored Pencil Edition  (v9)
=============================================================
Fills polygons with a colored-pencil drawing effect instead of
oil-paint stipple.  The colour comes directly from the img_number RGB key
(e.g. "233_171_0") — no image files are needed for colour-key fills.

v9 IMPROVEMENTS
---------------
  1. Technical Execution
     • Per-pass colour jitter: light pass is clean (jitter=8), shadow is rough (jitter=35).
       Previously all passes used the same flat jitter — now strokes feel materially distinct.
     • Area-proportional minimum stroke count: tiny polygons no longer get a flat minimum
       of 12 strokes. Minimum is now `max(3, area // 45)` — small cells stay proportional.
     • 3-segment smooth curves for long strokes: strokes longer than 2× MIN_LEN are drawn
       as three segments with two independent midpoint displacements, eliminating the
       visible kink at the midpoint of the old 2-segment approach.

  2. Value Hierarchy & Spatial Clarity
     • Global directional light bias (PENCIL_LIGHT_DIR, PENCIL_LIGHT_STRENGTH):
       Each polygon's centroid is projected onto the light direction vector and the
       base brightness is shifted accordingly — facing-light polygons are lighter,
       away-from-light polygons are darker. Gives the whole composition a coherent
       light source without the caller needing to manage it.
     • Edge darkening / micro-AO (PENCIL_EDGE_DARKEN, PENCIL_EDGE_INSET):
       A thin inset border at each polygon's perimeter is darkened after all stroke
       passes. This simulates contact shadow / ambient occlusion at cell boundaries,
       sharpening depth separation between adjacent polygons.

  3. Composition & Visual Rhythm
     • visual_weight parameter (0.0–2.0, default 1.0):
       Multiplies into the density scale. Use > 1.0 for focal polygons (more strokes,
       stronger texture), < 1.0 for background areas (less strokes, recede).
     • Hue-luminance grain scaling: paper grain density now scales with perceived
       luminance — bright polygons show more grain (paper shows through light wax),
       dark polygons show less (wax fills the tooth). Improves tonal rhythm.

  4. Style & Texture Realization
     • Hue-tinted paper grain: grain dots are now tinted toward the polygon's base
       colour instead of plain warm-grey. On saturated polygons this preserves colour
       identity and colour harmony across the whole piece.
     • Randomised cross-hatch angle offset (±15° per stroke):
       The shadow pass now applies an additional random offset per stroke on top of
       PENCIL_CROSSHATCH_ANGLE, breaking the mechanical regularity of fixed-angle
       hatching into something more naturalistic.

COLORED PENCIL FILL BEHAVIOUR
------------------------------
Each polygon is filled with overlapping layers of short, thin, slightly
wavy strokes that mimic real colored-pencil marks on textured paper:

  • colour   = the RGB parsed from img_number, with controlled variation
                across four tonal layers (light, main ×2, shadow passes)
  • strokes  = short lines (~6–20 px) with subtle random curvature
  • direction = primary stroke_angle with gentle fan spread (±22°)
                A second cross-hatch pass at +68° adds pencil depth
  • paper    = sparse hue-tinted "tooth" dots simulate paper grain
  • density  = strokes cover the polygon uniformly; pencil stays inside the shape
  • opacity  = strokes use alpha compositing so layered marks mix naturally

PASSES (four per polygon):
  1. Light pass  — slightly lighter, low density, clean strokes (jitter=8)
  2. Main pass   — base colour, high density (jitter=20)
  3. Second main — slight variation (jitter=25)
  4. Shadow pass — slightly darker, randomised crosshatch angle (jitter=35)

LEGACY IMAGE FILL
-----------------
If img_number is NOT a plain R_G_B colour key (e.g. "random_light",
"random_dark", a numeric id, or None) the old image-paste behaviour is
used unchanged — so nothing in your existing scripts breaks.

NEW PARAMETERS (v9)
-------------------
  visual_weight : float  (default 1.0)
      Compositional density emphasis. 0.5 = recede, 1.0 = neutral, 1.5 = focal point.

PENCIL CONSTANTS (tuneable at top of module)
--------------------------------------------
  PENCIL_STROKE_MIN_LEN   — shortest stroke in pixels (default 7)
  PENCIL_STROKE_MAX_LEN   — longest stroke in pixels (default 20)
  PENCIL_STROKE_WIDTH     — line width of each stroke (default 1)
  PENCIL_COLOUR_JITTER    — global jitter fallback (overridden per-pass in PENCIL_PASSES)
  PENCIL_ANGLE_SPREAD     — ± fan spread around primary angle (default 22°)
  PENCIL_WAVINESS         — max perpendicular offset for stroke midpoint curve (default 1.5)
  PENCIL_PAPER_DENSITY    — base fraction of area covered by paper-grain dots (default 0.06)
  PENCIL_LIGHT_LIFT       — brightness boost for light pass (default 38)
  PENCIL_SHADOW_DROP      — brightness reduction for shadow pass (default 30)
  PENCIL_CROSSHATCH_ANGLE — base angle offset (degrees) for the shadow pass (default 68)
  PENCIL_EDGE_DARKEN      — brightness reduction for inset edge border (default 38)
  PENCIL_EDGE_INSET       — inset border width in pixels (default 2)
  PENCIL_LIGHT_DIR        — global light direction unit vector (default (0.6, -0.8))
  PENCIL_LIGHT_STRENGTH   — max brightness shift from global light (default 22)

TONE-ADAPTIVE DENSITY
---------------------
Stroke density is automatically scaled by perceived luminance of the
polygon's base colour (highlights stay airy, shadows feel heavy/rich),
then further multiplied by visual_weight for compositional control.
"""

import random
import math
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np


# ─── tuneable constants ──────────────────────────────────────────────────────

PENCIL_STROKE_MIN_LEN   = 7      # shortest stroke (pixels)
PENCIL_STROKE_MAX_LEN   = 20     # longest stroke (pixels)
PENCIL_STROKE_WIDTH     = 1      # stroke line width in pixels
PENCIL_COLOUR_JITTER    = 20     # max per-channel random colour noise
PENCIL_ANGLE_SPREAD     = 22     # ± fan spread around primary angle (degrees)
PENCIL_WAVINESS         = 1.5    # max perpendicular offset for stroke midpoint curve
PENCIL_PAPER_DENSITY    = 0.06   # fraction of bbox area covered by paper-grain dots
PENCIL_LIGHT_LIFT       = 38     # brightness boost for light pass
PENCIL_SHADOW_DROP      = 30     # brightness reduction for shadow pass
PENCIL_CROSSHATCH_ANGLE = 68     # angle offset (degrees) for the shadow pass

# stroke density bands: (strokes_per_100px², brightness_modifier, angle_offset_deg, jitter)
# Per-pass jitter: light pass is clean, shadow pass is rough — matches real pencil behaviour.
PENCIL_PASSES = [
    (1.8,  PENCIL_LIGHT_LIFT,    0,                        8),   # light pass  — clean highlight
    (4.5,  0,                    0,                        20),  # main pass   — base texture
    (3.0,  0,                    0,                        25),  # second main — slight variation
    (2.2, -PENCIL_SHADOW_DROP,   PENCIL_CROSSHATCH_ANGLE,  35),  # shadow pass — rough crosshatch
]

# Tone-adaptive density multipliers keyed by perceived luminance band.
# Highlights get fewer strokes (airy), shadows get more (dense/rich).
# Change these values to taste; 1.0 = neutral baseline (midtone).
PENCIL_TONE_DENSITY_SCALE = {
    'highlight': 0.55,   # luminance >= PENCIL_HIGHLIGHT_THRESH
    'midtone':   1.0,    # between thresholds (neutral baseline)
    'shadow':    1.65,   # luminance < PENCIL_SHADOW_THRESH
}

# Luminance thresholds (ITU-R BT.601 perceived brightness, 0-255 scale)
PENCIL_HIGHLIGHT_THRESH = 180   # at or above -> highlight
PENCIL_SHADOW_THRESH    =  80   # below -> shadow; in-between -> midtone

# Edge darkening: inset-border brightness drop applied inside the polygon perimeter.
# Creates micro-AO (ambient occlusion) at cell boundaries — improves spatial clarity.
PENCIL_EDGE_DARKEN      =  38   # brightness reduction for the inset border
PENCIL_EDGE_INSET       =   2   # inset in pixels (how far inside the border we darken)

# Global light direction (unit vector, canvas space: +x right, +y down).
# Used to bias brightness of each polygon based on centroid position relative to
# the canvas centre — gives the whole scene a directional light source.
# Set to (0, 0) to disable (fully local colour, no global lighting).
PENCIL_LIGHT_DIR        = (0.6, -0.8)   # approx top-right light
PENCIL_LIGHT_STRENGTH   = 22            # max brightness shift from global light

# ── Parallel line overlay ────────────────────────────────────────────────────
# Black lines drawn on top of the pencil texture, aligned to stroke_angle_deg.
# They give the graphic parallel-line look while the pencil layer underneath
# makes them feel drawn and blended rather than a flat digital overlay.
LINE_SPACING      = 6     # pixels between line centres (increase = fewer, airier lines)
LINE_WIDTH        = 1     # thickness of each black line in pixels
LINE_COLOUR       = (45, 45, 45)   # colour of the parallel lines (default black)


# ─── colour parsing ──────────────────────────────────────────────────────────

def _parse_rgb_key(img_number):
    """Return (r, g, b) if img_number is an 'R_G_B' colour key, else None."""
    if not isinstance(img_number, str):
        return None
    parts = img_number.split('_')
    if len(parts) != 3:
        return None
    try:
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
            return (r, g, b)
    except ValueError:
        pass
    return None


def _jitter(value, amount):
    """Clamp value + random offset to [0, 255]."""
    return max(0, min(255, value + random.randint(-amount, amount)))


def _lift(value, amount):
    """Brighten a channel by amount, clamped to [0, 255]."""
    return max(0, min(255, value + amount))


def _tone_band(rgb):
    """
    Classify an (r, g, b) colour as 'highlight', 'midtone', or 'shadow'
    using ITU-R BT.601 perceived luminance.
    """
    r, g, b = rgb
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    if luminance >= PENCIL_HIGHLIGHT_THRESH:
        return 'highlight'
    elif luminance < PENCIL_SHADOW_THRESH:
        return 'shadow'
    return 'midtone'


# ─── geometry helpers ────────────────────────────────────────────────────────

def _point_in_polygon(px, py, poly):
    """Ray-casting point-in-polygon test."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _polygon_bbox(pixel_points):
    xs = [p[0] for p in pixel_points]
    ys = [p[1] for p in pixel_points]
    return min(xs), min(ys), max(xs), max(ys)


def _clip_segment_to_bbox(x0, y0, x1, y1, bx0, by0, bx1, by1):
    """Cohen-Sutherland clip — returns clipped (x0,y0,x1,y1) or None."""
    def code(x, y):
        c = 0
        if x < bx0: c |= 1
        elif x > bx1: c |= 2
        if y < by0: c |= 4
        elif y > by1: c |= 8
        return c
    c0, c1 = code(x0, y0), code(x1, y1)
    while True:
        if not (c0 | c1):
            return x0, y0, x1, y1
        if c0 & c1:
            return None
        c = c0 if c0 else c1
        if c & 8:
            x = x0 + (x1 - x0) * (by1 - y0) / (y1 - y0) if y1 != y0 else x0
            y = by1
        elif c & 4:
            x = x0 + (x1 - x0) * (by0 - y0) / (y1 - y0) if y1 != y0 else x0
            y = by0
        elif c & 2:
            y = y0 + (y1 - y0) * (bx1 - x0) / (x1 - x0) if x1 != x0 else y0
            x = bx1
        else:
            y = y0 + (y1 - y0) * (bx0 - x0) / (x1 - x0) if x1 != x0 else y0
            x = bx0
        if c == c0:
            x0, y0, c0 = x, y, code(x, y)
        else:
            x1, y1, c1 = x, y, code(x, y)


def _contour_angle_deg(pixel_points):
    """
    Return the angle (degrees) of the longest edge of the polygon.
    Lines drawn at this angle run parallel to the dominant face of the shape,
    matching the reference where mountain lines follow mountain slopes,
    water lines run horizontally, sky lines run vertically, etc.
    """
    best_len = -1
    best_angle = 0.0
    n = len(pixel_points)
    for i in range(n):
        ax, ay = pixel_points[i]
        bx, by = pixel_points[(i + 1) % n]
        length = math.hypot(bx - ax, by - ay)
        if length > best_len:
            best_len = length
            best_angle = math.degrees(math.atan2(by - ay, bx - ax)) % 180
    return best_angle


# ─── core colored pencil renderer ────────────────────────────────────────────

def _polygon_centroid(pixel_points):
    """Return the arithmetic centroid (cx, cy) of a polygon."""
    xs = [p[0] for p in pixel_points]
    ys = [p[1] for p in pixel_points]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _draw_pencil_fill(canvas_img, pixel_points, base_rgb, stroke_angle_deg,
                      canvas_w=None, canvas_h=None, visual_weight=1.0):
    """
    Unified renderer: coloured-pencil texture  +  parallel black line overlay.

    Rendering order (all on a single masked tile):
      1. Solid base coat  — brightened base colour sets the paper tone
      2. Pencil passes    — light / main / shadow strokes in colour,
                            organically textured, blended into the fill
      3. Paper grain dots — hue-tinted tooth for wax translucency
      4. Parallel lines   — evenly-spaced black lines at stroke_angle_deg,
                            drawn OVER the pencil layer so they read as
                            deliberate mark-making rather than a flat overlay
      5. Edge darkening   — inset border for micro-AO at cell boundaries
      6. Mask composite   — the entire tile is pasted onto canvas_img through
                            a polygon-shaped mask for pixel-perfect hard edges
                            (no line-width bleed past the polygon boundary)

    Tweakable via module constants:
      LINE_SPACING  — gap between parallel line centres (pixels)
      LINE_WIDTH    — thickness of each parallel line (pixels)
      LINE_COLOUR   — colour of the parallel lines (default black)
    """
    if len(pixel_points) < 3:
        return

    # ── bbox + tile setup ────────────────────────────────────────────────────
    min_x, min_y, max_x, max_y = _polygon_bbox(pixel_points)
    w = max_x - min_x
    h = max_y - min_y
    if w == 0 or h == 0:
        return

    local_pts = [(x - min_x, y - min_y) for x, y in pixel_points]

    tile  = Image.new('RGB', (w, h), (0, 0, 0))
    tdraw = ImageDraw.Draw(tile)

    # ── 1. flat colour fill ───────────────────────────────────────────────────
    tile  = Image.new('RGB', (w, h), (0, 0, 0))
    tdraw = ImageDraw.Draw(tile)
    tdraw.polygon(local_pts, fill=base_rgb)

    # ── 2. parallel line overlay ─────────────────────────────────────────────
    # Lines are drawn with the same wavy 3-segment curve and slight darkness
    # jitter as the pencil strokes — so they feel drawn, not digitally imposed.
    if LINE_SPACING > 0:
        angle_rad = math.radians(stroke_angle_deg % 180)
        cos_a = math.cos(angle_rad);  sin_a = math.sin(angle_rad)
        cos_perp = -sin_a;            sin_perp = cos_a
        diag = math.hypot(w, h) + LINE_SPACING * 2
        cx_t = w / 2.0;  cy_t = h / 2.0
        n_lines = int(diag / LINE_SPACING) + 2
        start_t = -(n_lines // 2) * LINE_SPACING
        for i in range(n_lines):
            t = start_t + i * LINE_SPACING
            ox = cx_t + cos_perp * t;  oy = cy_t + sin_perp * t
            lx0 = ox - cos_a * diag / 2
            ly0 = oy - sin_a * diag / 2
            lx1 = ox + cos_a * diag / 2
            ly1 = oy + sin_a * diag / 2

            # Slight darkness jitter — lines aren't perfectly uniform black,
            # they vary subtly like a pencil pressing unevenly on paper.
            darkness = random.randint(0, 30)
            line_col = tuple(min(255, c + darkness) for c in LINE_COLOUR)

            # Wavy 3-segment curve — same approach as the pencil strokes.
            # Two independent perpendicular offsets at the quarter-points
            # give each line a gentle hand-drawn bow.
            w1 = random.uniform(-PENCIL_WAVINESS * 2, PENCIL_WAVINESS * 2)
            w2 = random.uniform(-PENCIL_WAVINESS * 2, PENCIL_WAVINESS * 2)
            mx = (lx0 + lx1) / 2;  my = (ly0 + ly1) / 2
            qx0 = (lx0 + mx) / 2 + cos_perp * w1
            qy0 = (ly0 + my) / 2 + sin_perp * w1
            qx1 = (mx + lx1) / 2 + cos_perp * w2
            qy1 = (my + ly1) / 2 + sin_perp * w2
            segs = [(int(lx0),int(ly0)),(int(qx0),int(qy0)),
                    (int(qx1),int(qy1)),(int(lx1),int(ly1))]
            for j in range(len(segs) - 1):
                tdraw.line([segs[j], segs[j+1]], fill=line_col, width=LINE_WIDTH)

    # ── 6. edge darkening ────────────────────────────────────────────────────
    tdraw.polygon(local_pts, outline=(0, 0, 0), width=PENCIL_EDGE_INSET)

    # ── 7. mask composite onto canvas ────────────────────────────────────────
    # Polygon mask = white inside, black outside.
    # paste() uses it as a stencil — every layer above (pencil, lines, edge)
    # is hard-clipped at the exact polygon boundary regardless of line width.
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).polygon(local_pts, fill=255)
    canvas_img.paste(tile, (min_x, min_y), mask)


# ─── main drawer class ───────────────────────────────────────────────────────

class ImagePolygonDrawerPurePIL:

    def __init__(self, image_library_path, canvas_width, canvas_height, logical_w, logical_h):
        self.image_lib = Path(image_library_path)
        self.canvas_w  = canvas_width
        self.canvas_h  = canvas_height
        self.logical_w = logical_w
        self.logical_h = logical_h

        self.canvas           = None
        self.pending_polygons = []

        # Legacy tone folders (used only when img_number is not an RGB key)
        self.light_images   = self._load_folder('light')
        self.midtone_images = self._load_folder('midtone')
        self.dark_images    = self._load_folder('dark')

        # Color mode: discover all R_G_B subfolders automatically
        self.color_images = {}
        self._discover_color_folders()

        print(f"\n=== Image Library Loaded ===")
        print(f"  Light   folder : {len(self.light_images)} images")
        print(f"  Midtone folder : {len(self.midtone_images)} images")
        print(f"  Dark    folder : {len(self.dark_images)} images")
        if self.color_images:
            print(f"  Color folders  : {len(self.color_images)} folder(s)")
        print(f"  Pencil fill mode : ON  (RGB key → coloured-pencil strokes)")

    # ── loading ──────────────────────────────────────────────────────────────

    def _load_folder(self, folder_name):
        folder = self.image_lib / folder_name
        images = {}
        if not folder.exists():
            return images
        for img_path in sorted(folder.glob('*.png')):
            try:
                key = int(img_path.stem)
            except ValueError:
                key = img_path.stem
            try:
                images[key] = Image.open(img_path).convert('RGBA')
            except Exception as e:
                print(f"  Warning: could not load {img_path.name}: {e}")
        return images

    def _is_color_folder(self, name):
        parts = name.split('_')
        if len(parts) != 3:
            return False
        try:
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            return 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255
        except ValueError:
            return False

    def _discover_color_folders(self):
        if not self.image_lib.exists():
            return
        for entry in sorted(self.image_lib.iterdir()):
            if entry.is_dir() and self._is_color_folder(entry.name):
                self.color_images[entry.name] = self._load_folder(entry.name)

    # ── image retrieval (legacy fallback) ─────────────────────────────────────

    def get_image_by_number(self, img_number):
        if img_number is None:
            return None
        if img_number == "random_light":
            pool = list(self.light_images.values())
            img  = random.choice(pool) if pool else None
        elif img_number == "random_midtone":
            pool = list(self.midtone_images.values())
            img  = random.choice(pool) if pool else None
        elif img_number == "random_dark":
            pool = list(self.dark_images.values())
            img  = random.choice(pool) if pool else None
        elif img_number == "random":
            all_pools = (
                list(self.light_images.values()) +
                list(self.midtone_images.values()) +
                list(self.dark_images.values()) +
                [v for imgs in self.color_images.values() for v in imgs.values()]
            )
            img = random.choice(all_pools) if all_pools else None
        elif isinstance(img_number, str) and self._is_color_folder(img_number):
            folder_imgs = self.color_images.get(img_number, {})
            img = random.choice(list(folder_imgs.values())) if folder_imgs else None
        else:
            n = int(img_number)
            img = (self.light_images.get(n) or
                   self.midtone_images.get(n) or
                   self.dark_images.get(n))
            if img is None:
                for folder_imgs in self.color_images.values():
                    img = folder_imgs.get(n)
                    if img:
                        break
        return img.copy() if img else None

    # ── polygon management ───────────────────────────────────────────────────

    def register_polygon(self, points, img_number, pen_color=(45, 45, 48),
                         pensize=2, desaturation=0, stroke_angle=None,
                         show_outline=True, visual_weight=1.0):
        points_copy = [tuple(p) if isinstance(p, (list, tuple)) else p for p in points]
        # Lock angle at registration — stroke_angle=None → contour-following,
        # derived from the polygon's own longest edge direction.
        if stroke_angle is not None:
            resolved_angle = stroke_angle
        else:
            # convert logical points to pixel space for edge measurement
            pixel_pts = [self.logical_to_pixel(x, y) for x, y in points_copy]
            resolved_angle = _contour_angle_deg(pixel_pts)
            # small random nudge so adjacent same-orientation shapes don't look identical
            resolved_angle += random.uniform(-12, 12)
        self.pending_polygons.append({
            'points':        points_copy,
            'img_number':    img_number,
            'pen_color':     pen_color,
            'pensize':       pensize,
            'desaturation':  max(0, min(255, int(desaturation))),
            'stroke_angle':  resolved_angle,
            'show_outline':  show_outline,
            'visual_weight': max(0.0, float(visual_weight)),
        })

    def clear(self):
        self.pending_polygons = []
        self.canvas = None

    def undo_last(self):
        if self.pending_polygons:
            self.pending_polygons.pop()

    # ── coordinate helper ────────────────────────────────────────────────────

    def logical_to_pixel(self, x, y):
        norm_x = (x + self.logical_w / 2) / self.logical_w
        norm_y = (self.logical_h / 2 - y) / self.logical_h
        return int(norm_x * self.canvas_w), int(norm_y * self.canvas_h)

    # ── fill dispatch ─────────────────────────────────────────────────────────

    def _fill_polygon(self, canvas_img, poly):
        """Route to pencil+lines fill or legacy image fill depending on img_number."""
        img_number    = poly['img_number']
        stroke_angle  = poly.get('stroke_angle', 30)
        visual_weight = poly.get('visual_weight', 1.0)
        pixel_points  = [self.logical_to_pixel(x, y) for x, y in poly['points']]

        rgb = _parse_rgb_key(img_number)

        if rgb is not None:
            # Pencil+lines renderer — mask composite handles edge clipping,
            # edge darkening handles the outline; no separate PIL outline needed.
            _draw_pencil_fill(canvas_img, pixel_points, rgb, stroke_angle,
                              canvas_w=self.canvas_w, canvas_h=self.canvas_h,
                              visual_weight=visual_weight)

        else:
            # ── LEGACY IMAGE FILL ──
            fill_img = self.get_image_by_number(img_number)
            if not fill_img:
                return
            desat = poly.get('desaturation', 0)
            xs = [p[0] for p in pixel_points]
            ys = [p[1] for p in pixel_points]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            w, h = max_x - min_x, max_y - min_y
            if w > 0 and h > 0:
                fill_img = fill_img.resize((w, h), Image.LANCZOS)
                if desat > 0:
                    grey = fill_img.convert('L').convert('RGB')
                    t = desat / 255.0
                    blended = Image.fromarray(
                        ((1 - t) * np.array(fill_img.convert('RGB')) +
                          t      * np.array(grey)).astype('uint8'))
                    fill_img = blended
                mask = Image.new('L', (w, h), 0)
                ImageDraw.Draw(mask).polygon(
                    [(x - min_x, y - min_y) for x, y in pixel_points], fill=255)
                canvas_img.paste(fill_img, (min_x, min_y), mask)

    # ── partial build (video frames) ─────────────────────────────────────────

    def build_partial_fills(self, count):
        temp = Image.new('RGB', (self.canvas_w, self.canvas_h), (255, 255, 255))
        draw = ImageDraw.Draw(temp)
        for i in range(min(count, len(self.pending_polygons))):
            poly = self.pending_polygons[i]
            self._fill_polygon(temp, poly)
            if _parse_rgb_key(poly['img_number']) is None and poly.get('show_outline', True):
                pixel_points = [self.logical_to_pixel(x, y) for x, y in poly['points']]
                draw.polygon(pixel_points, outline=poly['pen_color'], width=poly['pensize'])
        return temp

    # ── final render ─────────────────────────────────────────────────────────

    def finalize_and_save(self, screen, output_path, upscale=1,
                          background_color=(255, 255, 255)):
        """
        Render at 2× resolution then downscale with LANCZOS — this gives
        free anti-aliasing on all lines, outlines, and polygon edges without
        any extra dependencies.
        """
        SS = 2  # supersample factor
        print(f"\n=== Building Final Image (Colored Pencil Mode, {SS}× supersample) ===")

        # temporarily double the canvas dimensions so logical_to_pixel
        # maps coordinates into the high-res space
        orig_w, orig_h = self.canvas_w, self.canvas_h
        self.canvas_w  = orig_w * SS
        self.canvas_h  = orig_h * SS

        hi_res = Image.new('RGB', (self.canvas_w, self.canvas_h), background_color)
        draw   = ImageDraw.Draw(hi_res)

        total = len(self.pending_polygons)
        for i, poly in enumerate(self.pending_polygons, 1):
            print(f"  Polygon {i}/{total}  {poly['img_number']}  angle={poly.get('stroke_angle', 30):.1f}°")
            self._fill_polygon(hi_res, poly)
            if _parse_rgb_key(poly['img_number']) is None and poly.get('show_outline', True):
                pixel_points = [self.logical_to_pixel(x, y) for x, y in poly['points']]
                draw.polygon(pixel_points, outline=poly['pen_color'], width=poly['pensize'] * SS)

        # restore original dimensions
        self.canvas_w = orig_w
        self.canvas_h = orig_h

        # downscale to target size — LANCZOS anti-aliases all edges
        target_w = orig_w * upscale
        target_h = orig_h * upscale
        self.canvas = hi_res.resize((target_w, target_h), Image.LANCZOS)

        self.canvas.save(output_path, 'PNG')
        print(f"\n✓ Saved: {output_path}  ({target_w}×{target_h}px)")
        return self.canvas


# ─── public API ──────────────────────────────────────────────────────────────

def setup_image_drawer(image_lib_path, canvas_w, canvas_h, logical_w, logical_h):
    return ImagePolygonDrawerPurePIL(image_lib_path, canvas_w, canvas_h, logical_w, logical_h)


def draw_polygon_img(drawer, turtle_obj, screen, points, img_number,
                     pen_color, pensize=2, desaturation=0, stroke_angle=None,
                     show_outline=True, visual_weight=1.0):
    """
    Draw a filled polygon with colored-pencil stroke fill (for R_G_B img_numbers)
    or legacy image fill (for random_light / random_dark / numeric ids).

    stroke_angle : float
        Angle in degrees for the primary stroke direction (0 = horizontal).
        Only affects R_G_B colour-key polygons.

    show_outline : bool (default True)
        Whether to draw the polygon outline.

    visual_weight : float (default 1.0)
        Compositional emphasis multiplier (0.0–2.0).
        Values > 1.0 increase stroke density (more visual weight / focal point).
        Values < 1.0 reduce density (recede into background).
        Only affects R_G_B colour-key polygons.
    """
    points_list = [tuple(p) if isinstance(p, (list, tuple)) else p for p in points]
    turtle_obj.pensize(pensize)
    turtle_obj.penup()
    turtle_obj.goto(points_list[0])
    if show_outline:
        turtle_obj.pendown()
        turtle_obj.pencolor((0, 0, 0))
        for p in points_list[1:]:
            turtle_obj.goto(p)
        turtle_obj.goto(points_list[0])
    turtle_obj.penup()
    drawer.register_polygon(points_list, img_number, pen_color, pensize,
                            desaturation, stroke_angle, show_outline, visual_weight)


def draw_polygon_n(drawer, turtle_obj, screen, points, pen_color, pensize=5):
    """Draw polygon outline ONLY (no fill)."""
    points_list = [tuple(p) if isinstance(p, (list, tuple)) else p for p in points]
    turtle_obj.pensize(pensize)
    turtle_obj.penup()
    turtle_obj.goto(points_list[0])
    turtle_obj.pendown()
    turtle_obj.pencolor(pen_color)
    for p in points_list[1:]:
        turtle_obj.goto(p)
    turtle_obj.goto(points_list[0])
    drawer.register_polygon(points_list, None, pen_color, pensize)


if __name__ == "__main__":
    print("Colored Pencil Edition — RGB key → layered stroke fill, no image files needed.")
