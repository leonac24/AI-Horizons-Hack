// Terrain for the stylized city: the heightmap baked by pipeline/build_terrain.py,
// or — if that file is missing — a rule-based stand-in shaped by river distance.

export interface Terrain {
  source: 'baked' | 'rules'
  heightAt(x: number, z: number): number
  isWater(x: number, z: number): boolean
  slopeAt(x: number, z: number): number
  /** Grid the ground mesh is drawn from: [extent, step, height fn]. */
  grids: { extent: number; step: number; h: (x: number, z: number) => number }[]
}

interface Meta {
  scale: number
  water: number
  coarse: { extent: number; step: number; n: number }
  fine: { extent: number; step: number; n: number }
}

/** Height of the flat water plane. */
export const WATER_LEVEL = 0.3
// Riverbed and lowest land sit well clear of the water plane so the depth buffer
// can always tell them apart (the engine also scales the camera's near plane with
// zoom). A shallow riverbed showed through the water when zoomed out, and on
// 16-bit depth buffers rivers flickered to land as the camera moved.
const WATER_H = WATER_LEVEL - 6
const LAND_MIN = WATER_LEVEL + 0.8

function sampler(data: Int16Array, offset: number, extent: number, step: number, n: number, scale: number, water: number) {
  const stride = n + 1
  const at = (i: number, j: number) => {
    const v = data[offset + j * stride + i]
    return v === water ? WATER_H : Math.max(LAND_MIN, v / scale)
  }
  const wet = (i: number, j: number) => data[offset + j * stride + i] === water
  const idx = (x: number, z: number) => {
    const fx = (x + extent) / step
    const fz = (z + extent) / step
    const i = Math.max(0, Math.min(n - 1, Math.floor(fx)))
    const j = Math.max(0, Math.min(n - 1, Math.floor(fz)))
    return { i, j, u: Math.min(1, Math.max(0, fx - i)), v: Math.min(1, Math.max(0, fz - j)) }
  }
  return {
    h(x: number, z: number) {
      const { i, j, u, v } = idx(x, z)
      return (at(i, j) * (1 - u) + at(i + 1, j) * u) * (1 - v) + (at(i, j + 1) * (1 - u) + at(i + 1, j + 1) * u) * v
    },
    wet(x: number, z: number) {
      const { i, j, u, v } = idx(x, z)
      return wet(u < 0.5 ? i : i + 1, v < 0.5 ? j : j + 1)
    },
  }
}

export async function loadTerrain(base: string, rivers: [number, number][][], half: number): Promise<Terrain> {
  try {
    const [meta, buf] = await Promise.all([
      fetch(`${base}/terrain.json`).then((r) => (r.ok ? (r.json() as Promise<Meta>) : Promise.reject(new Error('no terrain')))),
      fetch(`${base}/terrain.bin`).then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error('no terrain')))),
    ])
    const data = new Int16Array(buf)
    const { coarse, fine } = meta
    const C = sampler(data, 0, coarse.extent, coarse.step, coarse.n, meta.scale, meta.water)
    const F = sampler(data, (coarse.n + 1) ** 2, fine.extent, fine.step, fine.n, meta.scale, meta.water)
    const inFine = (x: number, z: number) => Math.abs(x) < fine.extent - 4 && Math.abs(z) < fine.extent - 4
    const heightAt = (x: number, z: number) => (inFine(x, z) ? F.h(x, z) : C.h(x, z))
    const isWater = (x: number, z: number) => (inFine(x, z) ? F.wet(x, z) : C.wet(x, z))
    return {
      source: 'baked',
      heightAt,
      isWater,
      slopeAt: slope(heightAt),
      grids: [
        { extent: coarse.extent, step: coarse.step, h: (x, z) => (inFine(x, z) ? C.h(x, z) - 2 : C.h(x, z)) },
        { extent: fine.extent, step: fine.step, h: F.h },
      ],
    }
  } catch {
    return ruleTerrain(rivers, half)
  }
}

function slope(h: (x: number, z: number) => number) {
  const e = 8
  return (x: number, z: number) => Math.hypot(h(x + e, z) - h(x - e, z), h(x, z + e) - h(x, z - e)) / (2 * e)
}

/** Dissected-plateau stand-in: flat river valleys, bluffs rising to rolling uplands. */
function ruleTerrain(riverPts: [number, number][][], half: number): Terrain {
  const pts = riverPts.flat()
  const dist = (x: number, z: number) => {
    let m = 1e9
    for (let k = 1; k < pts.length; k++) {
      const [ax, az] = pts[k - 1]
      const [bx, bz] = pts[k]
      const dx = bx - ax
      const dz = bz - az
      const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1)))
      m = Math.min(m, Math.hypot(x - ax - t * dx, z - az - t * dz))
    }
    return m
  }
  const sst = (a: number, b: number, v: number) => {
    const t = Math.max(0, Math.min(1, (v - a) / (b - a)))
    return t * t * (3 - 2 * t)
  }
  const heightAt = (x: number, z: number) => {
    const d = dist(x, z)
    if (d < 15) return WATER_H
    const n = 0.5 + 0.5 * Math.sin(x * 0.011 + 1.3) * Math.cos(z * 0.013 - 0.7) + 0.22 * Math.sin(x * 0.029 + z * 0.023)
    return LAND_MIN + sst(40, 105, d) * sst(80, 190, Math.hypot(x + 15, z)) * (15 + 14 * n)
  }
  return {
    source: 'rules',
    heightAt,
    isWater: (x, z) => dist(x, z) < 15,
    slopeAt: slope(heightAt),
    grids: [{ extent: half + 900, step: 26, h: heightAt }],
  }
}
