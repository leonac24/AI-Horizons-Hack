// three.js engine for the Lotline simulator: a stylized city diorama with every
// vacant parcel, and a lot scene where the user drags buildings onto the parcel.
// Framework-free; React talks to it through the returned API and callbacks.
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { frontage, loadBasemap, makeHoodLabels, makeLots, makeStreets, type BasemapConfig, type HoodLabels, type Lots, type Rect, type Streets } from './basemap'
import { makeBridge } from './bridges'
import { loadTerrain, WATER_LEVEL, type Terrain } from './terrain'
import { box, house, makeBuilding, mat, mesh, type BuildingForm } from './typologyMeshes'

export interface SceneConfig {
  origin: [number, number]
  scale: [number, number]
  half_extent: number
  rivers: [number, number][][]
  bridges: [string, number, number, string, number][] // name, lat, lon, form, length_m
  basemap?: BasemapConfig
}

export interface ParcelPoint {
  id: string
  lon: number
  lat: number
  public: boolean
}

export interface PinLot extends ParcelPoint {
  neighborhood: string | null
  zoning: string | null
  area: number
}

export interface LotInput {
  id: string
  lon: number
  lat: number
  frontage: number
  depth: number
  hill: boolean
}

export interface Placement {
  uid: string
  typ: string
  x: number
  z: number
  rot: number
}

export interface PointerLike {
  clientX: number
  clientY: number
  preventDefault?: () => void
}

export interface EngineOptions {
  scene: SceneConfig
  forms: Record<string, BuildingForm>
  parcels: ParcelPoint[]
  dataBase: string // where terrain.json / terrain.bin are served
  snap?: number
  onSelectLot?: (id: string) => void
  onChange?: (list: Placement[]) => void
  onSelect?: (uid: string | null) => void
  onUndo?: () => void
  onRedo?: () => void
  onReady?: () => void // city terrain and basemap are built
}

/** Buildable area inside the setbacks, in feet from each lot edge (street = front). */
export interface Envelope {
  front: number
  rear: number
  left: number
  right: number
}

export interface Engine {
  goLot(lot: LotInput, list?: Placement[]): Promise<void>
  goCity(): Promise<void>
  setPlacements(list: Placement[]): void
  setWarnings(uids: string[]): void
  setEnvelope(env: Envelope | null): void
  setShowPlan(v: boolean): void
  setVisibleParcels(ids: Set<string> | null): void
  setPins(pins: PinLot[]): void
  /** City view only: fly the camera so these lots fill the screen. */
  frameLots(lots: { lon: number; lat: number }[]): void
  beginDrag(typ: string, e?: PointerLike): void
  rotateSelected(): void
  deleteSelected(): void
  clearSelection(): void
  resetView(): void
  /** Leave the intro: swoop from the showcase orbit down to the working city view. */
  enter(): Promise<void>
  dispose(): void
}

const BG = '#cfeaff' // haze
const FADE = '#0d1b2a'
const GREEN = '#2fd06b' // plan, selection, lot outline
const VALID = '#7dffb0'
const INVALID = '#ff4a3a'
// Map markers avoid green and blue so they stand out from terrain and water.
export const MARKER_COLORS = { pin: '#ffd23f', public: '#ff4d6d', other: '#ff9f1c' } as const
const PIN = MARKER_COLORS.pin
const DOT_PUBLIC = MARKER_COLORS.public
const DOT_OTHER = MARKER_COLORS.other
const WATER = '#3aa7ff'
// Camera near plane as a share of orbit distance, and its ceiling.
const NEAR_PER_DISTANCE = 0.03
const NEAR_MAX = 60

function skyTexture(): THREE.Texture {
  const c = document.createElement('canvas')
  c.width = 4
  c.height = 256
  const g = c.getContext('2d')!
  const gr = g.createLinearGradient(0, 0, 0, 256)
  gr.addColorStop(0, '#3f9bff')
  gr.addColorStop(0.55, '#8cc8ff')
  gr.addColorStop(1, '#dff1ff')
  g.fillStyle = gr
  g.fillRect(0, 0, 4, 256)
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

function rng(seed: number): () => number {
  let s = seed >>> 0
  return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296
}

function rectOutline(w: number, d: number, color: string, th = 0.9, y = 0.9): THREE.Group {
  const g = new THREE.Group()
  const m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95 })
  for (const [bw, bd, x, z] of [
    [w + th, th, 0, d / 2],
    [w + th, th, 0, -d / 2],
    [th, d + th, w / 2, 0],
    [th, d + th, -w / 2, 0],
  ]) {
    const b = new THREE.Mesh(new THREE.BoxGeometry(bw, 0.4, bd), m)
    b.position.set(x, y, z)
    g.add(b)
  }
  return g
}

function tree(r: () => number): THREE.Group {
  const g = new THREE.Group()
  const h = 14 + r() * 12
  const tr = mesh(new THREE.CylinderGeometry(0.8, 1, 6, 5), '#8a5a3b')
  tr.position.y = 3
  g.add(tr)
  const c = mesh(new THREE.IcosahedronGeometry(5 + r() * 3, 0), r() > 0.5 ? '#3fae4a' : '#5cc45a')
  c.position.y = h * 0.6 + 3
  c.scale.y = 1.25
  g.add(c)
  return g
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

function lightRig(scene: THREE.Scene, x: number, y: number, z: number, ext: number): void {
  scene.add(new THREE.HemisphereLight('#fff4e0', '#7fa36a', 1.25))
  const d = new THREE.DirectionalLight('#ffe9c9', 2.3)
  d.position.set(x, y, z)
  d.castShadow = true
  Object.assign(d.shadow.camera, { left: -ext, right: ext, top: ext, bottom: -ext, near: 10, far: 3000 })
  d.shadow.mapSize.set(2048, 2048)
  d.shadow.bias = -0.0006
  d.shadow.normalBias = 0.6
  scene.add(d)
}

interface PlacedObj {
  p: Placement
  root: THREE.Group
  sel: THREE.Group
  warn: THREE.Group
  model: THREE.Group
}

interface Drag {
  typ: string
  rot: number
  uid: string | null
  ghost: THREE.Group
  gm: THREE.MeshBasicMaterial
  ok: boolean
  x: number
  z: number
  ox: number
  oz: number
  pending: boolean
}

export function createEngine(container: HTMLElement, opts: EngineOptions): Engine {
  const F = opts.forms
  const snap = opts.snap ?? 2
  const [LON0, LAT0] = opts.scene.origin
  const [KX, KZ] = opts.scene.scale
  const HALF = opts.scene.half_extent
  const toXZ = (lon: number, lat: number): [number, number] => [(lon - LON0) * KX, -(lat - LAT0) * KZ]

  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio))
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFShadowMap
  renderer.setClearColor(BG)
  const SKY = skyTexture()
  Object.assign(renderer.domElement.style, {
    position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block', touchAction: 'none',
  })
  container.appendChild(renderer.domElement)
  const labels = document.createElement('div')
  Object.assign(labels.style, { position: 'absolute', inset: '0', pointerEvents: 'none', overflow: 'hidden' })
  container.appendChild(labels)
  const fade = document.createElement('div')
  Object.assign(fade.style, {
    position: 'absolute', inset: '0', background: FADE, opacity: '0', pointerEvents: 'none', transition: 'opacity 260ms ease',
  })
  container.appendChild(fade)

  const camera = new THREE.PerspectiveCamera(38, 1, 1, 8000)
  const canvas = renderer.domElement
  const ray = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  const ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)

  // ---------- city ----------
  const city = new THREE.Scene()
  city.background = SKY
  city.fog = new THREE.Fog(BG, 1200, 3000)
  lightRig(city, -420, 720, 320, 700)
  const R = rng(20260926)
  const M4 = new THREE.Matrix4()
  const C = new THREE.Color()
  const Q = new THREE.Quaternion()
  const inMap = (x: number, z: number) => Math.abs(x) <= HALF && Math.abs(z) <= HALF

  const loading = document.createElement('div')
  loading.className = 'engine-pill'
  loading.textContent = 'Loading terrain…'
  container.appendChild(loading)

  let terrain: Terrain | null = null
  const heightAt = (x: number, z: number) => (terrain ? Math.max(WATER_LEVEL, terrain.heightAt(x, z)) : 0)

  // Real vacant parcels as instanced dots (placed once the terrain is known).
  const parcels = opts.parcels
  const parcelXZ = parcels.map((p) => toXZ(p.lon, p.lat))
  const parcelY = new Float32Array(parcels.length)
  const dots = new THREE.InstancedMesh(new THREE.CylinderGeometry(2.4, 2.4, 1, 8), new THREE.MeshBasicMaterial({ color: '#fff' }), Math.max(1, parcels.length))
  const dotVisible = new Uint8Array(parcels.length).fill(1)
  // Zoomed in, lots with an outline keep only a small center marker.
  const outlined = new Uint8Array(parcels.length)
  let outlineMode = false
  const writeDots = () => {
    parcels.forEach((_p, i) => {
      const [x, z] = parcelXZ[i]
      const s = dotVisible[i] ? (outlineMode && outlined[i] ? 0.08 : 1) : 0
      M4.compose(new THREE.Vector3(x, parcelY[i] + 0.8, z), Q, new THREE.Vector3(s, s, s))
      dots.setMatrixAt(i, M4)
    })
    dots.instanceMatrix.needsUpdate = true
  }
  parcels.forEach((p, i) => dots.setColorAt(i, C.set(p.public ? DOT_PUBLIC : DOT_OTHER)))
  writeDots()
  city.add(dots)

  // Pins (suggested lots and search hits) with DOM labels.
  interface Pin { g: THREE.Group; ring: THREE.Mesh; hit: THREE.Mesh; el: HTMLDivElement; lot: PinLot; w: number; h: number }
  const pins = new Map<string, Pin>()
  let pinList: PinLot[] = []
  const pinGeo = {
    pad: new THREE.CylinderGeometry(10, 10, 3, 24),
    beam: new THREE.CylinderGeometry(1.2, 1.2, 70, 8),
    ring: new THREE.TorusGeometry(15, 0.9, 6, 40),
    hit: new THREE.CylinderGeometry(20, 20, 80, 8),
  }
  const pinMats = {
    pad: new THREE.MeshStandardMaterial({ color: PIN, emissive: PIN, emissiveIntensity: 0.35 }),
    beam: new THREE.MeshBasicMaterial({ color: PIN, transparent: true, opacity: 0.55 }),
    ring: new THREE.MeshBasicMaterial({ color: PIN }),
    hit: new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }),
  }
  function addPin(lot: PinLot): void {
    const [x, z] = toXZ(lot.lon, lot.lat)
    const g = new THREE.Group()
    g.position.set(x, heightAt(x, z), z)
    const pad = new THREE.Mesh(pinGeo.pad, pinMats.pad)
    pad.position.y = 1.5
    const beam = new THREE.Mesh(pinGeo.beam, pinMats.beam)
    beam.position.y = 35
    const ring = new THREE.Mesh(pinGeo.ring, pinMats.ring)
    ring.rotation.x = Math.PI / 2
    ring.position.y = 2
    const hit = new THREE.Mesh(pinGeo.hit, pinMats.hit)
    hit.position.y = 40
    hit.userData.lotId = lot.id
    g.add(pad, beam, ring, hit)
    city.add(g)
    const el = document.createElement('div')
    el.className = 'pin-label'
    const name = document.createElement('div')
    name.className = 'pin-name'
    name.textContent = lot.neighborhood ?? lot.id
    const detail = document.createElement('div')
    detail.className = 'pin-detail'
    detail.textContent = `${lot.zoning ?? '—'} · ${Math.round(lot.area).toLocaleString()} sf${lot.public ? ' · public' : ''}`
    el.append(name, detail)
    el.addEventListener('click', () => opts.onSelectLot?.(lot.id))
    labels.appendChild(el)
    pins.set(lot.id, { g, ring, hit, el, lot, w: 0, h: 0 })
  }
  function renderPins(): void {
    for (const p of pins.values()) {
      city.remove(p.g)
      p.el.remove()
    }
    pins.clear()
    pinList.forEach(addPin)
  }

  let streets: Streets | null = null
  let lots: Lots | null = null
  let hoods: HoodLabels | null = null
  let pendingVisible: Set<string> | null = null
  const groundMeshes: THREE.Mesh[] = []
  const setLineResolution = (w: number, h: number) => {
    streets?.setResolution(w, h)
    lots?.setResolution(w, h)
  }

  function buildCity(t: Terrain, base: Awaited<ReturnType<typeof loadBasemap>>): void {
    terrain = t
    const bm = opts.scene.basemap
    // Water plane at the normal pool; land sits above it and the riverbed well
    // below. No polygon offset: at low depth precision it pushed the water behind
    // the riverbed, which then showed through. Clear height gaps plus the
    // distance-scaled near plane (see frame) keep the surfaces apart instead.
    const water = new THREE.Mesh(
      new THREE.PlaneGeometry(6000, 6000).rotateX(-Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: WATER, roughness: 0.28, metalness: 0.1 }),
    )
    water.position.y = WATER_LEVEL
    water.receiveShadow = true
    city.add(water)
    // Ground: vivid inside city limits, pale countryside outside.
    const cIn = { flat: new THREE.Color('#a6dc7e'), slope: new THREE.Color('#3f9e48'), up: new THREE.Color('#7fcb62'), rock: new THREE.Color('#9a8f78') }
    const cOut = { flat: new THREE.Color('#cdeebb'), slope: new THREE.Color('#a9d99a'), up: new THREE.Color('#bfe6ad'), rock: new THREE.Color('#c9dcb4') }
    for (const grid of t.grids) {
      const n = Math.round((grid.extent * 2) / grid.step)
      const geo = new THREE.PlaneGeometry(grid.extent * 2, grid.extent * 2, n, n).rotateX(-Math.PI / 2)
      const pos = geo.attributes.position
      const cols = new Float32Array(pos.count * 3)
      for (let k = 0; k < pos.count; k++) {
        const x = pos.getX(k)
        const z = pos.getZ(k)
        const h = grid.h(x, z)
        pos.setY(k, h)
        const sl = t.slopeAt(x, z)
        const P = inMap(x, z) ? cIn : cOut
        const c = sl > 0.4 ? P.rock : sl > 0.2 ? P.slope : h < 1.4 ? P.flat : P.up
        cols[k * 3] = c.r
        cols[k * 3 + 1] = c.g
        cols[k * 3 + 2] = c.b
      }
      geo.setAttribute('color', new THREE.BufferAttribute(cols, 3))
      geo.computeVertexNormals()
      const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, flatShading: true }))
      m.receiveShadow = true
      city.add(m)
      groundMeshes.push(m)
    }
    // Orientation layers: real streets, vacant-lot outlines, neighborhood names.
    if (bm && base.streets) {
      streets = makeStreets(base.streets, bm, toXZ, heightAt)
      city.add(streets.group)
    }
    // Hillside canopy on steep slopes, a few yard trees elsewhere; none over a street.
    const tpos: [number, number, boolean][] = []
    for (let x = -HALF + 4; x < HALF; x += 9)
      for (let z = -HALF + 4; z < HALF; z += 9) {
        const xx = x + (R() - 0.5) * 7
        const zz = z + (R() - 0.5) * 7
        if (t.isWater(xx, zz) || streets?.near(xx, zz, 4)) continue
        const sl = t.slopeAt(xx, zz)
        if (sl > 0.16 ? R() < 0.38 : R() < 0.025) tpos.push([xx, zz, sl > 0.16])
      }
    const greens = ['#2f7d32', '#3b8f3a', '#46993d', '#56a646', '#6a9f3a']
    const trees = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 0), mat('#ffffff'), Math.max(1, tpos.length))
    trees.receiveShadow = true
    tpos.forEach(([x, z, wood], i) => {
      const r = wood ? 5 + R() * 3.5 : 3.2 + R() * 1.8
      const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(R() * 0.6, R() * Math.PI, R() * 0.6))
      M4.compose(new THREE.Vector3(x, heightAt(x, z) + r * 0.55, z), q, new THREE.Vector3(r, r * (0.75 + R() * 0.25), r))
      trees.setMatrixAt(i, M4)
      trees.setColorAt(i, C.set(greens[Math.floor(R() * greens.length)]))
    })
    city.add(trees)
    if (bm && base.lots) {
      const pub = new Map(parcels.map((p) => [p.id, p.public]))
      const made = makeLots(base.lots, (id) => (pub.get(id) ? DOT_PUBLIC : DOT_OTHER), toXZ, heightAt)
      made.obj.visible = false
      parcels.forEach((p, i) => (outlined[i] = made.ids.has(p.id) ? 1 : 0))
      if (pendingVisible) made.setVisible(pendingVisible)
      city.add(made.obj)
      lots = made
    }
    if (bm && base.hoods) hoods = makeHoodLabels(base.hoods, bm, labels, toXZ, heightAt)
    setLineResolution(container.clientWidth, container.clientHeight)
    // Decorative buildings — not buildings from data. Taller near the origin (Downtown).
    // With street data they line the real streets and stay off vacant lots.
    if (streets) {
      const lotCell = new Set(parcelXZ.map(([x, z]) => `${Math.round(x / 2)},${Math.round(z / 2)}`))
      const nearLot = (x: number, z: number) => {
        for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) if (lotCell.has(`${Math.round(x / 2) + a},${Math.round(z / 2) + b}`)) return true
        return false
      }
      const spots = frontage(streets,(x, z) => !inMap(x, z) || t.isWater(x, z) || t.slopeAt(x, z) > 0.3 || nearLot(x, z) || !!lots?.at(x, z), R)
      const houses = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), mat('#ffffff'), Math.max(1, spots.length))
      houses.castShadow = true
      houses.receiveShadow = true
      const hcol = ['#fff1d6', '#ffd9cc', '#d6ecff', '#e2f7d0', '#ffffff', '#fff0a8', '#ffb4a2', '#c9d6ff']
      const tcol = ['#ff5d5d', '#ff9f1c', '#ffd23f', '#1f8bff', '#9b7bff', '#13c2c2', '#ffffff', '#ffe9b8']
      const E = new THREE.Euler()
      const rq = new THREE.Quaternion()
      spots.forEach(([x, z, w, d, ang], i) => {
        const core = Math.max(0, 1 - Math.hypot(x - 10, z + 5) / 55)
        const s = 1 + core * 1.2
        const h = 1.2 + R() * 1.6 + core * core * (25 + R() * 60)
        M4.compose(new THREE.Vector3(x, heightAt(x, z) - 0.3, z), rq.setFromEuler(E.set(0, -ang, 0)), new THREE.Vector3(w * s, h, d * s))
        houses.setMatrixAt(i, M4)
        houses.setColorAt(i, C.set(core > 0.05 ? tcol[Math.floor(R() * tcol.length)] : hcol[Math.floor(R() * hcol.length)]))
      })
      city.add(houses)
    }
    const cells: [number, number][] = []
    if (!streets) for (let x = -HALF + 20; x <= HALF - 20; x += 22)
      for (let z = -HALF + 20; z <= HALF - 20; z += 22) {
        if (R() < 0.3) continue
        if (t.isWater(x, z) || t.isWater(x + 12, z) || t.isWater(x - 12, z) || t.isWater(x, z + 12) || t.isWater(x, z - 12)) continue
        if (t.slopeAt(x, z) > 0.18) continue
        cells.push([x, z])
      }
    const blocks = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), mat('#ffffff'), Math.max(1, cells.length))
    blocks.castShadow = true
    blocks.receiveShadow = true
    const bcol = ['#ff5d5d', '#ff9f1c', '#ffd23f', '#3ccf6e', '#1f8bff', '#9b7bff', '#ff5da2', '#13c2c2', '#ffffff', '#ffe9b8']
    cells.forEach(([x, z], i) => {
      const dt = Math.hypot(x - 10, z + 5)
      const core = Math.max(0, 1 - dt / 85)
      const h = dt < 85 ? 18 + R() * 40 + core * core * (50 + R() * 70) : 3 + R() * 7
      const s = dt < 85 ? 13 : 10 + R() * 6
      const px = x + (R() - 0.5) * 4
      const pz = z + (R() - 0.5) * 4
      M4.compose(new THREE.Vector3(px, heightAt(px, pz) - 0.5, pz), Q, new THREE.Vector3(s, h, s))
      blocks.setMatrixAt(i, M4)
      blocks.setColorAt(i, C.set(bcol[Math.floor(R() * bcol.length)]))
    })
    city.add(blocks)
    // City-limits fence: translucent wall with a white top line and green base line.
    {
      const pts: [number, number][] = []
      const E = HALF + 4
      const edge = (x0: number, z0: number, x1: number, z1: number) => {
        const n = Math.ceil(Math.hypot(x1 - x0, z1 - z0) / 12)
        for (let k = 0; k < n; k++) pts.push([x0 + ((x1 - x0) * k) / n, z0 + ((z1 - z0) * k) / n])
      }
      edge(-E, -E, E, -E)
      edge(E, -E, E, E)
      edge(E, E, -E, E)
      edge(-E, E, -E, -E)
      pts.push(pts[0])
      const wall: number[] = []
      const top: number[] = []
      const base: number[] = []
      const idx: number[] = []
      const alpha = new Float32Array(pts.length * 2)
      pts.forEach(([x, z], k) => {
        const h = heightAt(x, z)
        wall.push(x, h, z, x, h + 14, z)
        top.push(x, h + 14, z)
        base.push(x, h + 0.8, z)
        alpha[k * 2] = 0.55
        if (k < pts.length - 1) idx.push(k * 2, k * 2 + 1, k * 2 + 2, k * 2 + 1, k * 2 + 3, k * 2 + 2)
      })
      const wg = new THREE.BufferGeometry()
      wg.setAttribute('position', new THREE.Float32BufferAttribute(wall, 3))
      wg.setAttribute('alpha', new THREE.BufferAttribute(alpha, 1))
      wg.setIndex(idx)
      city.add(new THREE.Mesh(wg, new THREE.ShaderMaterial({
        transparent: true, depthWrite: false, side: THREE.DoubleSide, uniforms: { c: { value: new THREE.Color('#ffffff') } },
        vertexShader: 'attribute float alpha; varying float va; void main(){ va = alpha; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
        fragmentShader: 'uniform vec3 c; varying float va; void main(){ gl_FragColor = vec4(c, va); }',
      })))
      const tg = new THREE.BufferGeometry()
      tg.setAttribute('position', new THREE.Float32BufferAttribute(top, 3))
      city.add(new THREE.Line(tg, new THREE.LineBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.9 })))
      const bg = new THREE.BufferGeometry()
      bg.setAttribute('position', new THREE.Float32BufferAttribute(base, 3))
      city.add(new THREE.Line(bg, new THREE.LineBasicMaterial({ color: GREEN })))
    }
    // Bridges: snapped onto water and turned across the narrowest crossing.
    for (const [, lat, lon, form, lengthM] of opts.scene.bridges) {
      let [cx, cz] = toXZ(lon, lat)
      if (!t.isWater(cx, cz)) {
        let best: [number, number] | null = null
        for (let r = 1.5; r <= 16 && !best; r += 1.5)
          for (let a = 0; a < 360; a += 15) {
            const x = cx + Math.cos((a * Math.PI) / 180) * r
            const z = cz + Math.sin((a * Math.PI) / 180) * r
            if (t.isWater(x, z)) {
              best = [x, z]
              break
            }
          }
        if (!best) continue // no river nearby at this resolution; skip rather than float a bridge on land
        ;[cx, cz] = best
      }
      let bestA = 0
      let bestW = 1e9
      for (let a = 0; a < 180; a += 3) {
        const dx = Math.cos((a * Math.PI) / 180)
        const dz = Math.sin((a * Math.PI) / 180)
        let w = 0
        for (const sgn of [1, -1]) {
          let s = 0
          while (s < 90 && t.isWater(cx + dx * sgn * s, cz + dz * sgn * s)) s += 0.7
          w += s
        }
        if (w < bestW) {
          bestW = w
          bestA = a
        }
      }
      const L = Math.max(bestW + 16, lengthM / 17)
      const ang = (bestA * Math.PI) / 180
      const dx = Math.cos(ang)
      const dz = Math.sin(ang)
      const e1 = heightAt(cx - (dx * L) / 2, cz - (dz * L) / 2)
      const e2 = heightAt(cx + (dx * L) / 2, cz + (dz * L) / 2)
      const b = makeBridge(form, L, Math.min(Math.max(Math.min(e1, e2) + 1, 5), 9))
      b.position.set(cx, 0, cz)
      b.rotation.y = -ang
      city.add(b)
    }
    parcels.forEach((_p, i) => (parcelY[i] = heightAt(parcelXZ[i][0], parcelXZ[i][1])))
    writeDots()
    renderPins()
    loading.remove()
    // Showcase: drop from straight overhead into a low, fast orbit
    // (skipped when a lot is already open, e.g. from a shared link).
    if (!selLot) {
      camera.position.set(0, 1650, 200)
      controls.target.set(0, 0, 30)
      void flyTo(...introView(), 3400)
    }
    opts.onReady?.()
  }
  void Promise.all([
    loadTerrain(opts.dataBase, opts.scene.rivers.map((r) => r.map(([lo, la]) => toXZ(lo, la))), HALF),
    loadBasemap(opts.dataBase),
  ]).then(([t, b]) => buildCity(t, b))

  // ---------- lot ----------
  let lotScene: { scene: THREE.Scene; W: number; D: number } | null = null
  let placedGroup: THREE.Group | null = null
  const placed = new Map<string, PlacedObj>()
  let placements: Placement[] = []
  let selUid: string | null = null
  let warnSet = new Set<string>()
  let showPlan = true
  const dims = (typ: string, rot: number): [number, number] => (rot % 2 ? [F[typ].d, F[typ].w] : [F[typ].w, F[typ].d])

  let envelope: Envelope | null = null
  let envelopeLine: THREE.Line | null = null
  function drawEnvelope(): void {
    if (!lotScene) return
    if (envelopeLine) {
      lotScene.scene.remove(envelopeLine)
      envelopeLine.geometry.dispose()
      envelopeLine = null
    }
    const e = envelope
    if (!e || e.front + e.rear + e.left + e.right === 0) return
    const { W, D } = lotScene
    const x0 = -W / 2 + e.left
    const x1 = W / 2 - e.right
    const z0 = -D / 2 + e.rear
    const z1 = D / 2 - e.front
    if (x1 <= x0 || z1 <= z0) return // setbacks swallow the lot; the zoning box says so
    const y = 0.9
    const g = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(x0, y, z0), new THREE.Vector3(x1, y, z0), new THREE.Vector3(x1, y, z1),
      new THREE.Vector3(x0, y, z1), new THREE.Vector3(x0, y, z0),
    ])
    envelopeLine = new THREE.Line(g, new THREE.LineDashedMaterial({ color: '#ffb800', dashSize: 3, gapSize: 2 }))
    envelopeLine.computeLineDistances()
    lotScene.scene.add(envelopeLine)
  }

  function buildLot(lot: LotInput) {
    const s = new THREE.Scene()
    s.background = SKY
    s.fog = new THREE.Fog(BG, 520, 1250)
    const W = lot.frontage
    const D = lot.depth
    const S = Math.max(420, D + 280, W + 320)
    const r = rng(Math.round(W * 131 + D * 17))
    lightRig(s, -170, 320, 200, S / 2 + 40)
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(3600, 3600).rotateX(-Math.PI / 2), mat('#a8dc84'))
    ground.receiveShadow = true
    s.add(ground)
    const EXT = 520
    const walkZ = D / 2 + 6
    const roadZ = D / 2 + 12 + 18
    const farWalk = D / 2 + 48 + 5
    const flat = (m: THREE.Mesh, x: number, y: number, z: number) => {
      m.castShadow = false
      m.position.set(x, y, z)
      s.add(m)
    }
    flat(box(EXT * 4, 0.4, 36, '#5b6672'), 0, 0.2, roadZ)
    for (let x = -EXT * 2; x < EXT * 2; x += 22) flat(box(9, 0.1, 1, '#ffffff'), x, 0.45, roadZ)
    for (const z of [walkZ, farWalk]) flat(box(EXT * 4, 0.7, 10, '#eef3f8'), 0, 0.35, z)
    flat(box(W, 0.6, D, '#eef8df'), 0, 0.3, 0)
    const gp: number[] = []
    for (let x = -W / 2 + 10; x < W / 2; x += 10) gp.push(x, 0.65, -D / 2, x, 0.65, D / 2)
    for (let z = -D / 2 + 10; z < D / 2; z += 10) gp.push(-W / 2, 0.65, z, W / 2, 0.65, z)
    const gg = new THREE.BufferGeometry()
    gg.setAttribute('position', new THREE.Float32BufferAttribute(gp, 3))
    s.add(new THREE.LineSegments(gg, new THREE.LineBasicMaterial({ color: '#b5dc92', transparent: true, opacity: 0.7 })))
    s.add(rectOutline(W, D, GREEN, 0.8, 0.75))
    // Illustrative neighbors — procedural, not the real block.
    const bodies = ['#fff1d6', '#ffd9cc', '#d6ecff', '#e2f7d0', '#ffffff', '#fff0a8']
    const roofs = ['#e2574c', '#3f7cc9', '#f08a24', '#5a6b7d']
    const row = (from: number, dir: number, zFront: number, facing: number) => {
      let x = from
      while (Math.abs(x) < EXT) {
        const w = 18 + Math.floor(r() * 8)
        const d = 34 + Math.floor(r() * 10)
        const g = new THREE.Group()
        house(g, { windows: Math.abs(x) < 240, w, d, floors: r() > 0.4 ? 2 : 3, body: bodies[Math.floor(r() * bodies.length)], roof: roofs[Math.floor(r() * roofs.length)], flat: r() > 0.6 })
        const cx = x + dir * (w / 2)
        g.position.set(cx, 0, zFront - (facing * d) / 2)
        if (facing < 0) g.rotation.y = Math.PI
        s.add(g)
        if (r() > 0.55) {
          const t = tree(r)
          t.position.set(cx, 0, zFront - facing * (d + 16 + r() * 20))
          s.add(t)
        }
        x += dir * (w + 4 + Math.floor(r() * 6))
      }
    }
    row(-W / 2 - 6, -1, D / 2 - 8, 1)
    row(W / 2 + 6, 1, D / 2 - 8, 1)
    row(-EXT, 1, farWalk + 8, -1)
    const backZ = -D / 2 - 112
    row(-EXT, 1, backZ, -1)
    flat(box(EXT * 4, 0.4, 30, '#5b6672'), 0, 0.2, backZ - 20)
    flat(box(EXT * 4, 0.7, 8, '#eef3f8'), 0, 0.35, backZ - 2)
    row(-EXT, 1, backZ - 42, 1)
    for (let x = -EXT; x < EXT; x += 26 + r() * 20) {
      if (Math.abs(x) < W / 2 + 6) continue
      const t = tree(r)
      t.position.set(x, 0, walkZ + 3.5)
      s.add(t)
    }
    for (let k = 0; k < 16; k++) {
      const t = tree(r)
      t.position.set((r() * 2 - 1) * (W / 2 + 60), 0, -D / 2 - 14 - r() * 40)
      s.add(t)
    }
    for (let k = 0; k < 70; k++) {
      const t = tree(r)
      const a = r() * Math.PI * 2
      const d = 300 + r() * 500
      t.position.set(Math.cos(a) * d, 0, -D / 2 - 200 - Math.abs(Math.sin(a)) * d * 0.8)
      t.scale.setScalar(1.3)
      s.add(t)
    }
    if (lot.hill) {
      const h = mesh(new THREE.IcosahedronGeometry(S * 0.42, 1), '#4fae4a')
      h.scale.y = 0.42
      h.position.set(0, -6, -S / 2 - 20)
      s.add(h)
    }
    placedGroup = new THREE.Group()
    s.add(placedGroup)
    return { scene: s, W, D }
  }

  function ghostOf(typ: string) {
    const g = makeBuilding(F[typ])
    const gm = new THREE.MeshBasicMaterial({ color: VALID, transparent: true, opacity: 0.5, depthWrite: false })
    g.traverse((c) => {
      if (c instanceof THREE.Mesh) {
        c.material = gm
        c.castShadow = false
        c.receiveShadow = false
      }
    })
    const fp = new THREE.Mesh(new THREE.BoxGeometry(F[typ].w, 0.3, F[typ].d), gm)
    fp.position.y = 0.8
    g.add(fp)
    return { g, gm }
  }

  function valid(typ: string, x: number, z: number, rot: number, selfUid: string | null): boolean {
    if (!lotScene) return false
    const [fw, fd] = dims(typ, rot)
    const { W, D } = lotScene
    if (Math.abs(x) + fw / 2 > W / 2 + 0.01 || Math.abs(z) + fd / 2 > D / 2 + 0.01) return false
    for (const p of placements) {
      if (p.uid === selfUid) continue
      const [ow, od] = dims(p.typ, p.rot)
      if (Math.abs(x - p.x) < (fw + ow) / 2 - 0.01 && Math.abs(z - p.z) < (fd + od) / 2 - 0.01) return false
    }
    return true
  }

  function snapPos(typ: string, rot: number, px: number, pz: number): [number, number] {
    const [fw, fd] = dims(typ, rot)
    const { W, D } = lotScene!
    let x = -W / 2 + Math.round((px - fw / 2 + W / 2) / snap) * snap + fw / 2
    let z = -D / 2 + Math.round((pz - fd / 2 + D / 2) / snap) * snap + fd / 2
    const near = Math.abs(px) < W / 2 + 14 && Math.abs(pz) < D / 2 + 14
    if (near) {
      if (fw <= W) x = Math.max(-W / 2 + fw / 2, Math.min(W / 2 - fw / 2, x))
      if (fd <= D) z = Math.max(-D / 2 + fd / 2, Math.min(D / 2 - fd / 2, z))
    }
    return [x, z]
  }

  function addRoot(p: Placement): void {
    const f = F[p.typ]
    if (!f || !placedGroup) return
    const root = new THREE.Group()
    root.userData.uid = p.uid
    const model = makeBuilding(f)
    model.traverse((c) => {
      if (c instanceof THREE.Mesh) c.userData.uid = p.uid
    })
    root.add(model)
    const sel = rectOutline(f.w + 3, f.d + 3, GREEN, 1.1, 1)
    sel.visible = false
    root.add(sel)
    const warn = rectOutline(f.w + 6, f.d + 6, INVALID, 1.4, 0.95)
    warn.visible = false
    root.add(warn)
    root.position.set(p.x, 0, p.z)
    root.rotation.y = (-p.rot * Math.PI) / 2
    placedGroup.add(root)
    placed.set(p.uid, { p, root, sel, warn, model })
  }
  function refreshMarks(): void {
    for (const [uid, o] of placed) {
      o.sel.visible = uid === selUid
      o.warn.visible = warnSet.has(uid)
    }
  }
  function rebuildPlaced(): void {
    if (!placedGroup) return
    for (const { root } of placed.values()) placedGroup.remove(root)
    placed.clear()
    placements.forEach(addRoot)
    refreshMarks()
  }
  const emit = () => opts.onChange?.(placements.map((p) => ({ ...p })))
  const select = (uid: string | null) => {
    selUid = uid
    refreshMarks()
    opts.onSelect?.(uid)
  }

  // ---------- camera ----------
  const controls = new OrbitControls(camera, canvas)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.maxPolarAngle = 1.32
  // Idle showcase: the city turns slowly until the user first touches the map.
  controls.autoRotate = true
  controls.autoRotateSpeed = 1.6
  const stopSpin = () => (controls.autoRotate = false)
  controls.addEventListener('start', stopSpin)
  interface Tween { t0: number; dur: number; fp: THREE.Vector3; ft: THREE.Vector3; tp: THREE.Vector3; tt: THREE.Vector3; res: () => void }
  let tween: Tween | null = null
  const flyTo = (pos: number[], target: number[], dur = 900) =>
    new Promise<void>((res) => {
      tween = { t0: performance.now(), dur, fp: camera.position.clone(), ft: controls.target.clone(), tp: new THREE.Vector3(...pos), tt: new THREE.Vector3(...target), res }
    })
  const cityView = (): [number[], number[]] => [[420, 620, 760], [0, 0, 30]]
  const introView = (): [number[], number[]] => [[560, 210, 500], [0, 20, 30]]
  const lotView = (): [number[], number[]] => {
    const m = Math.max(lotScene!.W, lotScene!.D)
    return [[m * 0.85 + 90, m * 0.8 + 110, lotScene!.D / 2 + m + 130], [0, 0, 6]]
  }
  let mode: 'city' | 'lot' = 'city'
  let scene: THREE.Scene = city
  const setCityLimits = () => {
    controls.minDistance = 45
    controls.maxDistance = 1700
  }
  const setLotLimits = () => {
    controls.minDistance = 40
    controls.maxDistance = 760
  }
  camera.position.set(...(cityView()[0] as [number, number, number]))
  controls.target.set(...(cityView()[1] as [number, number, number]))
  setCityLimits()
  // ---------- pointer ----------
  function setNdc(cx: number, cy: number): DOMRect {
    const r = canvas.getBoundingClientRect()
    ndc.set(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1)
    return r
  }
  function groundAt(cx: number, cy: number): THREE.Vector3 | null {
    const r = canvas.getBoundingClientRect()
    if (cx < r.left || cx > r.right || cy < r.top || cy > r.bottom) return null
    setNdc(cx, cy)
    ray.setFromCamera(ndc, camera)
    const v = new THREE.Vector3()
    return ray.ray.intersectPlane(ground, v) ? v : null
  }
  function pick(cx: number, cy: number, objs: THREE.Object3D[]) {
    setNdc(cx, cy)
    ray.setFromCamera(ndc, camera)
    return ray.intersectObjects(objs, true)[0] ?? null
  }
  const v3 = new THREE.Vector3()
  /** Nearest visible parcel dot within `px` screen pixels (no raycast over 22k instances). */
  function nearestParcel(cx: number, cy: number, px = 9): string | null {
    const r = canvas.getBoundingClientRect()
    let best: string | null = null
    let bd = px * px
    for (let i = 0; i < parcels.length; i++) {
      if (!dotVisible[i]) continue
      const [x, z] = parcelXZ[i]
      v3.set(x, parcelY[i] + 0.8, z).project(camera)
      if (v3.z > 1) continue
      const sx = r.left + (v3.x * 0.5 + 0.5) * r.width
      const sy = r.top + (-v3.y * 0.5 + 0.5) * r.height
      const d = (sx - cx) ** 2 + (sy - cy) ** 2
      if (d < bd) {
        bd = d
        best = parcels[i].id
      }
    }
    return best
  }
  const pinHits = () => [...pins.values()].map((p) => p.hit)
  /** Vacant lot whose outline contains the terrain point under the cursor. */
  function lotUnder(cx: number, cy: number): string | null {
    if (!lots || !outlineMode) return null
    const g = pick(cx, cy, groundMeshes)
    return g ? lots.at(g.point.x, g.point.z) : null
  }

  let drag: Drag | null = null
  function startGhost(typ: string, rot: number, uid: string | null): void {
    if (!lotScene) return
    const { g, gm } = ghostOf(typ)
    g.visible = false
    lotScene.scene.add(g)
    drag = { typ, rot, uid, ghost: g, gm, ok: false, x: 0, z: 0, ox: 0, oz: 0, pending: false }
    controls.enabled = false
  }
  function paintGhost(d: Drag): void {
    d.gm.color.set(d.ok ? VALID : INVALID)
    canvas.style.cursor = d.ok ? 'grabbing' : 'not-allowed'
  }
  function updateGhost(cx: number, cy: number): void {
    if (!drag) return
    const g = groundAt(cx, cy)
    if (!g) {
      drag.ghost.visible = false
      drag.ok = false
      return
    }
    const [x, z] = snapPos(drag.typ, drag.rot, g.x - drag.ox, g.z - drag.oz)
    drag.x = x
    drag.z = z
    drag.ok = valid(drag.typ, x, z, drag.rot, drag.uid)
    drag.ghost.visible = true
    drag.ghost.position.set(x, 0, z)
    drag.ghost.rotation.y = (-drag.rot * Math.PI) / 2
    paintGhost(drag)
  }
  function endGhost(commit: boolean): void {
    if (!drag) return
    const d = drag
    drag = null
    lotScene?.scene.remove(d.ghost)
    controls.enabled = true
    canvas.style.cursor = ''
    if (d.uid) {
      const o = placed.get(d.uid)
      if (o) o.model.visible = true
    }
    if (!commit || !d.ok || !d.ghost.visible) return
    if (d.uid) {
      const p = placements.find((q) => q.uid === d.uid)
      if (p && (p.x !== d.x || p.z !== d.z || p.rot !== d.rot)) {
        Object.assign(p, { x: d.x, z: d.z, rot: d.rot })
        rebuildPlaced()
        emit()
      }
    } else {
      const p: Placement = { uid: 'b' + Date.now().toString(36) + Math.floor(Math.random() * 1e4), typ: d.typ, x: d.x, z: d.z, rot: d.rot }
      placements.push(p)
      rebuildPlaced()
      select(p.uid)
      emit()
    }
  }

  let down: { x: number; y: number } | null = null
  const onDown = (e: PointerEvent) => {
    down = { x: e.clientX, y: e.clientY }
    stopSpin()
    if (mode !== 'lot' || e.button !== 0 || !showPlan || !placedGroup) return
    const h = pick(e.clientX, e.clientY, placedGroup.children)
    const uid = h?.object.userData.uid as string | undefined
    const p = uid ? placements.find((q) => q.uid === uid) : undefined
    if (uid && p) {
      select(uid)
      startGhost(p.typ, p.rot, uid)
      if (!drag) return
      const g = groundAt(e.clientX, e.clientY)
      const dd = drag as Drag
      dd.ox = g ? g.x - p.x : 0
      dd.oz = g ? g.z - p.z : 0
      dd.x = p.x
      dd.z = p.z
      dd.ok = true
      dd.pending = true
      canvas.setPointerCapture(e.pointerId)
    }
  }
  const onMove = (e: PointerEvent) => {
    if (drag && drag.uid) {
      if (drag.pending && down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 4) return
      if (drag.pending) {
        drag.pending = false
        const o = placed.get(drag.uid)
        if (o) o.model.visible = false
      }
      updateGhost(e.clientX, e.clientY)
      return
    }
    if (drag) return
    if (mode === 'city') canvas.style.cursor = pick(e.clientX, e.clientY, pinHits()) ? 'pointer' : ''
    else if (showPlan && placedGroup) canvas.style.cursor = pick(e.clientX, e.clientY, placedGroup.children) ? 'grab' : ''
  }
  const onUp = (e: PointerEvent) => {
    const still = down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5
    if (drag && drag.uid) {
      endGhost(!drag.pending)
      return
    }
    if (!still) return
    if (mode === 'city') {
      const h = pick(e.clientX, e.clientY, pinHits())
      const id = (h?.object.userData.lotId as string | undefined) ?? lotUnder(e.clientX, e.clientY) ?? nearestParcel(e.clientX, e.clientY)
      if (id) opts.onSelectLot?.(id)
    } else if (!drag) select(null)
  }
  canvas.addEventListener('pointerdown', onDown, { capture: true })
  canvas.addEventListener('pointermove', onMove)
  canvas.addEventListener('pointerup', onUp)
  const onWinMove = (e: PointerEvent) => {
    if (drag && !drag.uid) updateGhost(e.clientX, e.clientY)
  }
  const onWinUp = () => {
    if (drag && !drag.uid) endGhost(true)
  }
  const onKey = (e: KeyboardEvent) => {
    const tag = (e.target as HTMLElement | null)?.tagName ?? ''
    if (/INPUT|SELECT|TEXTAREA/.test(tag)) return
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault()
      ;(e.shiftKey ? opts.onRedo : opts.onUndo)?.()
      return
    }
    if (mode !== 'lot') return
    if (e.key === 'r' || e.key === 'R') {
      if (drag) {
        drag.rot = (drag.rot + 1) % 4
        if (drag.ghost.visible) {
          drag.ghost.rotation.y = (-drag.rot * Math.PI) / 2
          const [x, z] = snapPos(drag.typ, drag.rot, drag.x, drag.z)
          drag.x = x
          drag.z = z
          drag.ghost.position.set(x, 0, z)
          drag.ok = valid(drag.typ, x, z, drag.rot, drag.uid)
          paintGhost(drag)
        }
      } else api.rotateSelected()
    }
    if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault()
      api.deleteSelected()
    }
    if (e.key === 'Escape') {
      if (drag) endGhost(false)
      else select(null)
    }
  }
  window.addEventListener('pointermove', onWinMove)
  window.addEventListener('pointerup', onWinUp)
  window.addEventListener('keydown', onKey)

  // ---------- loop ----------
  const ro = new ResizeObserver(() => {
    const w = container.clientWidth
    const h = container.clientHeight
    if (!w || !h) return
    renderer.setSize(w, h, false)
    setLineResolution(w, h)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    // Resizing clears the canvas, and observers run after this frame's render but
    // before paint, so redraw now or animated layout (the intro's viewport slide,
    // panels opening) paints a blank canvas every frame.
    renderer.render(scene, camera)
  })
  ro.observe(container)
  let raf = 0
  let selLot: string | null = null
  function frame(now: number): void {
    raf = requestAnimationFrame(frame)
    if (tween) {
      const t = tween
      const k = Math.min(1, (now - t.t0) / t.dur)
      const e = ease(k)
      camera.position.lerpVectors(t.fp, t.tp, e)
      controls.target.lerpVectors(t.ft, t.tt, e)
      if (k >= 1) {
        tween = null
        t.res()
      }
    }
    if (mode === 'city' && !tween) {
      controls.target.x = Math.max(-HALF, Math.min(HALF, controls.target.x))
      controls.target.z = Math.max(-HALF, Math.min(HALF, controls.target.z))
    }
    controls.update()
    // Depth precision scales with the near plane, so a fixed near of 1 wasted it
    // when zoomed out and rivers dropped out (worst on 16-bit depth buffers). Keep
    // it a small fraction of the orbit distance; the polar-angle limit keeps the
    // camera above what it orbits, so nothing sits that close to the lens.
    const near = THREE.MathUtils.clamp(camera.position.distanceTo(controls.target) * NEAR_PER_DISTANCE, 1, NEAR_MAX)
    if (Math.abs(near - camera.near) > camera.near * 0.02) {
      camera.near = near
      camera.updateProjectionMatrix()
    }
    if (mode === 'city') {
      const w = container.clientWidth
      const h = container.clientHeight
      const dist = camera.position.distanceTo(controls.target)
      streets?.update(dist)
      if (lots) {
        const on = dist < (opts.scene.basemap?.lots.outline_distance ?? 0)
        lots.obj.visible = on
        if (on !== outlineMode) {
          outlineMode = on
          writeDots()
        }
      }
      const taken: Rect[] = []
      for (const [id, p] of pins) {
        p.ring.rotation.z = now / 900
        const s = id === selLot ? 1.25 + Math.sin(now / 250) * 0.1 : 1
        p.ring.scale.set(s, s, s)
        v3.set(p.g.position.x, p.g.position.y + 78, p.g.position.z).project(camera)
        const on = v3.z < 1
        p.el.style.display = on ? 'block' : 'none'
        if (!on) continue
        const sx = (v3.x * 0.5 + 0.5) * w
        const sy = (-v3.y * 0.5 + 0.5) * h
        p.el.style.transform = `translate(${sx}px, ${sy}px) translate(-50%,-100%)`
        if (!p.w) {
          p.w = p.el.offsetWidth
          p.h = p.el.offsetHeight
        }
        taken.push({ x0: sx - p.w / 2, y0: sy - p.h, x1: sx + p.w / 2, y1: sy })
      }
      hoods?.update(camera, w, h, taken)
    } else if (warnSet.size) {
      const o = 0.45 + 0.5 * (0.5 + 0.5 * Math.sin(now / 220))
      for (const uid of warnSet) {
        const x = placed.get(uid)
        const m = (x?.warn.children[0] as THREE.Mesh | undefined)?.material as THREE.MeshBasicMaterial | undefined
        if (m) m.opacity = o
      }
    }
    renderer.render(scene, camera)
  }
  raf = requestAnimationFrame(frame)

  const api: Engine = {
    async goLot(lot, list = []) {
      stopSpin()
      selLot = lot.id
      if (mode === 'city') {
        const [x, z] = toXZ(lot.lon, lot.lat)
        const y = heightAt(x, z)
        await flyTo([x + 70, y + 150, z + 170], [x, y, z], 750)
      }
      fade.style.opacity = '1'
      await wait(270)
      if (lotScene) lotScene.scene.traverse((o) => (o as THREE.Mesh).geometry?.dispose?.())
      placed.clear()
      lotScene = buildLot(lot)
      drawEnvelope()
      placements = list.map((p) => ({ ...p }))
      selUid = null
      rebuildPlaced()
      if (placedGroup) placedGroup.visible = showPlan
      mode = 'lot'
      scene = lotScene.scene
      labels.style.display = 'none'
      setLotLimits()
      const [p, t] = lotView()
      camera.position.set(p[0] * 1.8, p[1] * 1.9, p[2] * 1.6)
      controls.target.set(t[0], t[1], t[2])
      fade.style.opacity = '0'
      await flyTo(p, t, 1000)
    },
    async goCity() {
      if (mode === 'city') return
      if (drag) endGhost(false)
      fade.style.opacity = '1'
      await wait(270)
      mode = 'city'
      scene = city
      labels.style.display = 'block'
      setCityLimits()
      const lot = parcels.find((p) => p.id === selLot)
      if (lot) {
        const [x, z] = toXZ(lot.lon, lot.lat)
        camera.position.set(x + 70, 150, z + 170)
        controls.target.set(x, 0, z)
      }
      fade.style.opacity = '0'
      await flyTo(...cityView(), 1000)
    },
    setPlacements(list) {
      placements = list.map((p) => ({ ...p }))
      if (selUid && !placements.find((p) => p.uid === selUid)) select(null)
      rebuildPlaced()
    },
    setWarnings(uids) {
      const k = [...uids].sort().join(',')
      if (k === [...warnSet].sort().join(',')) return
      warnSet = new Set(uids)
      refreshMarks()
    },
    setEnvelope(env) {
      envelope = env
      drawEnvelope()
    },
    setShowPlan(v) {
      showPlan = v
      if (placedGroup) placedGroup.visible = v
      if (!v) select(null)
    },
    setVisibleParcels(ids) {
      parcels.forEach((p, i) => (dotVisible[i] = !ids || ids.has(p.id) ? 1 : 0))
      writeDots()
      pendingVisible = ids
      lots?.setVisible(ids)
    },
    setPins(list) {
      pinList = list
      renderPins()
    },
    frameLots(list) {
      if (mode !== 'city' || !list.length) return
      const xz = list.map((l) => toXZ(l.lon, l.lat))
      const xs = xz.map((p) => p[0])
      const zs = xz.map((p) => p[1])
      const cx = (Math.min(...xs) + Math.max(...xs)) / 2
      const cz = (Math.min(...zs) + Math.max(...zs)) / 2
      // Far enough to see the spread, never so close that one lot fills the screen.
      const r = Math.min(Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs)) * 1.2, 1000)
      const d = Math.max(r, 180)
      void flyTo([cx + d * 0.35, d * 0.8, cz + d * 0.8], [cx, 0, cz], 1100)
    },
    beginDrag(typ, e) {
      if (mode !== 'lot' || !showPlan) return
      e?.preventDefault?.()
      startGhost(typ, 0, null)
      if (e) updateGhost(e.clientX, e.clientY)
    },
    rotateSelected() {
      const p = placements.find((q) => q.uid === selUid)
      if (!p) return
      for (let k = 1; k <= 3; k++) {
        const rot = (p.rot + k) % 4
        const [x, z] = snapPos(p.typ, rot, p.x, p.z)
        if (valid(p.typ, x, z, rot, p.uid)) {
          Object.assign(p, { x, z, rot })
          rebuildPlaced()
          emit()
          return
        }
      }
    },
    deleteSelected() {
      if (!selUid) return
      placements = placements.filter((p) => p.uid !== selUid)
      select(null)
      rebuildPlaced()
      emit()
    },
    clearSelection() {
      select(null)
    },
    async enter() {
      controls.autoRotateSpeed = 0.5
      await flyTo(...cityView(), 2200)
    },
    resetView() {
      void flyTo(...(mode === 'city' ? cityView() : lotView()), 800)
    },
    dispose() {
      cancelAnimationFrame(raf)
      ro.disconnect()
      window.removeEventListener('pointermove', onWinMove)
      window.removeEventListener('pointerup', onWinUp)
      window.removeEventListener('keydown', onKey)
      controls.dispose()
      hoods?.dispose()
      renderer.dispose()
      container.innerHTML = ''
    },
  }
  return api
}
