// Cartoon river bridges for the stylized city. `form` comes from city.yaml
// scene.bridges; each form is a small geometry recipe, merged per color.
import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { mat } from './typologyMeshes'

const K = 3.4 // cartoon scale-up
const STEEL = '#ffc21a' // Pittsburgh bridge yellow
const DECK = '#5b6672'
const PIER = '#a7b0ba'

export function makeBridge(form: string, lengthUnits: number, deckY: number): THREE.Group {
  const L = lengthUnits / K
  const y = deckY / K
  const parts = new Map<string, THREE.BufferGeometry[]>()
  const put = (g: THREE.BufferGeometry, c: string) => {
    const a = parts.get(c) ?? []
    a.push(g)
    parts.set(c, a)
  }
  const boxAt = (w: number, h: number, d: number, x: number, yy: number, z: number, c: string, rz = 0) => {
    const g = new THREE.BoxGeometry(w, h, d)
    if (rz) g.rotateZ(rz)
    g.translate(x, yy, z)
    put(g, c)
  }
  const beam = (x1: number, y1: number, x2: number, y2: number, z: number, t: number, c = STEEL) => {
    const dx = x2 - x1
    const dy = y2 - y1
    boxAt(Math.hypot(dx, dy), t, t, (x1 + x2) / 2, (y1 + y2) / 2, z, c, Math.atan2(dy, dx))
  }
  const S = [-0.9, 0.9]
  const WY = 0.3 / K
  boxAt(L, 0.45, 1.8, 0, y, 0, DECK)
  for (const s of S) boxAt(L, 0.3, 0.12, 0, y + 0.3, s, STEEL)
  const piers = (xs: number[]) => xs.forEach((x) => boxAt(0.8, y + 0.6, 1.4, x, (y - 0.6) / 2, 0, PIER))
  const approach = (a0: number) => {
    const xs: number[] = []
    for (let x = -L / 2 + 5; x < -a0 - 1; x += 7) xs.push(x)
    for (let x = L / 2 - 5; x > a0 + 1; x -= 7) xs.push(x)
    piers(xs)
  }
  const rib = (x0: number, x1: number, base: number, rise: number, z: number, t: number, below = false) => {
    const n = 14
    const pts: [number, number][] = []
    for (let i = 0; i <= n; i++) {
      const u = i / n
      pts.push([x0 + (x1 - x0) * u, base + (below ? -1 : 1) * rise * (1 - (2 * u - 1) ** 2)])
    }
    for (let i = 0; i < n; i++) beam(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], z, t)
    return pts
  }
  const tiedArch = (cx: number, span: number, rise: number, double: boolean) => {
    const x0 = cx - span / 2
    const x1 = cx + span / 2
    for (const s of S) {
      const pts = rib(x0, x1, y + 0.3, rise, s, 0.34)
      for (let i = 1; i < pts.length - 1; i++) beam(pts[i][0], y + 0.3, pts[i][0], pts[i][1], s, 0.07)
    }
    for (let i = 3; i <= 11; i += 2) {
      const u = i / 14
      boxAt(0.14, 0.14, 1.8, x0 + span * u, y + 0.3 + rise * (1 - (2 * u - 1) ** 2), 0, STEEL)
    }
    if (double) boxAt(span + 2, 0.35, 1.7, cx, y - 1.1, 0, DECK)
    piers([x0, x1])
  }
  const trussSpan = (x0: number, x1: number, hf: (u: number) => number) => {
    const n = Math.max(4, Math.round((x1 - x0) / 1.6))
    for (const s of S)
      for (let i = 0; i < n; i++) {
        const xa = x0 + ((x1 - x0) * i) / n
        const xb = x0 + ((x1 - x0) * (i + 1)) / n
        const ha = hf(i / n)
        const hb = hf((i + 1) / n)
        beam(xa, y + 0.3 + ha, xb, y + 0.3 + hb, s, 0.14)
        beam(xb, y + 0.3, xb, y + 0.3 + hb, s, 0.07)
        if (i < n / 2) beam(xa, y + 0.3 + ha, xb, y + 0.3, s, 0.06)
        else beam(xa, y + 0.3, xb, y + 0.3 + hb, s, 0.06)
      }
  }

  switch (form) {
    case 'tied_arch':
    case 'tied_arch_double': {
      const span = Math.min(L * 0.6, 46)
      tiedArch(0, span, span * 0.17, form === 'tied_arch_double')
      approach(span / 2)
      break
    }
    case 'twin_arch': {
      const span = L * 0.32
      tiedArch(-L * 0.19, span, span * 0.2, false)
      tiedArch(L * 0.19, span, span * 0.2, false)
      approach(L * 0.35)
      break
    }
    case 'deck_arch': {
      const n = Math.max(3, Math.round(L / 13))
      const sp = L / n
      const xs: number[] = []
      for (let k = 0; k < n; k++) {
        const x0 = -L / 2 + k * sp
        xs.push(x0)
        for (const s of [-0.6, 0.6]) {
          const rise = y - WY - 0.6
          rib(x0, x0 + sp, WY + 0.2, rise, s, 0.3)
          for (let i = 2; i < 14; i += 2) {
            const u = i / 14
            const x = x0 + sp * u
            beam(x, WY + 0.2 + rise * (1 - (2 * u - 1) ** 2), x, y - 0.2, s, 0.08)
          }
        }
      }
      xs.push(L / 2)
      piers(xs)
      break
    }
    case 'suspension': {
      const tx = L * 0.24
      const th = 3.8
      for (const x of [-tx, tx]) {
        for (const s of S) boxAt(0.32, th + 0.6, 0.32, x, y + th / 2, s, STEEL)
        boxAt(0.3, 0.3, 2.1, x, y + th, 0, STEEL)
      }
      piers([-tx, tx])
      const cab = (x: number) => {
        const ax = Math.abs(x)
        return ax <= tx ? y + 0.8 + (th - 0.8) * (ax / tx) ** 2 : y + th - (th - 0.4) * ((ax - tx) / (L / 2 - tx))
      }
      for (const s of S) {
        let px = -L / 2
        let py = cab(px)
        for (let x = -L / 2 + 1; x <= L / 2 + 0.01; x += 1) {
          const cy = cab(x)
          beam(px, py, x, cy, s, 0.08)
          if (Math.abs(Math.abs(x) - tx) > 0.6) beam(x, y + 0.3, x, cy, s, 0.03)
          px = x
          py = cy
        }
      }
      approach(L / 2 - 1)
      break
    }
    case 'lenticular': {
      const sp = L * 0.4
      for (const cx of [-L * 0.21, L * 0.21]) {
        for (const s of S) {
          const top = rib(cx - sp / 2, cx + sp / 2, y + 0.3, 2.2, s, 0.18)
          const bot = rib(cx - sp / 2, cx + sp / 2, y + 0.3, 1.4, s, 0.14, true)
          top.forEach(([x, yy], i) => {
            if (i > 0 && i < top.length - 1) beam(x, bot[i][1], x, yy, s, 0.06)
          })
        }
        piers([cx - sp / 2, cx + sp / 2])
      }
      approach(L * 0.41)
      break
    }
    case 'cantilever': {
      const a0 = L * 0.18
      trussSpan(-L * 0.45, L * 0.45, (u) => {
        const x = Math.abs(u * 2 - 1)
        return 1.1 + 2.4 * Math.max(0, 1 - Math.abs(x - 0.45) / 0.3)
      })
      piers([-a0 * 1.5, a0 * 1.5])
      approach(L * 0.45)
      break
    }
    case 'truss': {
      const n = Math.max(2, Math.round(L / 18))
      const sp = (L * 0.9) / n
      const xs: number[] = []
      for (let k = 0; k < n; k++) {
        const x0 = -L * 0.45 + k * sp
        trussSpan(x0, x0 + sp, (u) => 1.7 * Math.min(1, Math.min(u, 1 - u) * 7))
        xs.push(x0)
      }
      xs.push(L * 0.45)
      piers(xs)
      break
    }
    default: {
      boxAt(L, 0.9, 1.4, 0, y - 0.6, 0, STEEL)
      const xs: number[] = []
      for (let x = -L / 2 + 4; x < L / 2; x += 8) xs.push(x)
      piers(xs)
    }
  }
  const g = new THREE.Group()
  for (const [c, geos] of parts) {
    const m = new THREE.Mesh(mergeGeometries(geos, false), mat(c))
    m.castShadow = true
    m.receiveShadow = true
    g.add(m)
    geos.forEach((q) => q.dispose())
  }
  g.scale.setScalar(K)
  return g
}
