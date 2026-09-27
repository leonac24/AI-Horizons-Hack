import type { LotSearchFilters, LotSearchResult } from '../types'

/** Mirrors server/lot_search.FLOOD: the FEMA flag is a filter value next to the config hazards. */
export const FLOOD_FILTER = 'fema_high_risk_flood'

export type AiSearch = { query: string; result: Extract<LotSearchResult, { ok: true }> }

/** Does a map point pass the filters the model chose? Same rules as server/lot_search.matches. */
export function passesAiFilters(f: LotSearchFilters, p: { a: number | null; z: string | null; n: string | null; p: 0 | 1; fh: 0 | 1 | null; [k: string]: unknown }) {
  const area = p.a ?? 0
  return (
    (!f.neighborhoods.length || (p.n !== null && f.neighborhoods.includes(p.n))) &&
    (!f.zoning_districts.length || (p.z !== null && f.zoning_districts.includes(p.z))) &&
    (f.min_lot_sf === null || area >= f.min_lot_sf) &&
    (f.max_lot_sf === null || area <= f.max_lot_sf) &&
    (!f.publicly_held_only || p.p === 1) &&
    !f.avoid.some((h) => (h === FLOOD_FILTER ? p.fh === 1 : !!p[h]))
  )
}
