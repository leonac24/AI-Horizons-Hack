import { useMemo } from 'react'
import type { ParcelFeature } from '../App'
import type { Config, ParcelSummary } from '../types'

export interface Filters {
  district: string
  minArea: number
  publicOnly: boolean
  exclude: Record<string, boolean>
}

interface Props {
  config: Config
  features: ParcelFeature[]
  visibleCount: number
  filters: Filters
  setFilters: (f: Filters) => void
  query: string
  setQuery: (q: string) => void
  cards: ParcelSummary[]
  cardsAreHits: boolean
  onOpen: (id: string) => void
}

export function CityPanel({ config, features, visibleCount, filters, setFilters, query, setQuery, cards, cardsAreHits, onOpen }: Props) {
  const districts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const f of features) if (f.properties.z) c[f.properties.z] = (c[f.properties.z] ?? 0) + 1
    return Object.entries(c).sort((a, b) => b[1] - a[1])
  }, [features])
  const hazardsOf = useMemo(() => {
    const byId = new Map(features.map((f) => [f.properties.id, f.properties]))
    return (id: string) => {
      const p = byId.get(id)
      return Object.entries(config.city.hazards)
        .filter(([k]) => p && p[k])
        .map(([, h]) => h.label)
    }
  }, [features, config])

  return (
    <>
      <aside className="city-panel">
        <div className="cp-head">
          <div className="h-title">Pick a lot</div>
          <p className="muted">Every vacant lot in the City of Pittsburgh is on the map. Click one, search an address or parcel ID, or start from a suggested lot.</p>
          <input className="field" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search address or parcel ID" />
          <div className="cp-grid">
            <label>
              Zoning
              <select className="field-sm" value={filters.district} onChange={(e) => setFilters({ ...filters, district: e.target.value })}>
                <option value="">All districts</option>
                {districts.map(([d, n]) => (
                  <option key={d} value={d}>
                    {d} ({n.toLocaleString()})
                  </option>
                ))}
              </select>
            </label>
            <label className="nowrap">
              <span>Min lot {filters.minArea.toLocaleString()} sf</span>
              <input type="range" className="lime-range" min={0} max={10000} step={500} value={filters.minArea} onChange={(e) => setFilters({ ...filters, minArea: Number(e.target.value) })} />
            </label>
          </div>
          <div className="cp-checks">
            <label>
              <input type="checkbox" checked={filters.publicOnly} onChange={(e) => setFilters({ ...filters, publicOnly: e.target.checked })} />
              Publicly held only
            </label>
            {Object.entries(config.city.hazards).map(([id, h]) => (
              <label key={id}>
                <input type="checkbox" checked={!!filters.exclude[id]} onChange={(e) => setFilters({ ...filters, exclude: { ...filters.exclude, [id]: e.target.checked } })} />
                <span>Hide {h.label.toLowerCase()}</span>
              </label>
            ))}
            <span className="dim small">Flood &amp; transit filters: not loaded yet</span>
          </div>
        </div>
        <div className="cp-legend">
          <span><i style={{ background: '#b6f23e' }} />suggested / search hit</span>
          <span><i style={{ background: '#ff6b4a' }} />publicly held</span>
          <span><i style={{ background: '#5aa9d6' }} />other vacant</span>
        </div>
        <div className="eyebrow cp-count">
          {cardsAreHits ? 'Search results' : 'Suggested starting points'} · {visibleCount.toLocaleString()} of {features.length.toLocaleString()} lots shown
        </div>
        <div className="cp-cards">
          {cards.map((c) => {
            const haz = hazardsOf(c.id)
            return (
              <button key={c.id} className="lot-card" onClick={() => onOpen(c.id)}>
                <span className="lc-top">
                  <span className="strong">{c.neighborhood ?? '—'}</span>
                  <span className="lc-zone">{c.zoning ?? '—'}</span>
                </span>
                <span className="muted small">
                  {c.address || c.id} · {Math.round(c.lot_area_sf ?? 0).toLocaleString()} sf{c.public ? ' · public' : ''}
                </span>
                {haz.length > 0 && <span className="warn small">{haz.join(' · ')}</span>}
              </button>
            )
          })}
        </div>
        <div className="cp-foot hatched small">Suggested lots are spread across neighborhoods, zoning and site conditions — not recommendations. The city model is stylized; lot positions are real.</div>
      </aside>
      <div className="hint-pill">Drag to orbit · right-drag to pan · scroll to zoom · click a lot to zoom in</div>
    </>
  )
}
