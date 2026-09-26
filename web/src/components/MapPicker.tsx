import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource, MapLayerMouseEvent } from 'maplibre-gl'
// Bundle MapLibre's worker (and the chunk it imports) into one file and point
// MapLibre at it; otherwise production builds look for a file that isn't emitted.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { Config, ParcelSummary } from '../types'

// Compact properties written by pipeline/build_parcels.py::_points
interface PointProps {
  id: string
  a: number | null // lot area sf
  z: string | null // zoning district
  n: string | null // neighborhood
  p: 0 | 1 // publicly held
  ad: string
  [hazard: string]: unknown
}
maplibregl.setWorkerUrl(workerUrl)

type Feature = GeoJSON.Feature<GeoJSON.Point, PointProps>

interface Filters {
  minArea: number
  district: string
  publicOnly: boolean
  exclude: Record<string, boolean> // hazard flag -> exclude lots with it
}

interface Props {
  config: Config
  selectedId: string | null
  onSelect: (id: string) => void
}

export function MapPicker({ config, selectedId, onSelect }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [features, setFeatures] = useState<Feature[]>([])
  const [suggested, setSuggested] = useState<ParcelSummary[]>([])
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ParcelSummary[]>([])
  const [filters, setFilters] = useState<Filters>({ minArea: 0, district: '', publicOnly: false, exclude: {} })
  const hazards = Object.entries(config.city.hazards)

  useEffect(() => {
    fetch('/data/parcels.geojson')
      .then((r) => r.json())
      .then((fc: GeoJSON.FeatureCollection<GeoJSON.Point, PointProps>) => setFeatures(fc.features))
    api.suggested().then(setSuggested)
  }, [])

  const districts = useMemo(() => countBy(features, (f) => f.properties.z), [features])
  const hoods = useMemo(() => {
    const acc: Record<string, { n: number; x: number; y: number }> = {}
    for (const f of features) {
      const h = f.properties.n
      if (!h) continue
      const [x, y] = f.geometry.coordinates
      const a = (acc[h] ??= { n: 0, x: 0, y: 0 })
      a.n++
      a.x += x
      a.y += y
    }
    return Object.entries(acc)
      .map(([name, a]) => ({ name, n: a.n, center: [a.x / a.n, a.y / a.n] as [number, number] }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [features])

  const visible = useMemo(
    () =>
      features.filter((f) => {
        const p = f.properties
        if ((p.a ?? 0) < filters.minArea) return false
        if (filters.district && p.z !== filters.district) return false
        if (filters.publicOnly && !p.p) return false
        for (const [h, on] of Object.entries(filters.exclude)) if (on && p[h]) return false
        return true
      }),
    [features, filters],
  )

  // Create the map once.
  useEffect(() => {
    if (!el.current || map.current) return
    const m = new maplibregl.Map({
      container: el.current,
      style: config.city.map.basemap_style,
      center: config.city.map.center,
      zoom: config.city.map.zoom,
      attributionControl: { compact: true },
    })
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    // Add our layers as soon as the style is parsed; 'load' also waits for every
    // basemap tile and can stall on a slow tile server.
    const addLayers = () => {
      if (m.getSource('parcels')) return
      m.addSource('parcels', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addLayer({
        id: 'parcels',
        type: 'circle',
        source: 'parcels',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 1.6, 14, 4, 17, 8],
          'circle-color': ['case', ['==', ['get', 'p'], 1], '#a4553a', '#4f6d7a'],
          'circle-opacity': 0.75,
          'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 12, 0, 15, 0.8],
          'circle-stroke-color': '#fdfaf3',
        },
      })
      m.addLayer({
        id: 'selected',
        type: 'circle',
        source: 'parcels',
        filter: ['==', ['get', 'id'], ''],
        paint: { 'circle-radius': 10, 'circle-color': 'transparent', 'circle-stroke-width': 3, 'circle-stroke-color': '#2a2522' },
      })
      m.on('click', 'parcels', (e: MapLayerMouseEvent) => {
        const id = e.features?.[0]?.properties?.id
        if (typeof id === 'string') onSelect(id)
      })
      m.on('mouseenter', 'parcels', () => (m.getCanvas().style.cursor = 'pointer'))
      m.on('mouseleave', 'parcels', () => (m.getCanvas().style.cursor = ''))
      setFeatures((f) => [...f]) // trigger data push once the source exists
    }
    m.on('style.load', addLayers)
    map.current = m
    if (import.meta.env.DEV) (window as unknown as { __map: unknown }).__map = m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const src = map.current?.getSource('parcels') as GeoJSONSource | undefined
    src?.setData({ type: 'FeatureCollection', features: visible })
  }, [visible])

  useEffect(() => {
    const m = map.current
    if (!m || !m.getLayer('selected')) return
    m.setFilter('selected', ['==', ['get', 'id'], selectedId ?? ''])
    const f = features.find((x) => x.properties.id === selectedId)
    if (f) m.easeTo({ center: f.geometry.coordinates as [number, number], zoom: Math.max(m.getZoom(), 15) })
  }, [selectedId, features])

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([])
      return
    }
    const t = setTimeout(() => api.search(query).then(setResults).catch(() => setResults([])), 250)
    return () => clearTimeout(t)
  }, [query])

  return (
    <section className="picker">
      <div className="picker-controls">
        <input
          className="search"
          placeholder="Search address or parcel ID"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {results.length > 0 && (
          <ul className="search-results">
            {results.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => {
                    onSelect(r.id)
                    setQuery('')
                  }}
                >
                  {r.address || r.id} <span className="muted">· {r.neighborhood} · {r.zoning}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="filter-row">
          <label>
            Neighborhood
            <select
              defaultValue=""
              onChange={(e) => {
                const h = hoods.find((x) => x.name === e.target.value)
                if (h) map.current?.flyTo({ center: h.center, zoom: 14.5 })
              }}
            >
              <option value="">Jump to…</option>
              {hoods.map((h) => (
                <option key={h.name} value={h.name}>
                  {h.name} ({h.n})
                </option>
              ))}
            </select>
          </label>
          <label>
            Zoning
            <select value={filters.district} onChange={(e) => setFilters({ ...filters, district: e.target.value })}>
              <option value="">All districts</option>
              {districts.map(([d, n]) => (
                <option key={d} value={d}>
                  {d} ({n})
                </option>
              ))}
            </select>
          </label>
          <label>
            Min lot {filters.minArea.toLocaleString()} sf
            <input
              type="range"
              min={0}
              max={20000}
              step={500}
              value={filters.minArea}
              onChange={(e) => setFilters({ ...filters, minArea: Number(e.target.value) })}
            />
          </label>
        </div>
        <div className="filter-row checks">
          <label>
            <input
              type="checkbox"
              checked={filters.publicOnly}
              onChange={(e) => setFilters({ ...filters, publicOnly: e.target.checked })}
            />
            Publicly held only
          </label>
          {hazards.map(([h, spec]) => (
            <label key={h}>
              <input
                type="checkbox"
                checked={!!filters.exclude[h]}
                onChange={(e) => setFilters({ ...filters, exclude: { ...filters.exclude, [h]: e.target.checked } })}
              />
              Hide {spec.label.toLowerCase()}
            </label>
          ))}
          <span className="muted small" title="Flood (FEMA NFHL) and transit access are not loaded yet — see What we don't know">
            Flood & transit filters: not loaded yet
          </span>
        </div>
        <div className="legend small">
          <span className="dot" style={{ background: '#a4553a' }} /> publicly held
          <span className="dot" style={{ background: '#4f6d7a' }} /> other vacant
          <span className="muted"> · {visible.length.toLocaleString()} of {features.length.toLocaleString()} vacant lots</span>
        </div>
      </div>
      <div ref={el} className="map" />
      <div className="suggested">
        <h3>Suggested starting points</h3>
        <p className="muted small">Spread across neighborhoods, zoning districts and site conditions — not recommendations.</p>
        <div className="chips">
          {suggested.map((s) => (
            <button key={s.id} className={`chip ${s.id === selectedId ? 'active' : ''}`} onClick={() => onSelect(s.id)}>
              {s.neighborhood} · {s.zoning} · {Math.round(s.lot_area_sf ?? 0).toLocaleString()} sf
              {s.public ? ' · public' : ''}
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}

function countBy<T>(xs: T[], key: (x: T) => string | null): [string, number][] {
  const c: Record<string, number> = {}
  for (const x of xs) {
    const k = key(x)
    if (k) c[k] = (c[k] ?? 0) + 1
  }
  return Object.entries(c).sort((a, b) => b[1] - a[1])
}
