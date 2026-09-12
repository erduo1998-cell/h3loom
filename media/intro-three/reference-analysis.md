# Three.js remake: reference motion analysis

Reference: [The New Mac Studio with M5 Max and M5 Ultra](https://www.youtube.com/watch?v=3uAIqqg8ZHo), supplied by the owner. Examined in the YouTube player on 2026-09-12. No reference footage or Apple artwork is bundled with this project.

## Evidence and limits

This pass inspected the actual moving reference with the browser player, then advanced through successive frames rather than judging isolated mood-board images. The player advances approximately 0.041666 seconds per `.` keypress, equivalent to 24 steps per second. Four-frame samples cover 5.00–6.92, 50.04–51.54 and 63.54–66.04 seconds; individual successive frames additionally cover 63.916–64.417 seconds. A brief normal-play pass confirmed that the later final collage keeps its layout while product cells move. The decisive timing evidence below comes from paused consecutive frames, not an assertion that a screenshot API provides uninterrupted human-like video perception.

Times are the browser video's `currentTime`, checked against the decoded picture. Seeking can briefly leave an older picture visible; those stale seek frames were excluded. Display time does not prove the source's exact original frame rate or an original animation keyframe. Estimated bounds use the displayed 880 × 495 video rectangle, with about 1–2% uncertainty. Video controls and captions obscure parts of the lower edge.

**Observed** below means visible screen-space change. **Suggested fit** means our reconstruction choice. A 2D image cannot uniquely distinguish an object scale change from a camera dolly or recover Apple's original interpolation curves.

## A. WITH → product rear → model name → chip

| Browser time | Observed composition and change |
| --- | --- |
| 5.000 | WITH nearly fills the video. Extremely tall condensed capitals, approximately 90% of width and 90% of height. Neutral silver face, dark upper reflection, no colored glow. |
| 5.250 | Height remains essentially constant; width is a little larger, approximately 93%. The word is breathing horizontally, not bouncing toward camera. |
| 5.417 | Product rear is present. A cut occurs within the 5.250–5.417 interval; there is no observed word fading through the product. |
| 5.583–5.750 | Rear face rotates toward a flatter view. Product occupies most width; lower underside visibility decreases. |
| 5.917 | Hard change to huge two-line M5 / MAX, filling most of the image. |
| 6.083 | Apple mark has joined the first row. Composition and first-row width rebalance. The type is still huge. |
| 6.250 | Large mark/type block, roughly 58% video width. MAX is almost as wide as the upper row. |
| 6.417 | The block has rapidly become a label inside a blue/violet-edged chip. Chip roughly 40% video width; label about 25%. MAX is now substantially narrower than the upper mark/M5 row. |
| 6.583 | Chip width about 31%; speed of contraction has fallen sharply. |
| 6.750 | Chip width about 29.5%; broad pale reflection moves across it. |
| 6.917 | Chip width about 29%; movement nearly settled. Reflection can temporarily reduce label contrast. |

The mechanism contains **three separately authored changes**: the typography arrangement, the scale contraction, and the reflected light. Shrinking a single group with one uniform ease misses the changing MAX-to-M5 width ratio and the sudden speed burst.

Suggested fit for the remake: begin with a gentle scale drift; put the main contraction inside a short 0.15–0.20 second interval, followed by 0.35–0.50 seconds of diminishing motion. Move the second line's width/height independently as it becomes a physical label. Preserve a clear hard cut before the huge type. The exact acceleration before 6.25 was not measured at single-frame density, so do not label a guessed Bezier as recovered source data.

## B. RENDER: nearly stationary type, moving material

Successive samples: 50.042, 50.208, 50.375, 50.542, 50.708, 50.875 seconds.

- RENDER occupies approximately 58–59% of the frame width and 56.5% of its height. It is centered horizontally and vertically, leaving generous black around it.
- Top and bottom edges remain almost perfectly fixed over this interval. Any horizontal change is only a few pixels. This is a reading hold, not a repeated zoom preset.
- The palette moves continuously across letter faces: deep indigo/blue, lavender, desaturated pink, warm pale cream. A broad pale patch travels through different letters; it does not illuminate each letter independently in sequence.
- Faces show broad smooth transitions and thin bright edge details. Black holes/counters and the background stay black. The effect is reflective metal with moving illumination, not a luminous neon outline or a uniformly glowing purple object.
- By 51.042 the next scene is visible: a robot wireframe with already solid lower regions. The cut happens after the 50.875 sample and before 51.042. There is no observed end-of-word shrink or fade.
- Between 51.042 and 51.542 the solid, blue metallic representation progresses from the lower torso up toward shoulders and neck. This connects the word's meaning to the following action.

Suggested fit: keep type transforms effectively fixed for this beat. Animate a low-frequency continuous reflected field across the entire word, combined with genuine beveled edge response. Reflection timing must be independent of text position. Retain black rather than filling the frame with blue ambient haze. Cut directly into the next representational change.

## C. ONE → MORE → TIME: shared layout, rapid displacement, long tail

This is the most useful reconstruction target for the owner's concern about initial/middle/final speed.

| Time | Observed state |
| --- | --- |
| 63.542 | ONE is above the large product front. Product partly overlaps the lower part of the word at this moment. |
| 63.708 | ONE clears above the product. Word width about 67% of frame, height about 26%; deliberately wide, squat letter proportions. |
| 63.875 | Similar centered composition, with slight continuing contraction. |
| **63.917** | A huge M from MORE is now visible at the **right edge**, while ONE and the product are still relatively large. |
| **63.958** | ONE/product have rapidly contracted and moved left; much of MORE is already visible. This is the dominant displacement over only about 42 ms. |
| **64.000** | Full MORE is visible in the right column; ONE is the short upper-left row, product the lower-left cell. |
| 64.042–64.292 | Arrangement settles gradually. MORE contracts slightly while the product continues turning inside its cell. ONE is about one-third MORE's height. This is a residual motion tail, not another large move. |
| **64.292** | TIME is not visible yet. |
| **64.333** | TIME is already almost wholly visible from below. ONE/MORE/product have moved sharply upward to make room. The product's rotation continues through the layout change. |
| **64.375** | Lower TIME row and upper two-column block keep resolving; changes are already much smaller than the preceding burst. |
| 64.542–64.875 | Whole composition slowly expands toward its final near-full-frame footprint. Margins tighten and movement decays. |
| 65.042–65.708 | Layout is virtually held. Final margins roughly 2.5–3% of width; black gutters approximately 1–2%. Product remains a visual cell, not a separate slide. |
| 65.875 | First specification row appears at the top, pushing the established collage downward by about 11% of frame height. |
| 66.042 | A second specification row adds more occupied height and pushes the old collage down further. TIME is now clipped by the bottom. |

Final collage approximate normalized rectangles, top-left origin:

| Cell | x | y | width | height |
| --- | --- | --- | --- | --- |
| ONE | .025 | .045 | .382 | .148 |
| Product | .028 | .213 | .377 | .320 |
| MORE | .425 | .045 | .548 | .493 |
| TIME | .028 | .562 | .945 | .390 |

The rows use **different letter proportions**, not one text style resized uniformly. ONE has extremely wide letters; MORE uses tall condensed letters; TIME uses broad heavy letters. Their visible bounding boxes align to a common set of black gutters. Product edges participate in the grid.

### What the speed evidence changes in implementation

The major reconfiguration does **most of its visible travel in one or two 24 fps sample intervals (roughly 42–83 ms)**, then carries small residual motion for 0.3–0.5 seconds. Making every word take 0.5 seconds with a symmetric ease-in-out produces a distinctly softer, presentation-like rhythm.

Suggested reconstruction pattern, normalized movement progress (a fit, not source keyframes):

| Local time | Main layout progress | Purpose |
| --- | --- | --- |
| 0.000 | 0.00 | Existing composition still readable. |
| 0.042 | 0.08 | Incoming word reaches the frame edge. |
| 0.083 | 0.78 | Fast shared displacement and scale change. |
| 0.125 | 0.92 | New word is readable; dominant movement is over. |
| 0.250 | 0.98 | Small residual adjustment. |
| 0.450 | 1.00 | Settle into reading hold. |

Interpolate this with a monotonic piecewise curve, keeping velocity transitions controlled inside the burst. Avoid adding a spring oscillation: no repeated overshoot/rebound was established in these sampled text layouts. The product may move for longer than the type. The next word can enter before the product finishes settling, which creates continuity.

For TIME, the visible entrance is faster still: a large part is already present in the first sampled frame after absence. Use a short, deliberately sharp upward displacement followed by a longer gentle expansion of the combined layout; do not add a 400 ms bottom-to-center glide.

## Adaptation and review contract

H3Loom's words can replace the reference words, but each replacement must be fitted to the **same role and occupied rectangle**, rather than assigned the same font size. The visible part of letter geometry, rather than font em metrics, should determine its alignment. Fit horizontal and vertical dimensions independently where the reference does so.

Keep these three clocks independent: (1) rapid layout changes, (2) reading holds and residual type movement, (3) product/light motion. One global ease applied to all objects will erase the observed temporal design.

Review the encoded video and scrub at consecutive frames around every word handoff. Verify that no blank frame appears between connected layouts; new words arrive with the correct direction; old words remain identifiable while changing role; gutters close without accidental collisions; holds are long enough to read; material motion does not become a substitute for missing geometry or timing. Record visual estimates as estimates. This document supports a reconstruction of the observed mechanisms and does not certify pixel-identical replication of Apple's film.
