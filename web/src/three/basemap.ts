// Orientation layers for the 3D city: neighborhood labels, streets draped on the
// terrain, and vacant-lot outlines. All three are static files baked by
// pipeline/build_basemap.py; any that is missing is simply not drawn.
import * as THREE from 'three'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js'

export interface StreetTier {
  id: string
  color: string
  opacity: number
  width_px: number
  max_distance: number
}

export interface BasemapConfig {
  labels: { padding_px: number }
  streets: { tiers: StreetTier[] }
  lots: { outline_distance: number }
}

interface Quantized {
  origin: [number, number]
  q: number
}
interface HoodsFile extends Quantized {
  labels: [string, number, number, number][]
}
interface StreetsFile extends Quantized {
  tiers: string[]
  lines: number[][] // [tier, x0, y0, x1, y1, ...]
}
interface LotsFile extends Quantized {
  lots: [string, ...number[][]][] // [id, ring, ring, ...]
}

export interface BasemapData {
  hoods: HoodsFile | null
  streets: StreetsFile | null
  lots: LotsFile | null
}

type ToXZ = (lon: number, lat: number) => [number, number]
type HeightAt = (x: number, z: number) => number

export async function loadBasemap(base: string): Promise<BasemapData> {
  const get = <T>(name: string) =>
    fetch(`${base}/basemap/${name}.json`)
      .then((r) => (r.ok ? (r.json() as Promise<T>) : null))
      .catch(() => null)
  const [hoods, streets, lots] = await Promise.all([get<HoodsFile>('neighborhoods'), get<StreetsFile>('streets'), get<LotsFile>('lots')])
  return { hoods, streets, lots }
}

/** Scene [x, z] pairs from a quantized coordinate run. */
function toScene(f: Quantized, run: number[], start: number, toXZ: ToXZ): [number, number][] {
  const [lon0, lat0] = f.origin
  const out: [number, number][] = []
  for (let k = start; k + 1 < run.length; k += 2) out.push(toXZ(lon0 + run[k] / f.q, lat0 + run[k + 1] / f.q))
  return out
}

function lineMaterial(color: string, opacity: number, width: number, vertexColors = false): LineMaterial {
  return new LineMaterial({ color: vertexColors ? 0xffffff : new THREE.Color(color).getHex(), linewidth: width, transparent: true, opacity, vertexColors, fog: true })
}

// ---------------------------------------------------------------- streets

export interface Streets {
  group: THREE.Group
  /** Street polylines in scene units, for placing decorative frontage. */
  lines: { tier: number; pts: [number, number][] }[]
  /** True within about `r` scene units of a street (alleys excluded). */
  near(x: number, z: number, r?: number): boolean
  update(distance: number): void
  setResolution(w: number, h: number): void
}

/** Streets as screen-width lines, densified so they follow the terrain. */
export function makeStreets(f: StreetsFile, cfg: BasemapConfig, toXZ: ToXZ, heightAt: HeightAt): Streets {
  const tiers = cfg.streets.tiers
  const step = 2
  const lift = 0.7
  const buf: number[][] = tiers.map(() => [])
  const lines: Streets['lines'] = []
  for (const run of f.lines) {
    const tier = tiers.findIndex((t) => t.id === f.tiers[run[0]])
    if (tier < 0) continue
    const pts = toScene(f, run, 1, toXZ)
    lines.push({ tier, pts })
    for (let k = 1; k < pts.length; k++) {
      const [ax, az] = pts[k - 1]
      const [bx, bz] = pts[k]
      const n = Math.max(1, Math.ceil(Math.hypot(bx - ax, bz - az) / step))
      for (let s = 0; s < n; s++) {
        const x0 = ax + ((bx - ax) * s) / n
        const z0 = az + ((bz - az) * s) / n
        const x1 = ax + ((bx - ax) * (s + 1)) / n
        const z1 = az + ((bz - az) * (s + 1)) / n
        buf[tier].push(x0, heightAt(x0, z0) + lift + tier * 0.05, z0, x1, heightAt(x1, z1) + lift + tier * 0.05, z1)
      }
    }
  }
  // Street sample points on a hash grid, so trees and buildings stay off streets.
  const CELL = 2
  const road = new Set<number>()
  const key = (i: number, j: number) => i * 100003 + j
  for (const { tier, pts } of lines) {
    if (tier === 0) continue // alleys run behind buildings
    for (let k = 1; k < pts.length; k++) {
      const [ax, az] = pts[k - 1]
      const [bx, bz] = pts[k]
      const n = Math.max(1, Math.ceil(Math.hypot(bx - ax, bz - az) / 0.8))
      for (let s = 0; s <= n; s++) road.add(key(Math.floor((ax + ((bx - ax) * s) / n) / CELL), Math.floor((az + ((bz - az) * s) / n) / CELL)))
    }
  }
  const near = (x: number, z: number, r = 0) => {
    const k = Math.ceil(r / CELL)
    const i0 = Math.floor(x / CELL)
    const j0 = Math.floor(z / CELL)
    for (let a = -k; a <= k; a++) for (let b = -k; b <= k; b++) if (road.has(key(i0 + a, j0 + b))) return true
    return false
  }
  const group = new THREE.Group()
  const layers = tiers.map((t, i) => {
    const geo = new LineSegmentsGeometry()
    geo.setPositions(buf[i])
    const m = lineMaterial(t.color, t.opacity, t.width_px)
    const obj = new LineSegments2(geo, m)
    obj.renderOrder = 1 + i
    group.add(obj)
    return { obj, m, t }
  })
  return {
    group,
    lines,
    near,
    update(d) {
      for (const { obj, m, t } of layers) {
        // Fade over the last 30% before a tier hides.
        const k = Math.max(0, Math.min(1, (t.max_distance - d) / (t.max_distance * 0.3)))
        obj.visible = k > 0
        m.opacity = t.opacity * k
      }
    },
    setResolution(w, h) {
      for (const { m } of layers) m.resolution.set(w, h)
    },
  }
}

/**
 * Decorative buildings lining the streets: [x, z, width, depth, angle]. Kept off
 * the street itself, water, steep ground, and every vacant lot. Not buildings
 * from data.
 */
export function frontage(
  streets: Streets,
  keepOut: (x: number, z: number) => boolean,
  rand: () => number,
): [number, number, number, number, number][] {
  const out: [number, number, number, number, number][] = []
  for (const { tier, pts } of streets.lines) {
    if (tier === 0) continue
    let carry = rand() * 2
    for (let k = 1; k < pts.length; k++) {
      const [ax, az] = pts[k - 1]
      const [bx, bz] = pts[k]
      const len = Math.hypot(bx - ax, bz - az)
      if (len < 0.01) continue
      const ux = (bx - ax) / len
      const uz = (bz - az) / len
      const ang = Math.atan2(uz, ux)
      let s = carry
      for (; s < len; s += 2.2 + rand() * 1.2) {
        for (const side of [1, -1]) {
          if (rand() < 0.35) continue
          const w = 1.3 + rand() * 0.7
          const dep = 1.4 + rand() * 0.9
          const off = 1.3 + dep / 2
          const x = ax + ux * s - uz * side * off
          const z = az + uz * s + ux * side * off
          if (streets.near(x, z) || keepOut(x, z)) continue
          out.push([x, z, w, dep, ang])
        }
      }
      carry = s - len
    }
  }
  return out
}

// ---------------------------------------------------------------- lot outlines

export interface Lots {
  obj: LineSegments2
  /** Parcel ids that have an outline. */
  ids: Set<string>
  /** Vacant lot under a scene point, if any. */
  at(x: number, z: number): string | null
  setVisible(ids: Set<string> | null): void
  setResolution(w: number, h: number): void
}

export function makeLots(f: LotsFile, colorOf: (id: string) => string, toXZ: ToXZ, heightAt: HeightAt): Lots {
  const lift = 1.1
  const lots = f.lots.map(([id, ...rings]) => {
    const polys = rings.map((r) => toScene(f, r, 0, toXZ))
    const pos: number[] = []
    for (const ring of polys)
      for (let k = 1; k < ring.length; k++) {
        const [ax, az] = ring[k - 1]
        const [bx, bz] = ring[k]
        pos.push(ax, heightAt(ax, az) + lift, az, bx, heightAt(bx, bz) + lift, bz)
      }
    const c = new THREE.Color(colorOf(id))
    const col: number[] = []
    for (let k = 0; k < pos.length / 3; k++) col.push(c.r, c.g, c.b)
    let x0 = Infinity, z0 = Infinity, x1 = -Infinity, z1 = -Infinity
    for (const ring of polys)
      for (const [x, z] of ring) {
        x0 = Math.min(x0, x); x1 = Math.max(x1, x)
        z0 = Math.min(z0, z); z1 = Math.max(z1, z)
      }
    return { id, polys, pos, col, box: [x0, z0, x1, z1] }
  })
  // Hash grid of lot bounding boxes for point lookup.
  const CELL = 6
  const grid = new Map<string, number[]>()
  lots.forEach((l, i) => {
    const [x0, z0, x1, z1] = l.box
    for (let a = Math.floor(x0 / CELL); a <= Math.floor(x1 / CELL); a++)
      for (let b = Math.floor(z0 / CELL); b <= Math.floor(z1 / CELL); b++) {
        const k = `${a},${b}`
        const list = grid.get(k)
        if (list) list.push(i)
        else grid.set(k, [i])
      }
  })
  const inside = (ring: [number, number][], x: number, z: number) => {
    let hit = false
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, zi] = ring[i]
      const [xj, zj] = ring[j]
      if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) hit = !hit
    }
    return hit
  }
  const geo = new LineSegmentsGeometry()
  const m = lineMaterial('#ffffff', 1, 2.2, true)
  const obj = new LineSegments2(geo, m)
  obj.renderOrder = 10
  let shown = new Set<number>(lots.map((_l, i) => i))
  const fill = () => {
    const pos: number[] = []
    const col: number[] = []
    for (const i of shown) {
      pos.push(...lots[i].pos)
      col.push(...lots[i].col)
    }
    geo.setPositions(pos.length ? pos : [0, 0, 0, 0, 0, 0])
    geo.setColors(col.length ? col : [0, 0, 0, 0, 0, 0])
  }
  fill()
  return {
    obj,
    ids: new Set(lots.map((l) => l.id)),
    at(x, z) {
      for (const i of grid.get(`${Math.floor(x / CELL)},${Math.floor(z / CELL)}`) ?? []) {
        if (!shown.has(i)) continue
        if (lots[i].polys.some((r) => inside(r, x, z))) return lots[i].id
      }
      return null
    },
    setVisible(ids) {
      shown = new Set(lots.flatMap((l, i) => (!ids || ids.has(l.id) ? [i] : [])))
      fill()
    },
    setResolution(w, h) {
      m.resolution.set(w, h)
    },
  }
}

// ---------------------------------------------------------------- neighborhood labels

export interface Rect {
  x0: number
  y0: number
  x1: number
  y1: number
}

export interface HoodLabels {
  /** Place labels for this frame; `taken` are screen rects already in use (pins). */
  update(camera: THREE.Camera, w: number, h: number, taken: Rect[]): void
  dispose(): void
}

/** DOM labels, biggest neighborhood first; any that would overlap one already placed is hidden. */
export function makeHoodLabels(f: HoodsFile, cfg: BasemapConfig, parent: HTMLElement, toXZ: ToXZ, heightAt: HeightAt): HoodLabels {
  const [lon0, lat0] = f.origin
  const pad = cfg.labels.padding_px
  const v = new THREE.Vector3()
  const items = f.labels.map(([name, qx, qy]) => {
    const [x, z] = toXZ(lon0 + qx / f.q, lat0 + qy / f.q)
    const el = document.createElement('div')
    el.className = 'hood-label'
    el.textContent = name
    el.style.display = 'none'
    parent.prepend(el) // behind pin labels
    return { el, x, y: heightAt(x, z) + 8, z, w: 0, h: 0 }
  })
  return {
    update(camera, w, h, taken) {
      const placed = [...taken]
      for (const it of items) {
        v.set(it.x, it.y, it.z).project(camera)
        const sx = (v.x * 0.5 + 0.5) * w
        const sy = (-v.y * 0.5 + 0.5) * h
        let show = v.z < 1 && sx > -40 && sx < w + 40 && sy > -20 && sy < h + 20
        if (show && !it.w) {
          it.el.style.display = 'block'
          it.w = it.el.offsetWidth
          it.h = it.el.offsetHeight
        }
        const r = { x0: sx - it.w / 2 - pad, y0: sy - it.h / 2 - pad, x1: sx + it.w / 2 + pad, y1: sy + it.h / 2 + pad }
        if (show) show = !placed.some((o) => r.x0 < o.x1 && r.x1 > o.x0 && r.y0 < o.y1 && r.y1 > o.y0)
        it.el.style.display = show ? 'block' : 'none'
        if (show) {
          placed.push(r)
          it.el.style.transform = `translate(${sx}px, ${sy}px) translate(-50%, -50%)`
        }
      }
    },
    dispose() {
      for (const it of items) it.el.remove()
    },
  }
}
