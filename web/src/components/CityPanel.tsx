import { useMemo, type ReactNode } from 'react'
import type { ParcelFeature } from '../App'
import { districtColor } from '../lib/format'
import { HelpTip } from './help'
import { MARKER_COLORS } from '../three/engine'
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
  cardsTitle?: string
  aiBox?: ReactNode
  onOpen: (id: string) => void
}

export function CityPanel({ config, features, visibleCount, filters, setFilters, query, setQuery, cards, cardsAreHits, cardsTitle, aiBox, onOpen }: Props) {
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
        <div className="cp-hero">
          <div className="h-title">Pick a lot<HelpTip id="pick_lot" /></div>
          <p>Every vacant lot in the City of Pittsburgh is on the map. Click one, search an address or parcel ID, or start from a suggested lot.</p>
        </div>
        <div className="cp-head">
          {aiBox && (
            <div data-tour="ai-search">
              <div className="eyebrow cp-label">Find lots with AI<HelpTip id="ai_search" /></div>
              {aiBox}
            </div>
          )}
          <div data-tour="filters">
          <div className="eyebrow cp-label">Search and filter<HelpTip id="filters" /></div>
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
            <label>
              <input type="checkbox" checked={!!filters.exclude.fh} onChange={(e) => setFilters({ ...filters, exclude: { ...filters.exclude, fh: e.target.checked } })} />
              Hide lots whose tested point is in a FEMA high-risk flood zone
            </label>
            <span className="dim small">Unmatched flood locations stay visible; transit job access is not measured yet.</span>
          </div>
          </div>
        </div>
        <div className="cp-legend" data-tour="legend">
          <span><i style={{ background: MARKER_COLORS.pin }} />suggested / search hit</span>
          <span><i style={{ background: MARKER_COLORS.public }} />publicly held</span>
          <span><i style={{ background: MARKER_COLORS.other }} />other vacant</span>
          <HelpTip id="legend" />
        </div>
        <div className="eyebrow cp-count">
          {cardsTitle ?? (cardsAreHits ? 'Search results' : 'Suggested starting points')} · {visibleCount.toLocaleString()} of {features.length.toLocaleString()} lots shown
          <HelpTip id="suggested" />
        </div>
        <div className="cp-cards" data-tour="lot-cards">
          {cards.map((c) => {
            const haz = hazardsOf(c.id)
            return (
              <button key={c.id} className="lot-card" onClick={() => onOpen(c.id)}>
                <span className="lc-top">
                  <span className="lc-name">{c.neighborhood ?? '—'}</span>
                  <span className="lc-zone" style={{ background: districtColor(config, c.zoning) }}>{c.zoning ?? '—'}</span>
                </span>
                <span className="muted small">
                  {c.address || c.id} · {Math.round(c.lot_area_sf ?? 0).toLocaleString()} sf{c.public ? ' · public' : ''}
                </span>
                {haz.length > 0 && <span className="haz-pill">{haz.join(' · ')}</span>}
              </button>
            )
          })}
        </div>
        <div className="cp-foot hatched small">Suggested lots are spread across neighborhoods, zoning and site conditions — not recommendations. The city model is stylized; lot positions are real.</div>
      </aside>
      <div className="hint-pill" data-tour="map-hint">Drag to orbit · right-drag to pan · scroll to zoom · click a lot to zoom in</div>
    </>
  )
}
