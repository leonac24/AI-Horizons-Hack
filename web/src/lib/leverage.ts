// Which unknown is actually holding the ranking up.
//
// Mirror of core/scoring.py::leverage — keep in sync.
//
// The work plan in the "what to find out" panel is only useful if it is ordered by
// what can still change the answer. That is what this computes: for each
// criterion, collapse its uncertainty band to the central estimate, resample, and
// see how much the leader's first-place share moves. A question whose answer
// cannot move it is one the CDC should not pay for yet — and saying so out loud is
// the most useful thing here, because nothing else tells them that.
//
// Every run is paired on the one seed from config, so the two SMAA passes draw the
// same weights and the same uniforms in the same order. The difference is then
// between matched samples and most of the Monte Carlo noise cancels, which is why
// a few hundred draws are enough to order the questions.
//
// This module reads evidence and weights but produces no score: it reports how
// sensitive the existing ranking is, and never changes it.

import type { Config } from '../types'
import { type Matrix, smaa } from './scoring'
import type { Option, Ranking } from './plan'

/** What settling a question would do to the current first choice. */
export type LeverageEffect = 'confirms' | 'could_unseat' | 'no_effect'

export interface CriterionLeverage {
  criterionId: string
  metricId: string
  /** Change in the leader's first-place share if this criterion were settled.
   *  Positive: the leader would come first more often. Negative: less often. */
  delta: number
  effect: LeverageEffect
}

export interface Leverage {
  leaderId: string
  /** Share of runs the leader currently comes first in, at the leverage draw
   *  count. Close to, but not identical to, the headline SMAA bar, which uses more
   *  draws — so the panel should quote the bar, not this. */
  leaderShare: number
  byCriterion: CriterionLeverage[]
  byMetricId: Record<string, CriterionLeverage>
  /** True when no open band can move the first choice at all. */
  nothingCanChangeIt: boolean
}

/** The part of a server-built inquiry that leverage needs. The full Inquiry type
 *  belongs beside the other server shapes in types.ts; this structural subset lets
 *  the maths land without waiting for it. */
export interface AffectsMetrics {
  id: string
  affects_metric_ids: string[]
  blocks_eligibility: boolean
}

export interface RankedInquiry<T extends AffectsMetrics> {
  inquiry: T
  delta: number
  effect: LeverageEffect
  /** Which criteria carried that delta, for showing why it is ranked here. */
  criterionIds: string[]
}

function effectOf(delta: number, epsilon: number): LeverageEffect {
  if (Math.abs(delta) <= epsilon) return 'no_effect'
  return delta > 0 ? 'confirms' : 'could_unseat'
}

/**
 * Per-criterion leverage for one lot at one set of weights.
 *
 * Takes the `Ranking` that `rank()` already produced rather than re-deriving the
 * comparable set, so the leader here is by construction the leader shown on screen.
 * Returns null when there is nothing to reorder.
 */
export function criterionLeverage(
  config: Config,
  ranking: Ranking,
  weights: Record<string, number>,
): Leverage | null {
  const opts: Option[] = ranking.ranked // best first, already filtered to what may be scored
  const crit = config.criteria
  if (opts.length < 2 || crit.length === 0) return null

  const { seed, profile_concentration: concentration } = config.app.smaa
  const samples = config.app.smaa.leverage_samples
  const epsilon = config.app.smaa.leverage_epsilon

  const higherIsBetter = crit.map((c) => c.direction === 'higher_is_better')
  const center = crit.map((c) => weights[c.id] ?? 0)
  const pick = (k: 'value' | 'low' | 'high'): Matrix =>
    opts.map((o) => crit.map((c) => o.metrics[c.metric_id][k]))
  const value = pick('value')
  const low = pick('low')
  const high = pick('high')

  const run = (lo: Matrix, hi: Matrix) =>
    smaa({ value, low: lo, high: hi, higherIsBetter, samples, seed, center, concentration })

  // opts[0] is the leader, because ranking.ranked is ordered best first.
  const leaderShare = run(low, high)[0][0]

  const byCriterion = crit.map((c, j) => {
    // Settle criterion j: its band becomes its central estimate, everything else
    // keeps its uncertainty. Same seed, so this is the matched counterfactual.
    const lo = low.map((row, i) => row.map((x, k) => (k === j ? value[i][j] : x)))
    const hi = high.map((row, i) => row.map((x, k) => (k === j ? value[i][j] : x)))
    const delta = run(lo, hi)[0][0] - leaderShare
    return { criterionId: c.id, metricId: c.metric_id, delta, effect: effectOf(delta, epsilon) }
  })

  return {
    leaderId: opts[0].id,
    leaderShare,
    byCriterion,
    byMetricId: Object.fromEntries(byCriterion.map((l) => [l.metricId, l])),
    nothingCanChangeIt: byCriterion.every((l) => l.effect === 'no_effect'),
  }
}

/**
 * Order a lot's open questions by what they can still change.
 *
 * Two rules, in this order:
 *
 * 1. Questions that can exclude an option come first, always. No weighting can
 *    undo an exclusion, so an unreviewed use rule outranks any amount of movement
 *    in a number. This mirrors the hard-requirements-before-weights rule in
 *    core/zoning.py.
 * 2. Then by how much settling the question could move the first choice, largest
 *    first, regardless of direction: "this could unseat your leader" is as much a
 *    reason to ask as "this would confirm it".
 *
 * Cost never enters this. A question is ranked by what its answer can change, not
 * by what finding out would cost — the illustrative figures in inquiries.yaml are
 * shown beside a question, never used to order it.
 *
 * `leverage` may be null (one option, or no criteria); the server order is then
 * kept, with exclusion-blocking questions still first.
 */
export function rankInquiries<T extends AffectsMetrics>(
  inquiries: T[],
  leverage: Leverage | null,
): RankedInquiry<T>[] {
  const scored = inquiries.map((inquiry, i) => {
    const hits = leverage
      ? inquiry.affects_metric_ids
          .map((m) => leverage.byMetricId[m])
          .filter((l): l is CriterionLeverage => !!l)
      : []
    // The criterion this question moves most. A question feeding several criteria
    // is worth what its biggest effect is worth, not the sum: settling it once
    // resolves all of them together.
    const strongest = hits.reduce<CriterionLeverage | null>(
      (best, l) => (best === null || Math.abs(l.delta) > Math.abs(best.delta) ? l : best),
      null,
    )
    return {
      inquiry,
      delta: strongest?.delta ?? 0,
      effect: strongest?.effect ?? 'no_effect',
      criterionIds: hits.filter((l) => l.effect !== 'no_effect').map((l) => l.criterionId),
      order: i,
    }
  })

  scored.sort(
    (a, b) =>
      Number(b.inquiry.blocks_eligibility) - Number(a.inquiry.blocks_eligibility) ||
      Math.abs(b.delta) - Math.abs(a.delta) ||
      a.order - b.order,
  )
  return scored.map(({ order: _order, ...rest }) => rest)
}

/** The questions worth doing something about now, and the rest. Split rather than
 *  hidden: "these cannot change your answer yet" is a finding, not filler. */
export function splitByEffect<T extends AffectsMetrics>(
  ranked: RankedInquiry<T>[],
): { nowActionable: RankedInquiry<T>[]; noEffectYet: RankedInquiry<T>[] } {
  return {
    nowActionable: ranked.filter((r) => r.inquiry.blocks_eligibility || r.effect !== 'no_effect'),
    noEffectYet: ranked.filter((r) => !r.inquiry.blocks_eligibility && r.effect === 'no_effect'),
  }
}
