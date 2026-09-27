import type {
  Analysis,
  Config,
  Explanation,
  EvidenceLeads,
  LotAnswer,
  NextStep,
  OutreachDraft,
  LotSearchResult,
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

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (r.status === 429) throw new Error('Too many AI requests right now. Wait a minute and try again.')
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return (await r.json()) as T
}

export const api = {
  config: () => get<Config>('/api/config'),
  suggested: () => get<ParcelSummary[]>('/api/parcels/suggested'),
  search: (q: string) => get<ParcelSummary[]>(`/api/parcels/search?q=${encodeURIComponent(q)}`),
  analysis: (id: string) => get<Analysis>(`/api/analysis/${encodeURIComponent(id)}`),
  unknowns: () => get<Unknowns>('/api/unknowns'),
  evidence: (topic: string, offset = 0, limit = 20) =>
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
  ask: (parcelId: string, weights: Record<string, number>, ranking: string[], question: string) =>
    post<LotAnswer>('/api/ask', { parcel_id: parcelId, weights, ranking, question }),
  nextSteps: (id: string) => get<NextStep[]>(`/api/next-steps/${encodeURIComponent(id)}`),
  draft: (parcelId: string, stepId: NextStep['id']) => post<OutreachDraft>('/api/draft', { parcel_id: parcelId, step_id: stepId }),
  lotSearch: (query: string) => post<LotSearchResult>('/api/parcels/ask', { query }),
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
