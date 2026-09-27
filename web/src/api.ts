import type {
  Analysis,
  Config,
  Explanation,
  EvidenceLeads,
  ParcelSummary,
  PlanResult,
  Unknowns,
  WorkBackwardsResult,
} from './types'

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`)
  return (await r.json()) as T
}

export const api = {
  config: () => get<Config>('/api/config'),
  suggested: () => get<ParcelSummary[]>('/api/parcels/suggested'),
  search: (q: string) => get<ParcelSummary[]>(`/api/parcels/search?q=${encodeURIComponent(q)}`),
  analysis: (id: string) => get<Analysis>(`/api/analysis/${encodeURIComponent(id)}`),
  unknowns: () => get<Unknowns>('/api/unknowns'),
  evidence: (topic = 'zoning', offset = 0, limit = 20) =>
    get<EvidenceLeads>(`/api/evidence?topic=${encodeURIComponent(topic)}&offset=${offset}&limit=${limit}`),
  workBackwards: (id: string, typology: string, units: number, amiPct: number) =>
    get<WorkBackwardsResult>(
      `/api/work-backwards/${encodeURIComponent(id)}?typology=${encodeURIComponent(typology)}&units=${units}&target_ami_pct=${amiPct}`,
    ),
  plan: async (id: string, counts: Record<string, number>, signal?: AbortSignal) => {
    const r = await fetch(`/api/analysis/${encodeURIComponent(id)}/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ placements: Object.entries(counts).map(([typology_id, count]) => ({ typology_id, count })) }),
      signal,
    })
    if (!r.ok) throw new Error(`plan: ${r.status}`)
    return (await r.json()) as PlanResult
  },
  explain: async (parcelId: string, weights: Record<string, number>, ranking: string[]) => {
    const r = await fetch('/api/explain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parcel_id: parcelId, weights, ranking }),
    })
    if (!r.ok) throw new Error(`explain: ${r.status}`)
    return (await r.json()) as Explanation
  },
}
