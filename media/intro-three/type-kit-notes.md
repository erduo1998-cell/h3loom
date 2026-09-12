# Three.js typography kit

`createTypeKit(renderer)` loads `/fonts/display.ttf` with Three.js `TTFLoader` and builds true, individually addressable beveled `TextGeometry` glyph meshes. It does not silently substitute another font. The local server supplies the system DIN Condensed Bold font; no proprietary font is copied into the repository.

```js
const kit = await createTypeKit(renderer);
scene.environment = kit.environment;
const title = kit.makeWord('RENDER', {
  width: 14.5, height: 5.2, depth: 0.065, material: 'metal',
});
scene.add(title);
kit.update(shotLocalTime - 1.0);
```

The word is visually centered on its origin and lies in the XY plane, facing +Z. Width and height are fitted independently, making the deliberately narrow/wide typography transitions possible. Extrusion depth remains in world units. `userData.letters` contains meshes whose individual origins are centered; `userData.restPositions` contains their initial positions. Restore these positions when evaluating any arbitrary frame; do not accumulate transforms from the previous render.

`materials.white` uses a clean white front face with physically lit silver side walls and bevels. `materials.silver` is a neutral, fully physical metal. `materials.silver` and `materials.metal` add finite virtual studio cards evaluated using the surface position, reflected view ray and normal; the latter uses a restrained blue/violet accent. The v4 effect combines this designed reflection with physical material response rather than an emissive gradient. The studio environment is generated locally as a floating-point panorama and filtered by PMREM. The ribbon is a designed approximation of moving studio lighting, not an inferred recreation of the original advertisement's light rig.

Use `kit.setWordMaterial(word, 'metal')` or `word.userData.setMaterial('white')` to change the complete word. Changing shared material opacity affects all words sharing that material; for independently fading words clone their materials, or reveal/conceal the group using geometry/clip transitions. `kit.update(time, {sheen: 0.8})` sets deterministic ribbon phase and intensity. The v4 card positions vary slowly and deterministically with time.

`kit.dispose()` releases all geometry, owned materials, and the environment render target.
