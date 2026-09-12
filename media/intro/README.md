# H3Loom introduction film

A 24-second, 1920 × 1080, 30 fps product introduction, built from local code.
`film.py` creates the geometry, materials, moving lights, camera choreography,
type layouts, storyboard views and progressive surface reveal in Blender.
`finish.cjs` adds original synthesized audio and readable project captions with
Canvas, then encodes H.264/AAC with FFmpeg.

No cloud model, AI-generated image/video, stock footage, Apple footage/music,
Remotion or HyperFrames is used. The separate README workflow illustration is
not an input. The silver module is a visual metaphor for the runtime, not a
physical product. Its storyboard views are not H3 output-quality evidence.

## Build

Use Blender 5.2, Node.js 22+, and FFmpeg with libx264:

```sh
cd media/intro
npm ci --ignore-scripts
npm run stills
npm run render
```

The wrapper starts a fresh background Blender process with factory defaults; it
does not edit an open scene. It uses local EEVEE ray tracing and 48 render samples.
Cycles remains available for material comparisons through the Python CLI.

Outputs go to ignored `outputs/promo-v2-final/`. The renderer preserves completed
PNG frames so an interrupted render can resume. **After changing the scene or
timing, use a new output directory or move the old frame set aside** to avoid
mixing revisions. `npm run encode` requires all 720 frames and rebuilds the film.

On macOS the wrapper discovers Blender in Applications. Elsewhere set
`BLENDER_BIN`. Fonts come from the OS and are not redistributed; to use other
installed fonts, set `H3LOOM_FILM_FONT`, `H3LOOM_LABEL_FONT`, and
`H3LOOM_CHINESE_FONT`. The default title font is DIN Condensed Bold, labels use
Arial, and Chinese overlays explicitly load Arial Unicode. Different fonts
change the result.

## Review

Serve the repository locally with a server supporting HTTP byte ranges, then
open [review.html](review.html). It provides normal/slow playback, eight-frame
steps and chapter markers. See [motion-study.md](motion-study.md) for the observed
reference mechanisms and the hand-coded timeline.

The user-selected reference is
[The New Mac Studio with M5 Max and M5 Ultra](https://www.youtube.com/watch?v=3uAIqqg8ZHo).
The study uses the relationship between type, objects, light and tempo. It does
not claim frame-exact equivalence to the original commercial.

The earlier 36-second Canvas-only film was rejected and removed from the build
entry points. Its local working files remain outside the release snapshot.
