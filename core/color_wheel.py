"""
color_wheel.py — Find the closest 12-colour wheel colour for any RGB value,
returned as highlight, midtone, or shadow variant based on input brightness.
"""

import colorsys

# Each entry: (name, hue_center, highlight_rgb, midtone_rgb, shadow_rgb)
COLOR_WHEEL = [
    ("Red",           0,   (255, 120, 120), (255,   0,   0), (139,   0,   0)),
    ("Red-Orange",   15,   (255, 150, 100), (255,  64,   0), (160,  30,   0)),
    ("Orange",       39,   (255, 210, 130), (255, 165,   0), (180, 100,   0)),
    ("Yellow-Orange",50,   (255, 230, 150), (255, 200,   0), (180, 130,   0)),
    ("Yellow",       60,   (255, 255, 150), (255, 255,   0), (180, 180,   0)),
    ("Yellow-Green", 90,   (190, 255, 130), (128, 255,   0), ( 70, 150,   0)),
    ("Green",       120,   (100, 210, 100), (  0, 128,   0), (  0,  64,   0)),
    ("Blue-Green",  150,   ( 80, 200, 180), (  0, 128, 128), (  0,  64,  64)),
    ("Cyan",        180,   (150, 255, 255), (  0, 255, 255), (  0, 139, 139)),
    ("Blue",        240,   (100, 149, 255), (  0,   0, 255), (  0,   0, 139)),
    ("Blue-Violet", 255,   (150, 120, 210), ( 75,   0, 130), ( 40,   0,  80)),
    ("Violet",      270,   (200, 100, 200), (128,   0, 128), ( 64,   0,  64)),
    ("Red-Violet",  330,   (255, 100, 180), (199,  21, 133), (120,   0,  80)),
]

ACHROMATICS = [
    ("Black",      (  0,   0,   0), (  0,   0,   0), (  0,   0,   0)),
    ("Dark Grey",  ( 90,  90,  90), ( 64,  64,  64), ( 30,  30,  30)),
    ("Grey",       (180, 180, 180), (128, 128, 128), ( 80,  80,  80)),
    ("Light Grey", (230, 230, 230), (192, 192, 192), (150, 150, 150)),
    ("White",      (255, 255, 255), (255, 255, 255), (230, 230, 230)),
]

def rgb_to_hsl(r, g, b):
    h, l, s = colorsys.rgb_to_hls(r/255, g/255, b/255)
    return h * 360, s * 100, l * 100

def get_tone(l):
    """Classify lightness into highlight, midtone, or shadow."""
    if l >= 60:  return "highlight", 0
    if l >= 30:  return "midtone",   1
    return       "shadow",           2

def closest_color(r, g, b):
    h, s, l = rgb_to_hsl(r, g, b)
    tone_name, tone_idx = get_tone(l)

    if l < 10:
        entry = ACHROMATICS[0]
        return entry[0], "shadow", entry[3]
    if l > 90:
        entry = ACHROMATICS[4]
        return entry[0], "highlight", entry[1]
    if s < 12:
        if l < 35:   entry = ACHROMATICS[1]
        elif l < 65: entry = ACHROMATICS[2]
        else:        entry = ACHROMATICS[3]
        return entry[0], tone_name, entry[1 + tone_idx]

    best, best_dist = None, float("inf")
    for entry in COLOR_WHEEL:
        center = entry[1]
        dist = abs(h - center)
        dist = min(dist, 360 - dist)
        if dist < best_dist:
            best_dist = dist
            best = entry

    name = best[0]
    rgb  = best[2 + tone_idx]   # index 2=highlight, 3=midtone, 4=shadow
    return name, tone_name, rgb


def main():
    print("── 12-Colour Wheel Matcher ──")
    print("Returns highlight / midtone / shadow variant based on input brightness.")
    print("Type 'q' to quit.\n")

    while True:
        raw = input("RGB (r, g, b): ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            break
        try:
            parts = [x.strip() for x in raw.replace(",", " ").split()]
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            assert all(0 <= v <= 255 for v in (r, g, b))
        except:
            print("  ✗ Invalid input. Try: 255, 120, 30\n")
            continue

        name, tone, rgb = closest_color(r, g, b)
        print(f"  → {name} ({tone})  RGB{rgb}\n")

if __name__ == "__main__":
    main()
