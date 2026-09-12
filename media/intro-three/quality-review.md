# Independent reference comparison

Review date: 2026-09-12. Baseline: `review-v2-frames` and the corresponding `scene.js` / `motion-score.js` before subsequent corrections. Reference evidence is recorded in [reference-analysis.md](reference-analysis.md).

This review found three material differences, listed below. H3/LOOM replacing M5/MAX, YOUR/OWN/CLOUD replacing ONE/MORE/TIME, the original cloud-module design, and the 24-second running time are intentional adaptations and are not defects by themselves.

## Review scope

The reviewer previously inspected the exact YouTube reference in successive 24 fps player steps, including individual frames around the rapid reflows. On this follow-up, the browser inventory returned no available browsers and both IAB tab-creation attempts failed. Therefore the new version was checked through actual local rendered frames and its deterministic motion code; **this is not a claim that the new full movie received uninterrupted browser playback review**.

Inspected new frames: 6.000, 6.200, 6.420, 9.000, 9.800, 13.300, 13.700 and 14.200 seconds in `outputs/intro-three/review-v2-frames/`.

## Findings requiring correction or explicit acceptance

1. **The first collage reflow moves YOUR in the opposite vertical direction.** In the reference, ONE starts near the top; when MORE arrives, ONE contracts leftward **and downward** into a centered two-column group. Only the following TIME entrance lifts that group toward the top. New 13.300 → 13.700 moves YOUR slightly upward instead. Code confirms `y` changes from `1.55` to `2.25`. The final three-row layout is already close in role and occupied area, but the route to that layout loses the reference's down-then-up choreography. Correct the starting and intermediate anchors while preserving the fast main displacement and longer settle.

2. **The chip shot reveals the container too soon and crops the giant words.** At 6.000 the new H3 top and LOOM bottom are outside the picture, and both vertical chip rails are plainly visible. At 6.200 the frame still encloses the typography. Reference 5.917–6.250 presents a readable giant two-line identifier on black, then reveals the chip while contracting. The new plate width is `4.25 × 3.05 ≈ 12.96` against a roughly 16-unit viewport, so its sides are not actually beyond the frame as the code comment states. Keep the initial type within readable bounds and stage the surrounding die's reveal separately from the type contraction. The core shrinking rhythm is substantially more specific than a generic ease preset, which should be retained.

3. **RENDER's reflective field is too broad and leaves half the word almost black.** New 9.000 has a bright left/middle area and a very dark DER; 9.800 has the inverse emphasis. In the reference's successive 50.04–50.87 frames, pale peach/lavender/indigo transitions are distributed across all six letters, with narrower overlapping bands and visible blue faces throughout. New type boundaries and reading hold match the intended mechanism; the remaining difference is the reflectance distribution. Raise the dark reflective floor modestly and use several broad but narrower overlapping bands so movement continues across the full word. Preserve black counters and background; do not fix this by adding glow around the letters.

These findings concern observed composition and trajectory, not recovery of Apple's original 3D scene or source curves. After corrections, the changed intervals should be re-rendered and checked at consecutive frames; a successful render or matching final still does not by itself resolve a movement-direction issue.

## V3 targeted recheck

Inspected `review-v3-frames` at 5.920, 6.000, 6.250, 6.420, 7.000, 9.000, 9.800, 13.200, 13.620 and 14.100 seconds. This is a targeted rendered-frame recheck; the lead agent owns continuous UI playback verification.

- **Finding 1: corrected.** YOUR now begins higher, moves down as it contracts leftward, and moves back up when CLOUD enters. The three observed states and changed position code establish the intended down-then-up direction. Exact perceptual smoothness still belongs to playback review.
- **Finding 2: partly corrected.** The giant-type states no longer show the chip's premature side rails, and the chip resolves around the same typography by 6.420. However, the 5.920 first frame still places LOOM's lower edge outside/at the picture boundary; by 6.000 it is complete but has only about 10 pixels of bottom clearance. Reduce initial type height or initial overall scale by roughly 5–6% to leave a real safety margin before treating the cropping defect as resolved.
- **Finding 3: corrected at the reviewed samples.** At both 9.000 and 9.800 all letters retain visible blue/purple faces, and additional pale/purple reflection regions span the word. The previously near-black half-word problem is gone. This confirms the requested distribution correction, not identical Apple shading or a full temporal material match.

## Final encoded-frame follow-up by lead

The initial chip scale was subsequently reduced from 2.65 to 2.50, with the early scale knots adjusted. The first encoded chip frame at 5.933333 s (the first 60 fps frame after the 5.920 s edit) was decoded from the final MP4 and visually checked: H3 and LOOM are fully inside the frame, with roughly 30 px clearance at the bottom. The premature border and first-frame clipping findings are resolved in this build. This follow-up is an encoded-frame observation, not a claim of pixel-identical matching to the reference.

## Cross-shot revision

The owner's subsequent feedback concerned the joins between shots. The reference's matched subject footprint and ongoing layout were re-examined; see `transition-reference.md`. The new `composeConnected` passages retain multiple elements across the old shot markers. The initial connected sample exposed a collision between departing H3/LOOM and growing RENDER; it was corrected by keeping the old labels attached to their descending die while RENDER unfolds above. The corrected 8.25 s render was checked. Wire-to-solid 4K and its continuation as the product's label were checked at 11.0, 12.0, 13.25 and 14.5 s. The new MP4 decodes all 1,440 frames with no fully black transition frame at the tested black-detection threshold. A transition-focused 80-return state test passes. Aesthetic continuity is still a visual judgement; these checks do not certify equivalence with the source film.
