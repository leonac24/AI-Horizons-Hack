// The comparison pool for one lot: every typology's pure option (from
// /api/analysis) plus the user's own plan (from /api/analysis/{id}/plan).
// Scoring stays in lib/scoring.ts; nothing here weighs anything.
import type { BuildingForm } from '../three/typologyMeshes'
import type { Placement } from '../three/engine'
import type { Analysis, CarbonSeries, Config, HouseholdCheck, LotShape, Metric, PlanResult, RevenueSeries, ZoningResult } from '../types'
import { rankOrder, rankingFlip, scores, smaa, type Flip } from './scoring'

export const PLAN_ID = '__plan__'

export interface Option {
  id: string // typology id, or PLAN_ID
  label: string
  short: string
  color: string
  units: number
  metrics: Record<string, Metric>
  zoning: ZoningResult
  households: HouseholdCheck[]
  carbon: CarbonSeries
  revenue: RevenueSeries
  eligible: boolean
  reason: string | null
  fits: boolean
  isPlan: boolean
  placements?: Placement[] // what "Place" puts on the lot
  zoningByType?: Record<string, ZoningResult> // plan only
  notes: string[]
}

export function buildingForms(config: Config): Record<string, BuildingForm> {
  return Object.fromEntries(
    config.typologies.map((t) => [
      t.id,
      { w: t.building.footprint_ft[0], d: t.building.footprint_ft[1], stories: t.stories, massing: t.building.massing, body: t.building.body, roof: t.building.roof },
    ]),
  )
}

/** The pure option's buildings in a row along the front of the lot (street is +z). */
export function purePlacements(config: Config, typId: string, buildings: number, shape: LotShape): Placement[] {
  const t = config.typologies.find((x) => x.id === typId)
  if (!t) return []
  const [w, d] = t.building.footprint_ft
  const D = shape.depth_ft
  const z = D / 2 - 6 - d / 2 > -D / 2 + d / 2 ? D / 2 - 6 - d / 2 : D / 2 - d / 2
  const x0 = -(buildings * w) / 2 + w / 2
  return Array.from({ length: buildings }, (_, i) => ({ uid: `o_${typId}_${i}`, typ: typId, x: x0 + i * w, z, rot: 0 }))
}

export function countsOf(list: Placement[]): Record<string, number> {
  const c: Record<string, number> = {}
  for (const p of list) c[p.typ] = (c[p.typ] ?? 0) + 1
  return c
}

export function buildPool(config: Config, analysis: Analysis, plan: PlanResult | null): Option[] {
  const pure: Option[] = analysis.scenarios.map((s) => {
    const t = config.typologies.find((x) => x.id === s.typology_id)!
    return {
      id: t.id, label: t.label, short: t.short_label, color: t.color, units: s.units, metrics: s.metrics,
      zoning: s.zoning, households: s.households, carbon: s.carbon, revenue: s.revenue, eligible: s.eligible, reason: s.ineligible_reason,
      fits: s.form_fits, isPlan: false, placements: purePlacements(config, t.id, s.buildings, analysis.lot_shape),
      notes: s.notes,
    }
  })
  if (!plan || plan.units === 0) return pure
  const own: Option = {
    id: PLAN_ID, label: 'Your plan', short: 'Your plan', color: '#2fd06b', units: plan.units, metrics: plan.metrics,
    zoning: plan.zoning, households: plan.households, carbon: plan.carbon, revenue: plan.revenue, eligible: plan.eligible,
    reason: plan.ineligible_reason, fits: true, isPlan: true, zoningByType: plan.zoning_by_typology, notes: plan.notes,
  }
  return [...pure, own]
}

export interface Ranking {
  ranked: Option[] // best first
  acc: Record<string, number[]>
  flip: (Flip & { winnerId: string; challengerId: string }) | null
  score: Record<string, number>
  notFitting: Option[]
  excluded: Option[]
}

/** Only options that fit the lot and pass hard requirements are scored. */
export function rank(config: Config, pool: Option[], weights: Record<string, number>): Ranking {
  const rankable = pool.filter((o) => o.fits && o.eligible)
  const crit = config.criteria
  const pick = (k: 'value' | 'low' | 'high') => rankable.map((o) => crit.map((c) => o.metrics[c.metric_id][k]))
  const hib = crit.map((c) => c.direction === 'higher_is_better')
  const w = crit.map((c) => weights[c.id] ?? 0)
  const s = rankable.length ? scores(pick('value'), hib, w) : []
  const order = rankOrder(s)
  const accM = rankable.length
    ? smaa({ value: pick('value'), low: pick('low'), high: pick('high'), higherIsBetter: hib, samples: config.app.smaa.samples, seed: config.app.smaa.seed, center: w, concentration: config.app.smaa.profile_concentration })
    : []
  const f = rankable.length > 1 ? rankingFlip(pick('value'), hib, w) : null
  return {
    ranked: order.map((i) => rankable[i]),
    acc: Object.fromEntries(rankable.map((o, i) => [o.id, accM[i]])),
    flip: f ? { ...f, winnerId: rankable[f.winner].id, challengerId: rankable[f.challenger].id } : null,
    score: Object.fromEntries(rankable.map((o, i) => [o.id, s[i]])),
    notFitting: pool.filter((o) => !o.fits),
    excluded: pool.filter((o) => o.fits && !o.eligible),
  }
}

/** Up-front subsidy per home to reach a target income tier — the same formula as
 * core/engine.py::work_backwards, applied to a plan's monthly-cost metric. */
export function subsidyPerHome(config: Config, monthly: Metric, amiPct: number): number {
  const a = config.assumptions
  const affordable = (a.ami_4person.value * amiPct) / 100 * a.housing_cost_share.value / 12
  return Math.max(0, monthly.value - affordable) * 12 / a.annual_capital_cost_share.value
}
