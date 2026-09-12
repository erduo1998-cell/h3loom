import * as THREE from 'three';
import { TTFLoader } from 'three/addons/loaders/TTFLoader.js';
import { FontLoader } from 'three/addons/loaders/FontLoader.js';
import { TextGeometry } from 'three/addons/geometries/TextGeometry.js';

/** Local, deterministic typography. No font or texture is fetched from a CDN. */
export async function createTypeKit(renderer, { fontUrl = '/fonts/display.ttf' } = {}) {
  const source = await new TTFLoader().loadAsync(fontUrl);
  const font = new FontLoader().parse(source);
  const geometries = new Set();
  const ownedMaterials = new Set();
  const timeUniform = { value: 0 };
  const reflectionStrength = { value: 1 };

  // Floating-point studio panorama. Values above 1 carry actual lighting energy;
  // PMREM convolves this environment for roughness-dependent reflections.
  const panorama = makeStudioPanorama();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const environmentTarget = pmrem.fromEquirectangular(panorama);
  const environment = environmentTarget.texture;
  panorama.dispose();
  pmrem.dispose();

  const whiteFace = new THREE.MeshBasicMaterial({ color: 0xf8f9fc, toneMapped: false });
  const whiteEdge = new THREE.MeshPhysicalMaterial({
    color: 0xe0e3e8, metalness: 0.68, roughness: 0.21,
    clearcoat: 0.65, clearcoatRoughness: 0.2,
    envMap: environment, envMapIntensity: 0.95,
  });
  const silver = new THREE.MeshPhysicalMaterial({
    color: 0xdce2eb, metalness: 1, roughness: 0.16,
    clearcoat: 0.35, clearcoatRoughness: 0.12,
    envMap: environment, envMapIntensity: 0.7,
  });
  const metal = new THREE.MeshPhysicalMaterial({
    color: 0xb3bad0, metalness: 1, roughness: 0.17,
    clearcoat: 0.35, clearcoatRoughness: 0.12,
    envMap: environment, envMapIntensity: 0.6,
  });
  const satin = new THREE.MeshPhysicalMaterial({
    color: 0x929292, metalness: 0.96, roughness: 0.38,
    clearcoat: 0.24, clearcoatRoughness: 0.36,
    envMap: environment, envMapIntensity: 0.14,
  });
  satin.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vSatinWorldPosition;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvSatinWorldPosition = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vSatinWorldPosition;')
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
float satinLevel = 1.0 - smoothstep(-3.8, 3.6, vSatinWorldPosition.y);
float satinLight = mix(0.075, 0.44, satinLevel);
`)
      .replace('#include <opaque_fragment>', `
// Keep the broad frontal studio card neutral while retaining the real physical
// response at grazing angles, on extrusion walls, and on the hairline bevel.
float satinFront = pow(abs(normal.z), 8.0);
outgoingLight = mix(outgoingLight, vec3(satinLight), satinFront * 0.96);
#include <opaque_fragment>`);
  };
  satin.customProgramCacheKey = () => 'h3loom-type-satin-v1';
  // Finite virtual studio cards reflected by the real surface normal. The ray
  // originates on the extruded geometry, so movement/curvature changes the light
  // footprint. No emissive gradient: readable silver comes from reflected cards.
  function studioReflection(material, accent) {
    material.onBeforeCompile = shader => {
      shader.uniforms.typeTime = timeUniform;
      shader.uniforms.typeReflectionStrength = reflectionStrength;
      shader.uniforms.typeAccent = { value: accent };
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nvarying vec3 vTypeWorldPosition;')
        .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvTypeWorldPosition = (modelMatrix * vec4(transformed, 1.0)).xyz;');
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `#include <common>
varying vec3 vTypeWorldPosition;
uniform float typeTime;
uniform float typeReflectionStrength;
uniform float typeAccent;
float studioBox(vec2 p, vec2 size, float feather) {
  vec2 d = abs(p) - size;
  return (1.0-smoothstep(-feather,feather,d.x)) * (1.0-smoothstep(-feather,feather,d.y));
}
`)
        .replace('#include <opaque_fragment>', `
vec3 ray = inverseTransformDirection(reflect(-normalize(vViewPosition), normal), viewMatrix);
float cardDistance = (10.0-vTypeWorldPosition.z) / max(ray.z,0.08);
vec2 hit = vTypeWorldPosition.xy + ray.xy * cardDistance;
float slow = sin(typeTime * 0.55);
// Large softbox / narrow strip / negative fill make distinct metal bands.
vec2 q = vec2(hit.x, hit.y + hit.x * 0.17 + slow * 0.72);
float feather = 0.13 + roughnessFactor * 1.6;
float keyCard = studioBox(q-vec2(-1.0,3.5), vec2(13.5,2.2), feather);
float lowerCard = studioBox(q-vec2(1.0,-4.4), vec2(13.0,1.55), feather*1.1);
float stripCard = studioBox(q-vec2(0.0,0.50+slow*0.18), vec2(14.0,0.14), feather*0.36);
float sideCard = studioBox(hit-vec2(-6.8+slow,0.0),vec2(0.75,9.0),feather);
vec3 reflected = vec3(0.115,0.125,0.15);
reflected += keyCard * vec3(1.45,1.48,1.55);
reflected += lowerCard * vec3(0.67,0.72,0.83);
reflected += stripCard * vec3(2.0,2.03,2.1);
reflected += sideCard * vec3(0.33,0.38,0.48);
// Blue/violet is a local reflected edge, not the entire letter's base color.
float accentCard = studioBox(q-vec2(2.0,-1.4),vec2(12.0,0.52),feather*1.7);
reflected = mix(reflected, reflected*vec3(0.48,0.52,0.94) + accentCard*vec3(0.14,0.06,0.32),typeAccent);
float front = smoothstep(0.12,0.80,abs(ray.z));
float fresnel = 0.91 + 0.09*pow(1.0-saturate(dot(normal,normalize(vViewPosition))),5.0);
outgoingLight = mix(outgoingLight, reflected*fresnel, front*0.86*clamp(typeReflectionStrength,0.0,1.0));
#include <opaque_fragment>`);
    };
    material.customProgramCacheKey = () => `h3loom-reflected-studio-v4-${accent}`;
  }
  studioReflection(silver, 0.0);
  studioReflection(metal, 0.38);
  for (const m of [whiteFace, whiteEdge, silver, metal, satin]) ownedMaterials.add(m);

  const materials = {
    white: [whiteFace, whiteEdge],
    silver,
    metal,
    satin,
    whiteFace,
    whiteEdge,
  };

  function resolveMaterial(material) {
    if (!material) return materials.white;
    if (typeof material === 'string') {
      if (!(material in materials)) throw new Error(`Unknown type material: ${material}`);
      return materials[material];
    }
    return material;
  }

  function makeWord(text, {
    width, height, depth = 0.065, material = 'silver', tracking = 0,
    bevel = true, bevelSize = 0.007, curveSegments = 10,
  } = {}) {
    const word = new THREE.Group();
    word.name = `type:${text}`;
    const letters = [];
    let cursor = 0;
    const glyphs = font.data.glyphs;
    const resolution = font.data.resolution;
    for (const character of String(text)) {
      const glyph = glyphs[character];
      if (!glyph) throw new Error(`Display font has no glyph for ${character}`);
      const advance = glyph.ha / resolution;
      if (character !== ' ') {
        const geometry = new TextGeometry(character, {
          font, size: 1, depth, curveSegments,
          bevelEnabled: bevel,
          bevelThickness: bevel ? bevelSize * 0.65 : 0,
          bevelSize: bevel ? bevelSize : 0,
          bevelSegments: bevel ? 3 : 0,
          steps: 1,
        });
        geometries.add(geometry);
        geometry.computeBoundingBox();
        const center = geometry.boundingBox.getCenter(new THREE.Vector3());
        geometry.translate(-center.x, -center.y, -center.z);
        const letter = new THREE.Mesh(geometry, resolveMaterial(material));
        letter.position.set(cursor + center.x, center.y, 0);
        letter.name = character;
        letter.castShadow = false;
        letter.receiveShadow = false;
        letter.userData.character = character;
        letters.push(letter);
        word.add(letter);
      }
      cursor += advance + tracking;
    }
    if (letters.length) {
      word.updateMatrixWorld(true);
      const bounds = new THREE.Box3().setFromObject(word);
      const center = bounds.getCenter(new THREE.Vector3());
      const size = bounds.getSize(new THREE.Vector3());
      for (const letter of letters) letter.position.sub(center);
      const sx = width == null ? (height == null ? 1 : height / size.y) : width / size.x;
      const sy = height == null ? sx : height / size.y;
      // Bake layout scaling into positions and geometry, preserving world-unit
      // extrusion thickness and making per-letter rotation axes predictable.
      for (const letter of letters) {
        letter.position.x *= sx;
        letter.position.y *= sy;
        letter.geometry.scale(sx, sy, 1);
        letter.geometry.computeBoundingBox();
        letter.geometry.computeBoundingSphere();
      }
      word.userData.width = size.x * sx;
      word.userData.height = size.y * sy;
    }
    word.userData.text = String(text);
    word.userData.letters = letters;
    word.userData.restPositions = letters.map((letter) => letter.position.clone());
    word.userData.setMaterial = (next) => setWordMaterial(word, next);
    return word;
  }

  function setWordMaterial(word, material) {
    const resolved = resolveMaterial(material);
    for (const letter of word.userData.letters || []) letter.material = resolved;
    return word;
  }

  return {
    makeWord, materials, environment, setWordMaterial,
    fontInfo: { family: source.familyName, url: fontUrl, fallback: false },
    update(time, { sheen = 1 } = {}) {
      timeUniform.value = time;
      reflectionStrength.value = sheen;
    },
    dispose() {
      for (const g of geometries) g.dispose();
      for (const m of ownedMaterials) m.dispose();
      environmentTarget.dispose();
    },
  };
}

function makeStudioPanorama() {
  const width = 512;
  const height = 256;
  const pixels = new Float32Array(width * height * 4);
  const wrap = (angle) => Math.atan2(Math.sin(angle), Math.cos(angle));
  const panels = [
    // longitude, latitude, width, height, radiance RGB
    [1.15, 0.40, 0.48, 0.16, [5.5, 5.8, 6.2]],
    [-0.58, 0.65, 0.19, 0.80, [2.0, 2.25, 3.0]],
    [2.65, -0.15, 0.10, 0.75, [3.9, 4.2, 5.0]],
    [-2.30, 0.10, 0.18, 0.60, [1.2, 1.5, 2.1]],
    [0.25, -0.75, 0.70, 0.09, [1.3, 1.4, 1.55]],
  ];
  for (let y = 0; y < height; y++) {
    const latitude = Math.PI * (0.5 - (y + 0.5) / height);
    for (let x = 0; x < width; x++) {
      const longitude = (x + 0.5) / width * Math.PI * 2 - Math.PI;
      const rgb = [0.009, 0.011, 0.017];
      for (const [lon, lat, sx, sy, energy] of panels) {
        const dx = wrap(longitude - lon) / sx;
        const dy = (latitude - lat) / sy;
        const intensity = Math.exp(-Math.pow(dx, 4) - Math.pow(dy, 4));
        for (let c = 0; c < 3; c++) rgb[c] += intensity * energy[c];
      }
      const i = (y * width + x) * 4;
      pixels[i] = rgb[0]; pixels[i + 1] = rgb[1]; pixels[i + 2] = rgb[2]; pixels[i + 3] = 1;
    }
  }
  const texture = new THREE.DataTexture(pixels, width, height, THREE.RGBAFormat, THREE.FloatType);
  texture.mapping = THREE.EquirectangularReflectionMapping;
  texture.colorSpace = THREE.LinearSRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}
