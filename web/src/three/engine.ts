// three.js engine for the Lotline simulator: a stylized city diorama with every
// vacant parcel, and a lot scene where the user drags buildings onto the parcel.
// Framework-free; React talks to it through the returned API and callbacks.
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { box, house, makeBuilding, mat, mesh, type BuildingForm } from './typologyMeshes'

export interface SceneConfig {
  origin: [number, number]
  scale: [number, number]
  half_extent: number
  rivers: [number, number][][]
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
  snap?: number
  onSelectLot?: (id: string) => void
  onChange?: (list: Placement[]) => void
  onSelect?: (uid: string | null) => void
  onUndo?: () => void
  onRedo?: () => void
}

export interface Engine {
  goLot(lot: LotInput, list?: Placement[]): Promise<void>
  goCity(): Promise<void>
  setPlacements(list: Placement[]): void
  setWarnings(uids: string[]): void
  setShowPlan(v: boolean): void
  setVisibleParcels(ids: Set<string> | null): void
  setPins(pins: PinLot[]): void
  beginDrag(typ: string, e?: PointerLike): void
  rotateSelected(): void
  deleteSelected(): void
  clearSelection(): void
  resetView(): void
  dispose(): void
}

const BG = '#0f1419'
const LIME = '#b6f23e'
const VALID = '#9be07a'
const INVALID = '#ff4a3a'
const DOT_PUBLIC = '#ff6b4a'
const DOT_OTHER = '#5aa9d6'

function rng(seed: number): () => number {
  let s = seed >>> 0
  return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296
}

function ribbon(pts: [number, number][], width: number, y: number, half: number) {
  const curve = new THREE.CatmullRomCurve3(pts.map(([x, z]) => new THREE.Vector3(x, 0, z)))
  const n = 140
  const pos: number[] = []
  const idx: number[] = []
  const cx = (v: number) => Math.max(-half, Math.min(half, v))
  for (let i = 0; i <= n; i++) {
    const t = i / n
    const p = curve.getPoint(t)
    const tg = curve.getTangent(t)
    const l = Math.hypot(tg.x, tg.z) || 1
    const nx = -tg.z / l
    const nz = tg.x / l
    const hw = width / 2
    pos.push(cx(p.x + nx * hw), y, cx(p.z + nz * hw), cx(p.x - nx * hw), y, cx(p.z - nz * hw))
    if (i < n) {
      const a = i * 2
      idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setIndex(idx)
  g.computeVertexNormals()
  return { geo: g, samples: curve.getPoints(200) }
}

function extendToEdge(pts: [number, number][]): [number, number][] {
  const out = pts.slice()
  const a = out[out.length - 2]
  const b = out[out.length - 1]
  const dx = b[0] - a[0]
  const dz = b[1] - a[1]
  const l = Math.hypot(dx, dz) || 1
  out.push([b[0] + (dx / l) * 140, b[1] + (dz / l) * 140])
  return out
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
  const tr = mesh(new THREE.CylinderGeometry(0.8, 1, 6, 5), '#6b4b33')
  tr.position.y = 3
  g.add(tr)
  const c = mesh(new THREE.IcosahedronGeometry(5 + r() * 3, 0), r() > 0.5 ? '#6d7b4f' : '#7f8c58')
  c.position.y = h * 0.6 + 3
  c.scale.y = 1.25
  g.add(c)
  return g
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

function lightRig(scene: THREE.Scene, x: number, y: number, z: number, ext: number): void {
  scene.add(new THREE.HemisphereLight('#fff4e0', '#3a3228', 1.15))
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
  Object.assign(renderer.domElement.style, {
    position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block', touchAction: 'none',
  })
  container.appendChild(renderer.domElement)
  const labels = document.createElement('div')
  Object.assign(labels.style, { position: 'absolute', inset: '0', pointerEvents: 'none', overflow: 'hidden' })
  container.appendChild(labels)
  const fade = document.createElement('div')
  Object.assign(fade.style, {
    position: 'absolute', inset: '0', background: BG, opacity: '0', pointerEvents: 'none', transition: 'opacity 260ms ease',
  })
  container.appendChild(fade)

  const camera = new THREE.PerspectiveCamera(38, 1, 1, 8000)
  const canvas = renderer.domElement
  const ray = new THREE.Raycaster()
  const ndc = new THREE.Vector2()
  const ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)

  // ---------- city ----------
  const city = new THREE.Scene()
  city.background = new THREE.Color(BG)
  city.fog = new THREE.Fog(BG, 1500, 3200)
  lightRig(city, -420, 720, 320, 700)
  const edge = mat('#27313a')
  const slab = new THREE.Mesh(new THREE.BoxGeometry(HALF * 2, 28, HALF * 2), [edge, edge, mat('#cfd3c8'), edge, edge, edge])
  slab.position.y = -14
  slab.receiveShadow = true
  city.add(slab)
  const riverSamples: THREE.Vector3[] = []
  for (const r of opts.scene.rivers) {
    const rb = ribbon(extendToEdge(r.map(([lo, la]) => toXZ(lo, la))), 30, 0.4, HALF)
    const m = new THREE.Mesh(rb.geo, new THREE.MeshStandardMaterial({ color: '#3d7ea6', roughness: 0.35, metalness: 0.1, side: THREE.DoubleSide }))
    m.receiveShadow = true
    city.add(m)
    riverSamples.push(...rb.samples)
  }
  const riverDist = (x: number, z: number) => {
    let m = 1e9
    for (const p of riverSamples) m = Math.min(m, Math.hypot(p.x - x, p.z - z))
    return m
  }
  // Decorative hills and blocks — a stylized city, not data.
  const R = rng(20260926)
  const hills: [number, number, number][] = []
  for (let i = 0; i < 70 && hills.length < 34; i++) {
    const x = (R() * 2 - 1) * (HALF - 80)
    const z = (R() * 2 - 1) * (HALF - 80)
    const r = 34 + R() * 60
    if (riverDist(x, z) < r + 24 || Math.hypot(x, z) < 110) continue
    const h = mesh(new THREE.IcosahedronGeometry(r, 1), R() > 0.5 ? '#8a9663' : '#77844f')
    h.scale.y = 0.3
    h.position.set(x, -2, z)
    city.add(h)
    hills.push([x, z, r])
  }
  const cells: [number, number][] = []
  for (let x = -HALF + 30; x <= HALF - 30; x += 22)
    for (let z = -HALF + 30; z <= HALF - 30; z += 22) {
      if (R() < 0.32 || riverDist(x, z) < 26) continue
      if (hills.some(([hx, hz, hr]) => Math.hypot(hx - x, hz - z) < hr * 0.85)) continue
      cells.push([x, z])
    }
  const blocks = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), mat('#ffffff'), cells.length)
  blocks.castShadow = true
  blocks.receiveShadow = true
  const bcol = ['#efe6d3', '#e3d5bb', '#d8c3a5', '#c98f6f', '#b9b2a4', '#a4553a']
  const M4 = new THREE.Matrix4()
  const C = new THREE.Color()
  const Q = new THREE.Quaternion()
  cells.forEach(([x, z], i) => {
    const core = Math.hypot(x, z) < 80 // taller towers near the origin (Downtown)
    const h = core ? 26 + R() * 70 : 3 + R() * 8
    const s = core ? 15 : 10 + R() * 6
    M4.compose(new THREE.Vector3(x + (R() - 0.5) * 4, 0, z + (R() - 0.5) * 4), Q, new THREE.Vector3(s, h, s))
    blocks.setMatrixAt(i, M4)
    blocks.setColorAt(i, C.set(bcol[Math.floor(R() * bcol.length)]))
  })
  city.add(blocks)

  // Real vacant parcels as instanced dots.
  const parcels = opts.parcels
  const parcelXZ = parcels.map((p) => toXZ(p.lon, p.lat))
  const dots = new THREE.InstancedMesh(new THREE.CylinderGeometry(2.4, 2.4, 1, 8), new THREE.MeshBasicMaterial({ color: '#fff' }), Math.max(1, parcels.length))
  const dotVisible = new Uint8Array(parcels.length).fill(1)
  const writeDots = () => {
    parcels.forEach((_p, i) => {
      const [x, z] = parcelXZ[i]
      const s = dotVisible[i] ? 1 : 0
      M4.compose(new THREE.Vector3(x, 0.8, z), Q, new THREE.Vector3(s, s, s))
      dots.setMatrixAt(i, M4)
    })
    dots.instanceMatrix.needsUpdate = true
  }
  parcels.forEach((p, i) => dots.setColorAt(i, C.set(p.public ? DOT_PUBLIC : DOT_OTHER)))
  writeDots()
  city.add(dots)

  // Pins (suggested lots and search hits) with DOM labels.
  interface Pin { g: THREE.Group; ring: THREE.Mesh; hit: THREE.Mesh; el: HTMLDivElement; lot: PinLot }
  const pins = new Map<string, Pin>()
  const pinGeo = {
    pad: new THREE.CylinderGeometry(10, 10, 3, 24),
    beam: new THREE.CylinderGeometry(1.2, 1.2, 70, 8),
    ring: new THREE.TorusGeometry(15, 0.9, 6, 40),
    hit: new THREE.CylinderGeometry(20, 20, 80, 8),
  }
  const pinMats = {
    pad: new THREE.MeshStandardMaterial({ color: LIME, emissive: LIME, emissiveIntensity: 0.35 }),
    beam: new THREE.MeshBasicMaterial({ color: LIME, transparent: true, opacity: 0.55 }),
    ring: new THREE.MeshBasicMaterial({ color: LIME }),
    hit: new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }),
  }
  function addPin(lot: PinLot): void {
    const [x, z] = toXZ(lot.lon, lot.lat)
    const g = new THREE.Group()
    g.position.set(x, 0, z)
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
    pins.set(lot.id, { g, ring, hit, el, lot })
  }
  function clearPins(): void {
    for (const p of pins.values()) {
      city.remove(p.g)
      p.el.remove()
    }
    pins.clear()
  }

  // ---------- lot ----------
  let lotScene: { scene: THREE.Scene; W: number; D: number } | null = null
  let placedGroup: THREE.Group | null = null
  const placed = new Map<string, PlacedObj>()
  let placements: Placement[] = []
  let selUid: string | null = null
  let warnSet = new Set<string>()
  let showPlan = true
  const dims = (typ: string, rot: number): [number, number] => (rot % 2 ? [F[typ].d, F[typ].w] : [F[typ].w, F[typ].d])

  function buildLot(lot: LotInput) {
    const s = new THREE.Scene()
    s.background = new THREE.Color(BG)
    const W = lot.frontage
    const D = lot.depth
    const S = Math.max(420, D + 280, W + 320)
    const r = rng(Math.round(W * 131 + D * 17))
    lightRig(s, -170, 320, 200, S / 2 + 40)
    const sl = new THREE.Mesh(new THREE.BoxGeometry(S, 18, S), [edge, edge, mat('#c9cec2'), edge, edge, edge])
    sl.position.y = -9
    sl.receiveShadow = true
    s.add(sl)
    const walkZ = D / 2 + 6
    const roadZ = D / 2 + 12 + 18
    const farWalk = D / 2 + 48 + 5
    const road = box(S, 0.4, 36, '#3a3530')
    road.position.set(0, 0.2, roadZ)
    road.castShadow = false
    s.add(road)
    for (let x = -S / 2 + 10; x < S / 2; x += 22) {
      const d = box(9, 0.1, 1, '#d8c27a')
      d.castShadow = false
      d.position.set(x, 0.45, roadZ)
      s.add(d)
    }
    for (const z of [walkZ, farWalk]) {
      const w = box(S, 0.7, 10, '#ddd3bf')
      w.castShadow = false
      w.position.set(0, 0.35, z)
      s.add(w)
    }
    const pad = box(W, 0.6, D, '#a9b47e')
    pad.castShadow = false
    pad.position.y = 0.3
    s.add(pad)
    const gp: number[] = []
    for (let x = -W / 2 + 10; x < W / 2; x += 10) gp.push(x, 0.65, -D / 2, x, 0.65, D / 2)
    for (let z = -D / 2 + 10; z < D / 2; z += 10) gp.push(-W / 2, 0.65, z, W / 2, 0.65, z)
    const gg = new THREE.BufferGeometry()
    gg.setAttribute('position', new THREE.Float32BufferAttribute(gp, 3))
    s.add(new THREE.LineSegments(gg, new THREE.LineBasicMaterial({ color: '#7d8a5c', transparent: true, opacity: 0.7 })))
    s.add(rectOutline(W, D, LIME, 0.8, 0.75))
    // Illustrative neighbors — procedural, not the real block.
    const bodies = ['#e6d8bd', '#dcc3a4', '#c98f6f', '#efe2c6', '#b9b2a4', '#d8c3a5']
    const roofs = ['#6b4b33', '#3b2a24', '#7a3b2e', '#4f4a44']
    const row = (from: number, dir: number, zFront: number, facing: number) => {
      let x = from
      while (Math.abs(x) < S / 2 - 16) {
        const w = 18 + Math.floor(r() * 8)
        const d = 34 + Math.floor(r() * 10)
        const g = new THREE.Group()
        house(g, { w, d, floors: r() > 0.4 ? 2 : 3, body: bodies[Math.floor(r() * bodies.length)], roof: roofs[Math.floor(r() * roofs.length)], flat: r() > 0.6 })
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
    row(-S / 2 + 20, 1, farWalk + 8, -1)
    for (let x = -S / 2 + 20; x < S / 2 - 10; x += 26 + r() * 20) {
      if (Math.abs(x) < W / 2 + 6) continue
      const t = tree(r)
      t.position.set(x, 0, walkZ + 3.5)
      s.add(t)
    }
    for (let i = 0; i < 18; i++) {
      const t = tree(r)
      t.position.set((r() * 2 - 1) * (S / 2 - 20), 0, -D / 2 - 30 - r() * Math.max(10, S / 2 - D / 2 - 40))
      s.add(t)
    }
    if (lot.hill) {
      const h = mesh(new THREE.IcosahedronGeometry(S * 0.42, 1), '#77844f')
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
    const sel = rectOutline(f.w + 3, f.d + 3, LIME, 1.1, 1)
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
  interface Tween { t0: number; dur: number; fp: THREE.Vector3; ft: THREE.Vector3; tp: THREE.Vector3; tt: THREE.Vector3; res: () => void }
  let tween: Tween | null = null
  const flyTo = (pos: number[], target: number[], dur = 900) =>
    new Promise<void>((res) => {
      tween = { t0: performance.now(), dur, fp: camera.position.clone(), ft: controls.target.clone(), tp: new THREE.Vector3(...pos), tt: new THREE.Vector3(...target), res }
    })
  const cityView = (): [number[], number[]] => [[420, 620, 760], [0, 0, 30]]
  const lotView = (): [number[], number[]] => {
    const m = Math.max(lotScene!.W, lotScene!.D)
    return [[m * 0.85 + 90, m * 0.8 + 110, lotScene!.D / 2 + m + 130], [0, 0, 6]]
  }
  let mode: 'city' | 'lot' = 'city'
  let scene: THREE.Scene = city
  const setCityLimits = () => {
    controls.minDistance = 160
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
      v3.set(x, 0.8, z).project(camera)
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
      const id = (h?.object.userData.lotId as string | undefined) ?? nearestParcel(e.clientX, e.clientY)
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
    camera.aspect = w / h
    camera.updateProjectionMatrix()
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
    controls.update()
    if (mode === 'city') {
      const w = container.clientWidth
      const h = container.clientHeight
      for (const [id, p] of pins) {
        p.ring.rotation.z = now / 900
        const s = id === selLot ? 1.25 + Math.sin(now / 250) * 0.1 : 1
        p.ring.scale.set(s, s, s)
        v3.set(p.g.position.x, 78, p.g.position.z).project(camera)
        const on = v3.z < 1
        p.el.style.display = on ? 'block' : 'none'
        if (on) p.el.style.transform = `translate(${(v3.x * 0.5 + 0.5) * w}px, ${(-v3.y * 0.5 + 0.5) * h}px) translate(-50%,-100%)`
      }
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
      selLot = lot.id
      if (mode === 'city') {
        const [x, z] = toXZ(lot.lon, lot.lat)
        await flyTo([x + 70, 150, z + 170], [x, 0, z], 750)
      }
      fade.style.opacity = '1'
      await wait(270)
      if (lotScene) lotScene.scene.traverse((o) => (o as THREE.Mesh).geometry?.dispose?.())
      placed.clear()
      lotScene = buildLot(lot)
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
    setShowPlan(v) {
      showPlan = v
      if (placedGroup) placedGroup.visible = v
      if (!v) select(null)
    },
    setVisibleParcels(ids) {
      parcels.forEach((p, i) => (dotVisible[i] = !ids || ids.has(p.id) ? 1 : 0))
      writeDots()
    },
    setPins(list) {
      clearPins()
      list.forEach(addPin)
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
      renderer.dispose()
      container.innerHTML = ''
    },
  }
  return api
}
