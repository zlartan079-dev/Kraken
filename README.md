# Kraken Paint — Android app

Kivy port of the Kraken Paint pipeline, packaged for Android via
buildozer/python-for-android, built through GitHub Actions CI.

## The actual workflow (corrected understanding)

Earlier passes at this port wrongly assumed `pv.py`/`main.py` were fixed
artworks and that `image_measure_tool_color.py` was a raster photo tool.
Neither is true. The real workflow, confirmed directly:

1. Draw shapes in Illustrator, fill with the live paint bucket, export as SVG.
2. Load that SVG in the shape picker (`image_measure_tool_color.py` on
   desktop, the **SVG Picker screen** in this app) — it renders every
   filled shape.
3. **Make Colors**: generates a recolored pattern-image library — one
   subfolder per unique SVG fill color (`R_G_B` naming) — by tinting a set
   of source pattern PNGs to match each color.
4. Pick shapes (individually or all at once) — each becomes a polygon
   entry: SVG coordinates converted to turtle-centered coordinates, fill
   color matched to its `R_G_B` folder key.
5. Render: **pv** for a still colored-pencil image, **video** for an
   animated MP4 of the same artwork being drawn.

On desktop, steps 4→5 went through hand-editing `pv.py`/`main.py` source
and copy-pasting generated code via the clipboard. This app skips that
round-trip entirely — picked shapes go straight into an in-memory list
that `pv_pipeline.run()`/`video_pipeline.run()` take as a `polygons`
parameter.

## Porting status

| Piece | Status |
|---|---|
| `core/svg_parser.py` | Ported verbatim from `image_measure_tool_color.py`'s SVG parsing — pure Python (re, xml.etree), no changes needed |
| `core/color_classify.py` | Ported `classify_color_group`, refactored to take the SVG's palette as a parameter instead of a module global |
| `core/make_colors.py` | Ported the recoloring logic — takes a list of pattern file paths (multi-file picker) instead of a picked folder |
| `core/svg_canvas_widget.py` | **New** — touch equivalent of the desktop's tkinter Canvas render+pick. Uses `kivy.graphics.tesselator.Tesselator` for correct concave-polygon fill (a naive triangle-fan would render concave letterform/illustration shapes wrong). Verified against a synthetic concave (L-shaped) test polygon under Xvfb — tapping the shape's notch correctly falls through to the shape underneath rather than false-hitting the L. |
| `core/color_wheel.py` | Ported as-is |
| `core/five_point_perspective.py` | Ported — tkinter dialogs swapped for the file picker |
| `core/simplify_shapes.py` | Ported — tkinter UI removed, `sklearn.KMeans` replaced with `cv2.kmeans` (no p4a recipe for sklearn) |
| `core/polygon_render.py` | Ported verbatim from `polygon_with_images_final.py` — no tkinter/turtle imports to begin with |
| `core/pv_pipeline.py` | Rebuilt generic: takes a `polygons` list parameter instead of one hardcoded artwork. `turtle.Turtle()/Screen()` replaced with no-op stand-ins (`turtle_stub.py`) — safe because `finalize_and_save()` never reads the screen object. |
| `core/video_pipeline.py` | Rebuilt generic, same `polygons` parameter. Also rebuilt the frame-capture mechanism itself: desktop screenshots a live tkinter Canvas via Ghostscript/postscript per frame — impossible on Android — replaced with drawing directly onto a PIL layer and writing composited frames straight to `cv2.VideoWriter`, no per-frame PNGs on disk. |
| `core/sample_artwork.py` | The two baked artworks originally hardcoded in `pv.py`/`main.py`, kept as fallback demo data (cross-checked programmatically against the source, not hand-transcribed) — used only when nothing's been picked from an SVG yet |
| `image_measure_tool_color.py`'s raster flood-fill fallback mode | **Not ported.** SVG mode is the confirmed primary workflow; the flood-fill/contour-tracing fallback for when no SVG exists is a separate, still-unbuilt feature |

## Why folder-pickers were removed

Testing on-device showed "Choose output folder" and "Choose image library
folder" buttons doing nothing. Root cause: Android's Storage Access
Framework directory picker (`ACTION_OPEN_DOCUMENT_TREE`) is unreliable
through `plyer`'s `choose_dir`. Rather than fight that, `image_lib_path`
and `output_dir` are now fixed, app-managed directories
(`App.user_data_dir/image_library` and `App.user_data_dir/output`) that
need no picker and no special permission at all. Only genuine **file**
selection (SVG, pattern images, input photos) uses `plyer.open_file`,
which was confirmed working on-device (single and multi-select both use
the same code path).

## Local testing before shipping to CI

Given how expensive each CI/on-device cycle is, this pass was tested
locally as far as possible before being packaged:

- Kivy installed headless in a sandbox, run under Xvfb (a real virtual
  display, not just import-checking).
- `SvgCanvasWidget` tested with a synthetic concave polygon: coordinate
  transform round-trips verified exact, touch hit-testing verified to
  pick the correct shape and correctly reject points in a concave
  cut-out (a real bug — a callback double-firing on every touch — was
  caught and fixed this way, from a Kivy naming-convention collision:
  don't name callback properties `on_<x>`, Kivy's EventDispatcher treats
  that specially).
- Full app wiring exercised end-to-end (all 9 screens constructed, SVG
  loaded and picked, Make Colors palette display, color wheel slider
  math) under Xvfb.
- Full pipeline run end-to-end with real image output: synthetic SVG →
  `make_colors()` → `pv_pipeline.run()` → rendered PNG, visually confirmed
  correct (colors, z-order, and the concave shape's cut-out corner all
  rendered right).
- `video_pipeline.run()` run end-to-end, produced a valid MP4 locally
  with opencv-python-headless.

None of this replaces on-device testing — Kivy's touch handling, file
picker behavior, and Android's opencv build all have platform-specific
behavior a desktop Xvfb run can't fully cover — but it should catch
another round of "the button does nothing" bugs before costing another
multi-hour CI cycle.

## Repo structure

```
kraken_paint_android/
  main.py                    Kivy app — 9 screens (see Screens below)
  core/
    svg_parser.py             SVG parsing (rect/polygon/path/polyline/line, transforms)
    svg_canvas_widget.py       Kivy touch-pick widget, Tesselator-based fill rendering
    color_classify.py          classify_color_group (palette-based + legacy fallback)
    make_colors.py             pattern-recoloring pipeline
    color_wheel.py             12-color-wheel matcher
    polygon_render.py          PIL-based fill/stroke renderer (from polygon_with_images_final.py)
    turtle_stub.py             no-op turtle/screen stand-ins
    pv_pipeline.py             still-image render, generic polygons param
    video_pipeline.py          animated MP4 render, generic polygons param
    five_point_perspective.py
    simplify_shapes.py
    sample_artwork.py          fallback demo data (both baked artworks)
  buildozer.spec
  .github/workflows/build-apk.yml
```

## Screens

1. **SVG Picker** — load SVG, tap shapes or "Pick All", queues polygons
2. **Make Colors** — generate the recolored pattern library from the loaded SVG's palette
3. **Colored-Pencil Render (pv)** — still image from queued polygons
3. **Animated Video Render (main)** — MP4 from queued polygons
4. **Five-Point Perspective** — standalone image tool
5. **Shape Simplifier** — standalone image tool
6. **Color Wheel Lookup** — real RGB-slider picker
7. **Image Region Tool** — stub (raster fallback mode, unported)

## Workflow: Termux + GitHub → APK

1. **Termux** (editing/version control only — the actual compile happens in CI):
   ```
   git add -A && git commit -m "..." && git push
   ```
2. **GitHub Actions** builds automatically on push to `main`, or via manual
   `workflow_dispatch`. First build compiles opencv/numpy from source —
   expect 45–90+ minutes; this is normal.
3. **Download the APK** from the workflow run's Artifacts section, sideload
   onto your phone.

## Known follow-ups

- **`cv2.VideoWriter` codec support is a real risk on Android.** The p4a
  opencv recipe may lack FFmpeg backend support, which `mp4v` relies on.
  Test this specifically once the APK builds. Fallbacks: `MediaCodec`/
  `MediaMuxer` via pyjnius, or bundling a static ffmpeg binary.
- `image_measure_tool_color.py`'s raster flood-fill fallback mode — not
  ported. Build if it turns out to be needed alongside the SVG mode.
- `SvgCanvasWidget` was tested under Xvfb with synthetic shapes, not a
  real Illustrator-exported SVG or an actual touchscreen — worth testing
  with a real file early.
- Very large/complex SVGs (many hundreds of shapes) may render slowly
  given each filled shape gets its own `Tesselator` + `Mesh` pass — worth
  profiling on-device if load times become noticeable.
