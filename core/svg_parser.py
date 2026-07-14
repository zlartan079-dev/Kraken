"""
core/svg_parser.py — Android port
=====================================
Ported verbatim from image_measure_tool_color.py's parsing functions.
These were already pure Python (re, xml.etree) with zero tkinter
dependency on the desktop — nothing needed changing here, just moving
it out of the tkinter-app file so it's usable standalone in Kivy.

parse_svg(path) -> (shapes, viewbox)
  shapes: list of {"points": [(x,y),...], "color": (r,g,b) or None, "filled": bool}
  viewbox: (vbx, vby, vbw, vbh)
"""

import re
import xml.etree.ElementTree as ET


def hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def parse_fill_value(v):
    v = v.strip()
    if v == "none":
        return None
    if v.startswith("#"):
        return hex_to_rgb(v)
    m = re.match(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', v)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    _NAMED = {
        "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
        "green": (0, 128, 0), "lime": (0, 255, 0), "blue": (0, 0, 255),
        "yellow": (255, 255, 0), "orange": (255, 165, 0), "purple": (128, 0, 128),
        "pink": (255, 192, 203), "brown": (165, 42, 42), "grey": (128, 128, 128),
        "gray": (128, 128, 128), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
        "navy": (0, 0, 128), "teal": (0, 128, 128), "maroon": (128, 0, 0),
        "olive": (128, 128, 0), "coral": (255, 127, 80), "salmon": (250, 128, 114),
        "gold": (255, 215, 0), "ivory": (255, 255, 240), "khaki": (240, 230, 140),
        "lavender": (230, 230, 250), "linen": (250, 240, 230), "beige": (245, 245, 220),
        "indigo": (75, 0, 130), "violet": (238, 130, 238), "turquoise": (64, 224, 208),
        "sienna": (160, 82, 45), "tan": (210, 180, 140), "wheat": (245, 222, 179),
        "crimson": (220, 20, 60), "tomato": (255, 99, 71), "chocolate": (210, 105, 30),
        "darkblue": (0, 0, 139), "darkgreen": (0, 100, 0), "darkred": (139, 0, 0),
        "darkorange": (255, 140, 0), "deeppink": (255, 20, 147), "hotpink": (255, 105, 180),
        "skyblue": (135, 206, 235), "steelblue": (70, 130, 180), "lightblue": (173, 216, 230),
        "lightgreen": (144, 238, 144), "lightgrey": (211, 211, 211), "lightgray": (211, 211, 211),
        "silver": (192, 192, 192), "aqua": (0, 255, 255), "fuchsia": (255, 0, 255),
    }
    named = _NAMED.get(v.lower())
    if named:
        return named
    return None


def parse_style_block(svg_text):
    result = {}
    m = re.search(r'<style[^>]*>(.*?)</style>', svg_text, re.DOTALL)
    if not m:
        return result
    css = m.group(1)
    for rule in re.finditer(r'([^{]+)\{([^}]+)\}', css):
        selectors = rule.group(1)
        props = rule.group(2)
        fill_m = re.search(r'fill\s*:\s*([^;]+)', props)
        fill_val = fill_m.group(1).strip() if fill_m else None
        for sel in selectors.split(','):
            sel = sel.strip().lstrip('.')
            if fill_val is None or fill_val == 'none':
                result[sel] = None
            else:
                parsed = parse_fill_value(fill_val)
                if parsed is not None:
                    result[sel] = parsed
    return result


def resolve_fill(elem, style_map):
    cls = elem.get("class", "")
    for c in cls.split():
        if c in style_map:
            return style_map[c]
    style_attr = elem.get("style", "")
    fm = re.search(r'fill\s*:\s*([^;]+)', style_attr)
    if fm:
        return parse_fill_value(fm.group(1))
    fill_attr = elem.get("fill", "")
    if fill_attr:
        return parse_fill_value(fill_attr)
    return None


def is_explicitly_unfilled(elem, style_map):
    cls = elem.get("class", "")
    for c in cls.split():
        if c in style_map and style_map[c] is None:
            return True
    style_attr = elem.get("style", "")
    if re.search(r'fill\s*:\s*none', style_attr):
        return True
    if elem.get("fill", "") == "none":
        return True
    return False


def parse_transform(transform_str):
    a, b, c, d, e, f = 1.0, 0.0, 0.0, 1.0, 0.0, 0.0

    def mat_mul(m1, m2):
        a1, b1, c1, d1, e1, f1 = m1
        a2, b2, c2, d2, e2, f2 = m2
        return (
            a1*a2 + c1*b2, b1*a2 + d1*b2,
            a1*c2 + c1*d2, b1*c2 + d1*d2,
            a1*e2 + c1*f2 + e1, b1*e2 + d1*f2 + f1,
        )

    for fn, args_str in re.findall(r'(\w+)\s*\(([^)]+)\)', transform_str):
        nums = [float(x) for x in re.findall(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', args_str)]
        if fn == 'matrix' and len(nums) == 6:
            m = tuple(nums)
        elif fn == 'translate':
            tx = nums[0]; ty = nums[1] if len(nums) > 1 else 0.0
            m = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif fn == 'scale':
            sx = nums[0]; sy = nums[1] if len(nums) > 1 else nums[0]
            m = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        else:
            continue
        a, b, c, d, e, f = mat_mul((a, b, c, d, e, f), m)

    return (a, b, c, d, e, f)


def apply_transform(pts, mat):
    a, b, c, d, e, f = mat
    return [(a*x + c*y + e, b*x + d*y + f) for x, y in pts]


def combine_transforms(parent_mat, child_transform_str):
    if not child_transform_str:
        return parent_mat
    child_mat = parse_transform(child_transform_str)
    a1, b1, c1, d1, e1, f1 = parent_mat
    a2, b2, c2, d2, e2, f2 = child_mat
    return (
        a1*a2 + c1*b2, b1*a2 + d1*b2,
        a1*c2 + c1*d2, b1*c2 + d1*d2,
        a1*e2 + c1*f2 + e1, b1*e2 + d1*f2 + f1,
    )


def strip_closing(pts):
    if len(pts) > 1 and pts[0] == pts[-1]:
        return pts[:-1]
    return pts


def parse_path_d(d):
    if re.search(r'[CcSsQqTtAa]', d):
        return None

    tokens = re.findall(r'[MLZmlzHhVv]|[-+]?(?:[0-9]+\.?[0-9]*|\.?[0-9]+)(?:[eE][-+]?[0-9]+)?', d)
    subpaths = []; current = []
    cmd = None; cx, cy = 0.0, 0.0; sx, sy = 0.0, 0.0; i = 0

    while i < len(tokens):
        t = tokens[i]
        if t in 'MLHhVvml':
            cmd = t; i += 1; continue
        if t in ('Z', 'z'):
            if current:
                if (sx, sy) != (cx, cy): current.append((sx, sy))
                subpaths.append(current); current = []
            cx, cy = sx, sy; cmd = None; i += 1; continue
        if cmd in ('M', 'L'):
            x, y = float(tokens[i]), float(tokens[i+1])
            cx, cy = x, y
            if cmd == 'M':
                if current: subpaths.append(current)
                current = []; sx, sy = x, y
            current.append((x, y)); i += 2
            if cmd == 'M': cmd = 'L'
        elif cmd in ('m', 'l'):
            x, y = cx+float(tokens[i]), cy+float(tokens[i+1])
            cx, cy = x, y
            if cmd == 'm':
                if current: subpaths.append(current)
                current = []; sx, sy = x, y
            current.append((x, y)); i += 2
            if cmd == 'm': cmd = 'l'
        elif cmd == 'H': cx = float(tokens[i]); current.append((cx, cy)); i += 1
        elif cmd == 'h': cx += float(tokens[i]); current.append((cx, cy)); i += 1
        elif cmd == 'V': cy = float(tokens[i]); current.append((cx, cy)); i += 1
        elif cmd == 'v': cy += float(tokens[i]); current.append((cx, cy)); i += 1
        else: i += 1

    if current: subpaths.append(current)

    result = []
    for pts in subpaths:
        if len(pts) >= 2: result.append(pts)
    return result if result else None


def parse_points_attr(s):
    nums = re.findall(r'[-+]?[0-9]*\.?[0-9]+', s)
    pts = [(float(nums[i]), float(nums[i+1])) for i in range(0, len(nums)-1, 2)]
    pts = strip_closing(pts)
    return pts if len(pts) >= 3 else None


def parse_svg(path):
    """Parse SVG file. Returns (shapes_list, viewbox_tuple)."""
    with open(path, 'r', encoding='utf-8') as f:
        svg_text = f.read()

    style_map = parse_style_block(svg_text)

    clean = re.sub(r'\sxmlns(?::[^=]+)?="[^"]*"', '', svg_text)
    clean = re.sub(r'<([a-zA-Z]+):[a-zA-Z]', '<', clean)
    clean = re.sub(r'</([a-zA-Z]+):[a-zA-Z]', '</', clean)

    root = ET.fromstring(clean)

    vb = root.get("viewBox", "")
    vb_nums = re.findall(r'[-+]?[0-9]*\.?[0-9]+', vb)
    if len(vb_nums) == 4:
        vbx, vby, vbw, vbh = [float(v) for v in vb_nums]
    else:
        vbx, vby = 0.0, 0.0
        vbw = float(root.get("width", 500))
        vbh = float(root.get("height", 500))
    viewbox = (vbx, vby, vbw, vbh)

    shapes = []
    IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def walk(elem, inherited_mat=IDENTITY, in_clippath=False):
        tag = elem.tag.split('}')[-1].lower()
        if tag == "clippath":
            return

        color = resolve_fill(elem, style_map)
        unfilled = is_explicitly_unfilled(elem, style_map)
        mat = combine_transforms(inherited_mat, elem.get("transform", ""))

        if tag == "rect":
            try:
                x = float(elem.get("x", 0)); y = float(elem.get("y", 0))
                w = float(elem.get("width", 0)); h = float(elem.get("height", 0))
                if w > 0 and h > 0:
                    pts = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]
                    pts = apply_transform(pts, mat)
                    shapes.append({"points": pts, "color": color, "filled": not unfilled})
            except (ValueError, TypeError):
                pass
        elif tag == "polygon":
            pts = parse_points_attr(elem.get("points", ""))
            if pts and len(pts) >= 3:
                pts = apply_transform(pts, mat)
                shapes.append({"points": pts, "color": color, "filled": not unfilled})
        elif tag == "path":
            subpaths = parse_path_d(elem.get("d", ""))
            if subpaths:
                for pts in subpaths:
                    if len(pts) >= 3:
                        pts = apply_transform(pts, mat)
                        shapes.append({"points": pts, "color": color, "filled": not unfilled})
        elif tag == "polyline":
            pts = parse_points_attr(elem.get("points", ""))
            if pts and len(pts) >= 2:
                pts = apply_transform(pts, mat)
                shapes.append({"points": pts, "color": color, "filled": False})
        elif tag == "line":
            try:
                pts = [
                    (float(elem.get("x1", 0)), float(elem.get("y1", 0))),
                    (float(elem.get("x2", 0)), float(elem.get("y2", 0))),
                ]
                pts = apply_transform(pts, mat)
                shapes.append({"points": pts, "color": color, "filled": False})
            except (ValueError, TypeError):
                pass

        for child in elem:
            walk(child, mat)

    walk(root)
    return shapes, viewbox


# ─── geometry helpers (also verbatim) ──────────────────────────────────────

def polygon_centroid(points):
    n = len(points)
    return sum(p[0] for p in points)/n, sum(p[1] for p in points)/n


def point_in_polygon(px, py, poly):
    """Ray-casting: returns True if (px,py) is inside poly."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj-xi)*(py-yi)/(yj-yi)+xi):
            inside = not inside
        j = i
    return inside


def polygon_area(pts):
    n = len(pts)
    area = 0
    for i in range(n):
        j = (i+1) % n
        area += pts[i][0]*pts[j][1] - pts[j][0]*pts[i][1]
    return abs(area) / 2


def svg_to_cart(sx, sy, viewbox):
    """SVG space -> turtle centered coords (matches desktop svg_to_cart)."""
    vbx, vby, vbw, vbh = viewbox
    px = sx - vbx - vbw / 2
    py = -(sy - vby - vbh / 2)
    return int(round(px)), int(round(py))
