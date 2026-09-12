# Reference transitions: what survives the cut

Reference: [The New Mac Studio with M5 Max and M5 Ultra](https://www.youtube.com/watch?v=3uAIqqg8ZHo), supplied by the owner. Analysis date: 2026-09-12.

## Evidence boundary

The observations below reuse this reviewer's **actual earlier browser inspection of successive reference frames**, documented in [reference-analysis.md](reference-analysis.md). On the transition-specific follow-up, this reviewer's browser inventory returned `browsers: []`; the lead agent was immediately asked to take over renewed reference playback. This document does not pretend that a new 4–8-frame inspection has already occurred at every cut.

Existing direct evidence covers four-frame samples at 5.000–6.917, 50.042–51.542 and 63.542–66.042 seconds, plus single-frame samples at 63.917–64.417. The lead agent subsequently supplied renewed actual CUA observations at 3.500–4.500 and 5.000–5.667; those observations are attributed below. Entrance into RENDER around 49.5 and product-to-ONE onset before 63.542 still lack additional cut-adjacent evidence here. Do not assign a mechanism such as a wipe, whip pan or occlusion to those unobserved intervals.

## Three consequential differences

1. **Hard cuts in the reference still match visual weight.** WITH, the large rear product face and the giant identifier remain centered silver masses on black, occupying most of the picture. The new version changes from near-full-height WITH to a much shorter dark module, then back to giant bright type. That alternation changes the visual weight much more abruptly than the sampled reference. Adding a dissolve would soften the boundary but would not restore the missing relationship.
2. **Several apparent “new scenes” are one object changing its role.** The huge identifier becomes the small identifier on the chip. The product becomes a cell inside ONE/MORE/TIME while turning continues. Specifications occupy new rows and push the old layout away. The reference often keeps a recognizable object or alignment alive while adding information; this is different from finishing one composition and starting an unrelated one.
3. **The next shot pays off the previous word or material.** RENDER is followed by an actual wireframe-to-solid action with the same blue/violet metallic family. In the new version, RENDER cuts to the unrelated white word IN. That removes the action promised by the preceding word and abandons its material palette at the same instant.

## Observed joins

| Join | Directly observed evidence | Classification and restraint |
| --- | --- | --- |
| WITH → rear product | 5.000–5.250: tall silver word gently widens. Renewed lead-agent samples show WITH still present at 5.333331 and rear product at 5.416664. The word spans approximately x=44–866 and the product x=50–860 inside the same video rectangle x=16–896. Both are centered on black, with broad neutral silver values. | A cut is narrowed to 5.333331–5.416664. Horizontal projected size and center match closely despite the subject replacement. No observed dissolve or type-to-product morph. At 5.500, 5.583 and 5.667, product width stays almost fixed while its underside visibility and projected height decrease as it rotates toward a more level view. |
| Rear product → giant identifier | 5.417–5.750: rear view continues changing orientation toward flatter framing; 5.917: large two-line identifier is present. | Observed replacement within 5.750–5.917. Near-full-frame silver mass and center are retained. A hidden wipe or exact frame-level match is not established by these samples. |
| Giant identifier → chip | 5.917–6.250: identifier occupies most of the picture, with mark/line proportions rebalanced; 6.417: the same identifier is inside the chip; 6.583–6.917: shrink slows into a hold. | Continuous identity and scale relationship: big type becomes a small physical label. Layout and container reveal need separate tracks. It is not a generic crossfade between a word and an unrelated object. |
| Previous scene → RENDER | No inspected picture before 50.042 in the current evidence set. | **Unclassified pending renewed playback.** Do not invent a whip pan, match cut or light wipe. |
| RENDER → wireframe/solid object | 50.042–50.875: centered reflective word holds; 51.042: centered wireframe object with lower solid regions; 51.208–51.542: solid metallic surface advances upward. Both use blue/violet reflections on black. | Observed cut within 50.875–51.042, followed by a motivated representation change. Color and meaning connect the scenes. No observed word fade or shrink before the cut. |
| Product → ONE | At 63.542 the product is still large with ONE emerging above/behind it; 63.708 ONE is clear above the same product. | Existing object remains on screen while type joins; depth/overlap is visible. The exact entrance before 63.542 needs further evidence. |
| ONE/product → ONE/product/MORE | 63.917: giant M enters at the right while the original pair remains; 63.958: original pair moves left and contracts as MORE becomes visible; 64.000: new grid is readable; 64.042–64.292: small residual settle. | Continuous shared layout reflow. No full-scene cut, no common opacity fade. Dominant movement occupies about 1–2 sampled 24 fps intervals, then settles. |
| Two-column group → addition of TIME | 64.292: no TIME; 64.333: TIME is nearly wholly present from below, old group has moved upward; 64.375 onward: small adjustments and slower overall growth. | Fast vertical insertion with shared displacement. Previous objects remain identifiable; product turn continues. The new row reorganizes space rather than replacing the old slide. |
| ONE/MORE/TIME → specifications | 65.042–65.708: grid holds; 65.875: first row of specifications occupies the top, pushing old grid down; 66.042: another row continues this. | Occupancy-driven downward displacement. Old content leaves because new content takes its place. No blank reset frame or dissolve is needed. |

## Why the current remake can feel disconnected

This is based on `scene.js` and `motion-score.js` as read at this follow-up, not a new full-movie playback claim.

- `reset()` hides all groups and resets camera position; `compose()` then shows one active shot. That architecture is compatible with intentional hard cuts, but it gives inter-shot continuity no explicit owner. The score currently describes what happens **within** each section, while most boundaries simply replace one group with another.
- The WITH word is approximately 8.1 scene units tall, while the device body is only 2.65 units tall before its roughly 1.1 scale. Even allowing for depth, the new device's short dark profile is a large reduction in bright occupied area compared with the sampled full rear face in the reference.
- CHIP comes to rest well before the RENDER cut. RENDER starts as a larger new word; the preceding chip/light state does not provide a designed leading edge, object handoff or maintained visual shape into that change.
- The 4K shot finishes with a fast forward move, but the next YOUR/product shot begins with a new static arrangement. Momentum is discarded rather than redirected or matched at the cut. This can be an intentional impact cut, but it currently has no explicit screen-space match in the score.
- The final DESIGN/REVIEW/CREATE section repeats short independent entrances. Keeping the same approximate rectangle helps typography matching, but alternately entering from left/right after each previous word has already settled can still feel like a sequence of separate title cards. A continuous carrier, common edge or a deliberate chain of out/in velocities would make their relationship legible.

## Design implications for correction

Use a separate transition specification for each boundary, recording: outgoing last readable composition, incoming first readable composition, the retained object or edge, occupied-area relationship, motion direction before/after, luminance/color relationship, and the intended cut frame. A transition may explicitly be a hard cut; it still needs these relationships.

For this film, prioritize these concrete choices:

- Restore the large neutral metal mass at WITH → device → identifier, or use another deliberate shape/scale match with comparable visual weight.
- Preserve a recognizable element across neighboring chapters where the story supports it: a word becomes a label, a device becomes a grid cell, or the same grid changes occupancy.
- Give RENDER a visible result or carry its reflective/material field into the following shot. Do not automatically insert an unrelated white title immediately afterward.
- When a chapter ends at high velocity, either continue that screen-space direction into the next scene or cut at a deliberately matched close view. Do not reset to a calm wide layout by default.
- Keep genuine reading holds and impact cuts. A uniform crossfade on every boundary would conceal some discontinuities while weakening the original's precise fast rhythm.

These are reconstruction choices guided by the observed reference. They are not claims that Apple's original camera, edit decision list, animation curves or compositing method have been recovered.

## Renewed lead-agent browser observations

The lead agent inspected the reference through CUA after this reviewer's browser became unavailable and reported the following additional frames. These are actual observations supplied by that reviewer, not independently re-opened images in this sub-agent's browser.

| Time | Reported visible state | Consequence |
| --- | --- | --- |
| 3.499963 | Small Mac Studio label centered. | Establishes a small centered identity before the larger typography section. The exact transition from this label to the following frame remains unspecified. |
| 3.749960 | AN AI fills the picture. | Large typography becomes the new visual mass. |
| 3.999957 | AN AI is vertically reshaped and retained above; POWERHOUSE joins as the bottom row. Both remain silver/white on black. | Continuous typographic reflow. Existing text survives while new text occupies another row; it is not a clear-and-restart for each word. |
| 4.249956, 4.499998 | Same AN AI / POWERHOUSE arrangement with reflection movement. | Reading hold with independent material motion. |
| 5.000000, 5.333331 | WITH fills the picture. | Outgoing near-full-frame silver mass is established before the product cut. |
| 5.416664 | Product rear fills almost the same horizontal bounds as WITH. | Size, tonal weight and center bridge a genuine local hard cut. |
| 5.500000, 5.583330, 5.666663 | Rear width is almost unchanged; underside visibility and height decrease, with the silver back still dominating the picture. | Post-cut rotation continues without a large width reset. The image retains visual weight while orientation changes. |

The remake's new chapter connections are **authored adaptations**. Matching or preserving projected shapes, objects and motion can improve them, but the film must not claim that every newly added carrier motion or transition also exists in Apple's reference. The evidence supports a mixture of deliberately matched hard cuts and persistent layout transformations, not a blanket ban on cuts.
