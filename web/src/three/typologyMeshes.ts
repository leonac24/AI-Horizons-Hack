// Low-poly building models for the 3D lot view. Which shape to draw comes from
// `building.massing` in typologies.yaml; nothing here knows a typology id.
import * as THREE from 'three'

export interface BuildingForm {
  w: number // footprint width along the street, ft
  d: number // footprint depth, ft
  stories: number
  massing: string
  body: string
  roof: string
}

const mats = new Map<string, THREE.MeshStandardMaterial>()
export function mat(color: string, extra?: THREE.MeshStandardMaterialParameters): THREE.MeshStandardMaterial {
  const k = color + (extra ? JSON.stringify(extra) : '')
  let m = mats.get(k)
  if (!m) {
    m = new THREE.MeshStandardMaterial({ color, roughness: 0.92, metalness: 0, flatShading: true, ...extra })
    mats.set(k, m)
  }
  return m
}

export function mesh(geo: THREE.BufferGeometry, color: string): THREE.Mesh {
  const m = new THREE.Mesh(geo, mat(color))
  m.castShadow = true
  m.receiveShadow = true
  return m
}

export function box(w: number, h: number, d: number, color: string): THREE.Mesh {
  return mesh(new THREE.BoxGeometry(w, h, d), color)
}

const FLOOR_FT = 10
const WINDOW = '#2e4a66'
const DOOR = '#3f4f63'
const TRIM = '#a9b6c4'

function gable(w: number, d: number, rise: number, color: string): THREE.Mesh {
  const s = new THREE.Shape()
  s.moveTo(-w / 2 - 1, 0)
  s.lineTo(w / 2 + 1, 0)
  s.lineTo(0, rise)
  s.lineTo(-w / 2 - 1, 0)
  const g = new THREE.ExtrudeGeometry(s, { depth: d + 2, bevelEnabled: false })
  g.translate(0, 0, -(d + 2) / 2)
  return mesh(g, color)
}

function windowsOn(g: THREE.Group, w: number, d: number, floors: number, cx: number, cz: number, y0 = 0): void {
  const n = Math.max(1, Math.floor((w - 4) / 7))
  for (let f = 0; f < floors; f++)
    for (let i = 0; i < n; i++) {
      const x = cx - w / 2 + (i + 0.5) * (w / n)
      const y = y0 + f * FLOOR_FT + 5.5
      for (const s of [1, -1]) {
        const m = box(3, 4.5, 0.6, WINDOW)
        m.castShadow = false
        m.position.set(x, y, cz + s * (d / 2 + 0.15))
        g.add(m)
      }
    }
}

interface HouseOpts {
  w: number
  d: number
  floors: number
  x?: number
  z?: number
  body: string
  roof: string
  flat?: boolean
  doors?: number
  windows?: boolean
}

export function house(g: THREE.Group, { w, d, floors, x = 0, z = 0, body, roof, flat = false, doors = 1, windows = true }: HouseOpts): void {
  const h = floors * FLOOR_FT
  const b = box(w, h, d, body)
  b.position.set(x, h / 2, z)
  g.add(b)
  if (flat) {
    const c = box(w + 1.2, 1.4, d + 1.2, roof)
    c.position.set(x, h + 0.7, z)
    g.add(c)
  } else {
    const r = gable(w, d, w * 0.38, roof)
    r.position.set(x, h, z)
    g.add(r)
  }
  if (windows) windowsOn(g, w, d, Math.floor(floors), x, z)
  for (let i = 0; i < doors; i++) {
    const dr = box(3.5, 7, 0.7, DOOR)
    const dx = doors === 1 ? w * 0.25 : i ? w * 0.3 : -w * 0.3
    dr.position.set(x + dx, 3.5, z + d / 2 + 0.3)
    g.add(dr)
  }
}

function flatBlock(g: THREE.Group, f: BuildingForm, podium: boolean): void {
  const h = f.stories * FLOOR_FT
  const base = podium ? 12 : 0
  if (podium) {
    const p = box(f.w, base, f.d, '#4a5f78')
    p.position.y = base / 2
    g.add(p)
    for (let i = 0, n = Math.max(1, Math.floor(f.w / 16)); i < n; i++) {
      const sf = box(12, 8, 0.6, '#9fe0ff')
      sf.position.set(-f.w / 2 + (i + 0.5) * (f.w / n), 5, f.d / 2 + 0.2)
      g.add(sf)
    }
  }
  const up = box(f.w, h - base, f.d, f.body)
  up.position.y = base + (h - base) / 2
  g.add(up)
  const parapet = box(f.w + 0.8, 1.8, f.d + 0.8, f.roof)
  parapet.position.y = h + 0.9
  g.add(parapet)
  const mech = box(Math.min(14, f.w / 4), 5, Math.min(10, f.d / 6), TRIM)
  mech.position.set(f.w * 0.15, h + 3.5, -f.d * 0.12)
  g.add(mech)
  if (!podium) {
    const canopy = box(12, 0.8, 5, f.roof)
    canopy.position.set(0, 9, f.d / 2 + 2.5)
    g.add(canopy)
  }
  windowsOn(g, f.w, f.d, Math.round((h - base) / FLOOR_FT), 0, 0, base)
}

/** A building group centered on its footprint, front facing +z (the street). */
export function makeBuilding(f: BuildingForm): THREE.Group {
  const g = new THREE.Group()
  switch (f.massing) {
    case 'house_with_rear_unit': {
      const mainD = f.d * 0.53
      const rearD = f.d * 0.31
      house(g, { w: f.w, d: mainD, floors: f.stories, z: f.d / 2 - mainD / 2, body: f.body, roof: f.roof })
      house(g, { w: f.w * 0.7, d: rearD, floors: Math.max(1, f.stories - 0.5), z: -f.d / 2 + rearD / 2, body: f.body, roof: f.roof })
      break
    }
    case 'gable_house_two_doors':
      house(g, { w: f.w, d: f.d, floors: f.stories, body: f.body, roof: f.roof, doors: 2 })
      break
    case 'flat_rowhouse': {
      house(g, { w: f.w, d: f.d, floors: f.stories, flat: true, body: f.body, roof: f.roof })
      const stoop = box(6, 2, 4, '#dfe6ee')
      stoop.position.set(f.w * 0.25, 1, f.d / 2 + 2)
      g.add(stoop)
      break
    }
    case 'walkup':
      flatBlock(g, f, false)
      break
    case 'podium_midrise':
      flatBlock(g, f, true)
      break
    default:
      house(g, { w: f.w, d: f.d, floors: f.stories, body: f.body, roof: f.roof })
  }
  return g
}
