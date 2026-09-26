// Values layer, in the browser for live updates. Mirror of core/scoring.py — keep in sync.
// Evidence (metric value/low/high) comes in; weights come from the user; they meet only here.

export type Matrix = number[][] // [scenario][criterion]

export function normalize(values: Matrix, higherIsBetter: boolean[]): Matrix {
  const m = values.length
  const k = higherIsBetter.length
  const out: Matrix = values.map(() => new Array<number>(k).fill(0))
  for (let j = 0; j < k; j++) {
    let lo = Infinity
    let hi = -Infinity
    for (let i = 0; i < m; i++) {
      lo = Math.min(lo, values[i][j])
      hi = Math.max(hi, values[i][j])
    }
    const span = hi - lo
    for (let i = 0; i < m; i++) {
      const n = span > 0 ? (values[i][j] - lo) / span : 0.5
      out[i][j] = higherIsBetter[j] ? n : 1 - n
    }
  }
  return out
}

export function normalizeWeights(w: number[]): number[] {
  const s = w.reduce((a, b) => a + b, 0)
  return s > 0 ? w.map((x) => x / s) : w.map(() => 1 / w.length)
}

export function scores(values: Matrix, higherIsBetter: boolean[], weights: number[]): number[] {
  const w = normalizeWeights(weights)
  return normalize(values, higherIsBetter).map((row) => row.reduce((acc, x, j) => acc + x * w[j], 0))
}

export function rankOrder(s: number[]): number[] {
  return s.map((_, i) => i).sort((a, b) => s[b] - s[a] || a - b)
}

// --- seeded randomness ---------------------------------------------------------
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function normal(rand: () => number): number {
  const u = Math.max(rand(), 1e-12)
  const v = rand()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

// Marsaglia–Tsang gamma sampler (shape a > 0, scale 1).
function gamma(rand: () => number, a: number): number {
  if (!Number.isFinite(a) || a <= 0) throw new Error(`gamma shape must be > 0, got ${a}`)
  if (a < 1) return gamma(rand, a + 1) * Math.pow(Math.max(rand(), 1e-12), 1 / a)
  const d = a - 1 / 3
  const c = 1 / Math.sqrt(9 * d)
  for (let iter = 0; iter < 10000; iter++) {
    let x: number
    let v: number
    do {
      x = normal(rand)
      v = 1 + c * x
    } while (v <= 0)
    v = v * v * v
    const u = rand()
    if (u < 1 - 0.0331 * x ** 4) return d * v
    if (Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v
  }
  return d // unreachable in practice; keeps a bad input from hanging the page
}

export function dirichlet(rand: () => number, alpha: number[]): number[] {
  const g = alpha.map((a) => gamma(rand, a))
  const s = g.reduce((x, y) => x + y, 0)
  return g.map((x) => x / s)
}

export interface SmaaInput {
  value: Matrix
  low: Matrix
  high: Matrix
  higherIsBetter: boolean[]
  samples: number
  seed: number
  center?: number[] // stakeholder profile to center weights on
  concentration?: number
}

/** Rank-acceptability: acc[i][r] = share of draws where scenario i ranks r (0 = best). */
export function smaa(inp: SmaaInput): Matrix {
  const rand = mulberry32(inp.seed)
  const m = inp.value.length
  const k = inp.higherIsBetter.length
  const conc = inp.concentration ?? 40
  const alpha = inp.center
    ? normalizeWeights(inp.center).map((w) => Math.max(w * conc, 1e-3))
    : new Array<number>(k).fill(1)
  const acc: Matrix = Array.from({ length: m }, () => new Array<number>(m).fill(0))
  const x: Matrix = Array.from({ length: m }, () => new Array<number>(k).fill(0))
  for (let s = 0; s < inp.samples; s++) {
    const w = dirichlet(rand, alpha)
    for (let i = 0; i < m; i++)
      for (let j = 0; j < k; j++) {
        const lo = inp.low[i][j]
        const hi = inp.high[i][j]
        x[i][j] = lo + (hi - lo) * rand()
      }
    const order = rankOrder(scores(x, inp.higherIsBetter, w))
    order.forEach((scenario, rank) => {
      acc[scenario][rank] += 1 / inp.samples
    })
  }
  return acc
}

export interface Flip {
  criterionIndex: number
  from: number
  to: number
  delta: number
  winner: number
  challenger: number
}

/** Smallest single-weight change that lets the runner-up overtake the leader (see core/scoring.py). */
export function rankingFlip(values: Matrix, higherIsBetter: boolean[], weights: number[]): Flip | null {
  const w = normalizeWeights(weights)
  const order = rankOrder(scores(values, higherIsBetter, w))
  if (order.length < 2) return null
  const [a, b] = order
  const N = normalize(values, higherIsBetter)
  const D = N[a].map((x, j) => x - N[b][j])
  const dw = D.reduce((acc, d, j) => acc + d * w[j], 0)
  let best: Flip | null = null
  for (let j = 0; j < w.length; j++) {
    if (1 - w[j] <= 1e-12) continue
    const r = (dw - D[j] * w[j]) / (1 - w[j])
    const denom = r - D[j]
    if (Math.abs(denom) < 1e-12) continue
    const t = r / denom
    if (t < 0 || t > 1) continue
    const delta = t - w[j]
    if (!best || Math.abs(delta) < Math.abs(best.delta))
      best = { criterionIndex: j, from: w[j], to: t, delta, winner: a, challenger: b }
  }
  return best
}
