# H3Loom typography film — Three.js

The 24-second H3Loom homepage film, rendered locally with Three.js. It adapts selected typography mechanisms from an Apple-style reference to H3Loom's text. The product is a conceptual cloud runtime, not real H3 generation output. Motion curves are authored fits, not recovered original curves.

All picture geometry, materials, light fields, motion and music are authored in code. No cloud image/video generation, Remotion or HyperFrames is used. The reference footage is not bundled.

## Run

Requires Node.js, FFmpeg, local Google Chrome, and the macOS DIN Condensed Bold and Arial fonts. Fonts are served from the local operating system and are not copied into this repository. `CHROME_EXECUTABLE` and `FFMPEG` may override executable locations. Font mappings are in `serve.mjs`.

```sh
cd media/intro-three
npm ci
npm run serve
```

Open `http://127.0.0.1:8790/` for the live Three.js timeline. It supports frame stepping, scrubbing, 0.25×/0.5× playback and a plot of the named motion parameter. `watch.html` plays the completed MP4 with its soundtrack after a build.

```sh
npm run build
npm run verify
```

The latest output is `outputs/intro-three/h3loom-type-metal.mp4` relative to the repository root. The build renders 1,440 deterministic frames at 1920×1080 / 60 fps, synthesizes an original 48 kHz stereo score, and muxes H.264/AAC with fast-start metadata. Output files are ignored by Git. `node build.mjs --mux-only` rebuilds the soundtrack and muxes an already rendered silent picture.

For shorter iterations:

```sh
node render.mjs --start=13.2 --duration=2 --fps=60 --output=outputs/intro-three/sample.mp4
node render.mjs --stills=5.933333,6.25,6.42,9,13.2,13.62,14.1,14.6
```

## Motion design

- `reference-analysis.md`: consecutively sampled reference evidence, estimated screen rectangles and clearly separated fitting suggestions.
- `motion-score.js`: shot boundaries and piecewise Hermite curves with explicit time/value/velocity knots.
- `scene.js`: independent type width/height, shared layout displacement, product rotation, chip framing and reading holds.
- `type-kit.js`: actual beveled text geometry, procedurally constructed studio environment and controlled metal reflection fields.
- `audio.cjs`: deterministic local oscillator/noise synthesis timed to the edit.
- `quality-review.md`: targeted comparison findings and subsequent corrections.

The reference's fast collage handoffs are deliberately concentrated in roughly 42–83 ms, followed by a much longer small settle. RENDER stays still while its reflected field moves. Chip typography changes its occupied rectangle independently of the surrounding frame. These are fitted mechanisms, not measured original 3D camera paths. The display font and synthetic cloud device differ from the reference's original assets.

## Initial study validation (2026-09-12)

The local Metal GPU build produced a 24.000-second, 1,440-frame 1080p60 picture and a 24.000-second AAC track. Final MP4: 3,700,473 bytes. Full video/audio decoding passed. A 7-time-point, 21-return seek test produced pixel-identical results, with no JavaScript errors or external dependency requests. The tested source hashes match the final rendered scene.

The picture's render-and-encode stage took 48.91 seconds on this Apple M5 Pro (Chrome 153); this excludes dependency installation, scene startup and the much longer analysis/design work. It is not a general performance guarantee. Evidence receipts and comparison frames are in the ignored `outputs/intro-three/` directory.

## Transition revision (2026-09-12)

The first study treated too many shots as independent resettable scenes. `composeConnected` now retains multiple actors across those markers: FROM/SRT becomes a larger sentence layout; the die recedes beneath RENDER; RENDER remains as the heading while 4K becomes a solid metallic result; that same 4K becomes a label in the next product cell; the final verbs move along one shared vertical strip. The intentional WITH/product cut now matches the silver subject footprint. These joins are authored H3Loom adaptations informed by the reference, not a claim that the source film contains these exact joins.

`transition-reference.md` records the observed reference evidence. The local player can compare the previous 3.7 MB study at the same playhead position if that earlier build is present. Latest encoded output is 24 seconds, 1080p60, 5,301,316 bytes. Full audio/video decoding passed. The new shared-actor scene passed 80 seek-return comparisons at 16 transition-focused timestamps; this verifies deterministic state, not aesthetic equivalence to the source. Receipts: `outputs/intro-three/connected-seek.json` and `h3loom-type-connected-silent.mp4.json`.

## Connected version publication and retrospective

The connected-transitions version was the first Three.js homepage film. It has since received the metallic face correction below; all five READMEs embed the current complete silent animated WebP preview. The [public player](https://erduo1998-cell.github.io/h3loom/) provides the 1080p60 version with sound. The reusable analysis and correction process is recorded in [the Chinese retrospective](RETROSPECTIVE.zh-CN.md).

The earlier connected MP4 SHA-256 is `55a6ec07521aae1b5e291842f9a147f5652e43a88fa50925331f6273db1a5125`. Preview generation reuses `media/intro/readme-animation.py` from the repository root: `uv run --with pillow python media/intro/readme-animation.py`. It samples the complete movie at 800×450 / 24 fps; the WebP encoder merges identical held frames while preserving the 24-second loop.

## Metallic face correction (2026-09-12)

The subsequent material review found that most title faces were unlit white, with metallic material only on thin side walls. The current homepage version uses silver physical material on the complete title, more visible bevels and 0.16-unit extrusion. Finite virtual studio cards produce readable highlight/negative-fill bands; RENDER and 4K retain restrained blue/violet accents. This is a designed reflection approximation, not offline path tracing.

The shot timings, camera/layout tracks and soundtrack are unchanged from the approved connected version. The prior connected MP4 is retained locally for same-time comparison. The material revision passed 33 pixel-identical seek returns across 11 timestamps, full audio/video decode and complete browser playback. These checks establish playback/state integrity; they do not claim a fresh owner aesthetic approval. Current distributed asset hashes are in `docs/media/provenance.json`.
