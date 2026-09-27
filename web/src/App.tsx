import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { AnalysisPanel, type Tab } from './components/AnalysisPanel'
import { LotSearchBox } from './components/ai'
import { type AiSearch, FLOOD_FILTER, passesAiFilters } from './lib/aiSearch'
import { clearShare, readShare, shareUrl, type Shared } from './lib/share'
import { CityPanel, type Filters } from './components/CityPanel'
import { Intro } from './components/Intro'
import { Tour } from './components/help'
import { HelpContext, readSeen, writeSeen } from './lib/tour'
import { Hud, Inspector, Palette } from './components/LotOverlay'
import { MemoModal } from './components/MemoModal'
import { TopBar } from './components/TopBar'
import { buildingForms, buildPool, countsOf, PLAN_ID, rank, envelopeOf, setbackCrossings } from './lib/plan'
import { createEngine, type Engine, type ParcelPoint, type Placement } from './three/engine'
import type { Analysis, Config, ParcelSummary, PlanResult, TourChapter } from './types'

// Compact properties written by pipeline/build_parcels.py::_points
interface PointProps {
  id: string
  a: number | null
  z: string | null
  n: string | null
  p: 0 | 1
  ad: string
  fh: 0 | 1 | null
  [hazard: string]: unknown
}
export type ParcelFeature = GeoJSON.Feature<GeoJSON.Point, PointProps>

// Where the viewport, HUD, palette, inspector and panel sit.
const L: Record<string, string> = { vpRight: '0px', vpBottom: '0px', hudLeft: '16px', hudMax: 'calc(100% - 458px)', palLeft: '16px', palRight: 'auto', palTop: 'auto', palBottom: '16px', palDir: 'row', palMax: 'calc(100% - 458px)', palMaxH: 'none', pTop: '90px', pRight: '16px', pBottom: '16px', pLeft: 'auto', pWidth: '410px', pHeight: 'auto', pRadius: '10px', inspLeft: '16px', inspBottom: '150px' }

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [features, setFeatures] = useState<ParcelFeature[]>([])
  const [suggested, setSuggested] = useState<ParcelSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'city' | 'lot'>('city')
  const [lotId, setLotId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [placements, setPlacements] = useState<Placement[]>([])
  const [past, setPast] = useState<Placement[][]>([])
  const [future, setFuture] = useState<Placement[][]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [plan, setPlan] = useState<PlanResult | null>(null)
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [profileId, setProfileId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('compare')
  const [showPlan, setShowPlan] = useState(true)
  const [year, setYear] = useState(0)
  const [filters, setFilters] = useState<Filters>({ district: '', minArea: 0, publicOnly: false, exclude: {} })
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<ParcelSummary[]>([])
  const [aiSearch, setAiSearch] = useState<AiSearch | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  // A scenario from a shared link, applied once its lot's analysis has loaded.
  const pendingShare = useRef<Shared | null>(null)
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 4500)
    return () => clearTimeout(t)
  }, [toast])
  const [wb, setWb] = useState({ typ: '', units: 1, ami: 60 })
  const [memo, setMemo] = useState(false)
  const [palH, setPalH] = useState(0)
  const [ready, setReady] = useState(false)
  const [entered, setEntered] = useState(false)
  const [introDone, setIntroDone] = useState(false)
  const [tour, setTour] = useState<TourChapter | null>(null)
  const vp = useRef<HTMLDivElement>(null)
  const engine = useRef<Engine | null>(null)
  const placementsRef = useRef<Placement[]>([])
  useEffect(() => {
    placementsRef.current = placements
  }, [placements])

  // --- boot ---
  useEffect(() => {
    Promise.all([api.config(), fetch('/data/parcels.geojson').then((r) => r.json()), api.suggested()])
      .then(([c, fc, sug]: [Config, GeoJSON.FeatureCollection<GeoJSON.Point, PointProps>, ParcelSummary[]]) => {
        setConfig(c)
        setFeatures(fc.features)
        setSuggested(sug)
        const first = c.stakeholders.profiles[0]
        const shared = readShare({
          lots: new Set(fc.features.map((f) => f.properties.id)),
          criteria: new Set(c.criteria.map((x) => x.id)),
          typologies: new Set(c.typologies.map((t) => t.id)),
          profiles: new Set(c.stakeholders.profiles.map((p) => p.id)),
          maxBuildings: c.app.api.plan_max_buildings,
        })
        setWeights(shared && Object.keys(shared.weights).length ? shared.weights : { ...first.weights })
        setProfileId(shared ? shared.profile : first.id)
        if (shared) {
          pendingShare.current = shared
          setEntered(true)
          setIntroDone(true)
          setLotId(shared.lot)
          setMode('lot')
        }
        setYear(Math.round(c.assumptions.analysis_years.value))
        document.title = `${c.app.name} — Pittsburgh`
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  // --- history ---
  const commit = useCallback((list: Placement[]) => {
    setPast((p) => [...p, placementsRef.current].slice(-60))
    setFuture([])
    setPlacements(list)
  }, [])
  const pastRef = useRef(past)
  const futureRef = useRef(future)
  useEffect(() => {
    pastRef.current = past
    futureRef.current = future
  }, [past, future])
  const undo = useCallback(() => {
    const p = pastRef.current
    if (!p.length) return
    const prev = p[p.length - 1]
    setPast(p.slice(0, -1))
    setFuture([placementsRef.current, ...futureRef.current])
    setPlacements(prev)
    engine.current?.setPlacements(prev)
  }, [])
  const redo = useCallback(() => {
    const f = futureRef.current
    if (!f.length) return
    const next = f[0]
    setFuture(f.slice(1))
    setPast([...pastRef.current, placementsRef.current])
    setPlacements(next)
    engine.current?.setPlacements(next)
  }, [])
  const place = useCallback((list: Placement[]) => {
    const pl = list.map((p) => ({ ...p, uid: 'b' + Math.random().toString(36).slice(2, 9) }))
    engine.current?.setPlacements(pl)
    commit(pl)
  }, [commit])

  // --- engine ---
  const openLot = useCallback((id: string) => {
    setLotId(id)
    setMode('lot')
    setPlacements([])
    setPast([])
    setFuture([])
    setSel(null)
    setPlan(null)
    setShowPlan(true)
    setAnalysis(null)
  }, [])
  // Engine callbacks are bound once; these refs always point at the latest handlers.
  const openLotRef = useRef(openLot)
  const undoRef = useRef(undo)
  const redoRef = useRef(redo)
  useEffect(() => {
    openLotRef.current = openLot
    undoRef.current = undo
    redoRef.current = redo
  }, [openLot, undo, redo])

  useEffect(() => {
    if (!config || !features.length || !vp.current) return
    const parcels: ParcelPoint[] = features.map((f) => ({ id: f.properties.id, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], public: !!f.properties.p }))
    const e = createEngine(vp.current, {
      scene: config.city.scene,
      forms: buildingForms(config),
      parcels,
      dataBase: '/data',
      snap: 2,
      onSelectLot: (id) => openLotRef.current(id),
      onChange: (list) => commit(list),
      onSelect: (uid) => setSel(uid),
      onUndo: () => undoRef.current(),
      onRedo: () => redoRef.current(),
      onReady: () => setReady(true),
    })
    engine.current = e
    return () => {
      e.dispose()
      engine.current = null
    }
  }, [config, features, commit])

  // Load the lot's analysis, then fly in.
  useEffect(() => {
    if (!lotId || !config) return
    let live = true
    api
      .analysis(lotId)
      .then((a) => {
        if (!live) return
        setAnalysis(a)
        const firstFit = [...a.scenarios].reverse().find((s) => s.form_fits) ?? a.scenarios[0]
        setWb((w) => ({ ...w, typ: firstFit.typology_id, units: firstFit.units }))
        const hill = Object.entries(config.city.hazards).some(([k, h]) => h.lot_scene === 'hill' && a.parcel[k])
        const shared = pendingShare.current?.lot === a.parcel.id ? pendingShare.current : null
        const list = (shared?.placements ?? []).map((b) => ({ ...b, uid: 'b' + Math.random().toString(36).slice(2, 9) }))
        pendingShare.current = null
        if (shared) clearShare()
        if (list.length) setPlacements(list)
        void engine.current?.goLot({ id: a.parcel.id, lon: a.parcel.lon, lat: a.parcel.lat, frontage: a.lot_shape.frontage_ft, depth: a.lot_shape.depth_ft, hill }, list)
      })
      .catch((e: Error) => setError(e.message))
    return () => {
      live = false
    }
  }, [lotId, config])

  // Evaluate the user's plan on the server whenever it changes (debounced).
  useEffect(() => {
    if (!lotId || !placements.length) {
      setPlan(null)
      return
    }
    const ctl = new AbortController()
    const t = setTimeout(() => {
      api.plan(lotId, countsOf(placements), ctl.signal).then(setPlan).catch(() => {})
    }, 120)
    return () => {
      clearTimeout(t)
      ctl.abort()
    }
  }, [lotId, placements])

  useEffect(() => engine.current?.setShowPlan(showPlan), [showPlan])
  // Reviewed setbacks: drawn as the buildable area; buildings crossing them are flagged.
  const envelope = useMemo(() => (analysis ? envelopeOf(analysis) : null), [analysis])
  const crossings = useMemo(
    () => (analysis ? setbackCrossings(config!, placements, analysis.lot_shape, envelope) : []),
    [config, analysis, placements, envelope],
  )
  useEffect(() => engine.current?.setEnvelope(envelope), [envelope])
  useEffect(() => {
    const failed = plan ? placements.filter((p) => plan.failed_typologies.includes(p.typ)).map((p) => p.uid) : []
    engine.current?.setWarnings([...new Set([...failed, ...crossings.map((c) => c.uid)])])
  }, [plan, placements, crossings])

  // City filters drive which parcel dots show; pins are suggested lots + search hits.
  const visibleIds = useMemo(() => {
    const q = query.trim().toLowerCase()
    const out = new Set<string>()
    for (const f of features) {
      const p = f.properties
      if ((p.a ?? 0) < filters.minArea) continue
      if (filters.district && p.z !== filters.district) continue
      if (filters.publicOnly && !p.p) continue
      if (Object.entries(filters.exclude).some(([h, on]) => on && p[h])) continue
      if (aiSearch && !passesAiFilters(aiSearch.result.filters, p)) continue
      if (q.length >= 2 && !(p.ad.toLowerCase().includes(q) || p.id.toLowerCase().includes(q) || (p.n ?? '').toLowerCase().includes(q))) continue
      out.add(p.id)
    }
    return out
  }, [features, filters, query, aiSearch])
  useEffect(() => engine.current?.setVisibleParcels(visibleIds), [visibleIds, config, features])
  useEffect(() => {
    if (query.trim().length < 2) {
      setHits([])
      return
    }
    const t = setTimeout(() => api.search(query).then(setHits).catch(() => setHits([])), 250)
    return () => clearTimeout(t)
  }, [query])
  const pinLots = useMemo(() => {
    const src = aiSearch ? aiSearch.result.results : hits.length ? hits : suggested.filter((s) => visibleIds.has(s.id))
    return src.map((s) => ({ id: s.id, lon: s.lon, lat: s.lat, public: s.public, neighborhood: s.neighborhood, zoning: s.zoning, area: s.lot_area_sf ?? 0 }))
  }, [aiSearch, hits, suggested, visibleIds])
  useEffect(() => engine.current?.setPins(pinLots), [pinLots, config, features])

  // First visit plays the city chapter; the first lot opened plays the lot chapter.
  // Finishing a chapter or skipping the tutorial is remembered in this browser.
  const lotReady = mode === 'lot' && !!analysis
  useEffect(() => {
    if (!config || !features.length || !introDone) return
    if (mode === 'lot' && !lotReady) return
    const chapter: TourChapter = mode
    if (config.app.tutorial.chapters[chapter]?.length && !readSeen(config.app.tutorial.storage_key)[chapter]) setTour(chapter)
  }, [config, features.length, mode, lotReady, introDone])
  const endTour = (how: 'done' | 'skipped') => {
    if (!config || !tour) return
    const key = config.app.tutorial.storage_key
    const seen = readSeen(key)
    if (how === 'done') seen[tour] = 'done'
    // Skipping means skipping the whole tutorial, not just this screen.
    else for (const c of Object.keys(config.app.tutorial.chapters) as TourChapter[]) seen[c] ??= 'skipped'
    writeSeen(key, seen)
    setTour(null)
  }

  const pool = useMemo(() => (config && analysis ? buildPool(config, analysis, placements.length ? plan : null) : []), [config, analysis, plan, placements.length])
  const ranking = useMemo(() => (config ? rank(config, pool, weights) : null), [config, pool, weights])

  if (!config) return <Intro app={null} ready={false} leaving={false} error={error} onEnter={() => {}} />
  // Bottom-tray layout: stack the inspector above the palette's measured height.
  const lotL = L.palDir === 'row' && palH ? { ...L, inspBottom: `calc(${L.palBottom} + ${palH + 12}px)` } : L
  const runAiSearch = (q: string) => {
    setAiLoading(true)
    setAiError(null)
    api
      .lotSearch(q)
      .then((r) => {
        if (!r.ok) {
          setAiError(`AI search is unavailable right now (${r.reason}). The filters below still work.`)
          return
        }
        setAiSearch({ query: q, result: r })
        engine.current?.frameLots(r.results)
      })
      .catch((e: Error) => setAiError(e.message))
      .finally(() => setAiLoading(false))
  }
  const toCity = () => {
    if (mode !== 'lot') return
    void engine.current?.goCity()
    setMode('city')
    setSel(null)
    setMemo(false)
  }
  const onWeights = (w: Record<string, number>, pid: string | null) => {
    setWeights(w)
    setProfileId(pid)
  }
  const planOpt = pool.find((o) => o.id === PLAN_ID)

  return (
    <HelpContext.Provider value={config.app.help}>
    <div className={`shell${entered ? '' : ' pre-intro'}`}>
      <div ref={vp} className="viewport" style={{ right: lotL.vpRight, bottom: mode === 'lot' ? lotL.vpBottom : '0px' }} />
      <TopBar
        mode={mode}
        lot={analysis?.parcel ?? null}
        onCity={toCity}
        showPlan={showPlan}
        setShowPlan={(v) => {
          setShowPlan(v)
          if (!v) setSel(null)
        }}
        canUndo={past.length > 0}
        canRedo={future.length > 0}
        onUndo={undo}
        onRedo={redo}
        onClear={() => placements.length && place([])}
        onReset={() => engine.current?.resetView()}
        onMemo={() => setMemo(true)}
        onShare={() => {
          if (!lotId) return
          const url = shareUrl({ lot: lotId, weights, profile: profileId, placements })
          navigator.clipboard
            .writeText(url)
            .then(() => setToast('Link copied: it reopens this lot with these priorities and buildings.'))
            .catch(() => setToast(url))
        }}
        onHelp={() => setTour(mode)}
        disclaimer={config.app.disclaimer}
      />
      {error && <div className="error-toast">{error}</div>}
      {toast && (
        <div className="info-toast" role="status" onClick={() => setToast(null)}>
          {toast}
        </div>
      )}
      {mode === 'city' && (
        <CityPanel
          config={config}
          features={features}
          visibleCount={visibleIds.size}
          filters={filters}
          setFilters={setFilters}
          query={query}
          setQuery={setQuery}
          cards={aiSearch ? aiSearch.result.results : hits.length ? hits : suggested}
          cardsAreHits={!!aiSearch || hits.length > 0}
          cardsTitle={aiSearch ? `Largest matching lots` : undefined}
          aiBox={
            <LotSearchBox
              search={aiSearch}
              loading={aiLoading}
              error={aiError}
              maxChars={config.app.api.lot_search_query_max_chars}
              example={config.app.ask.search_example}
              hazardLabel={(h) => (h === FLOOD_FILTER ? 'FEMA high-risk flood zone' : config.city.hazards[h]?.label ?? h)}
              onSearch={runAiSearch}
              onClear={() => {
                setAiSearch(null)
                setAiError(null)
              }}
            />
          }
          onOpen={openLot}
        />
      )}
      {mode === 'lot' && analysis && ranking && (
        <>
          <Hud
            config={config}
            L={lotL}
            analysis={analysis}
            plan={planOpt ?? null}
            ranking={ranking}
            profileLabel={config.stakeholders.profiles.find((p) => p.id === profileId)?.label ?? 'Custom'}
            year={year}
            wbAmi={wb.ami}
            showPlan={showPlan}
            empty={!placements.length}
          />
          <Palette config={config} L={lotL} analysis={analysis} counts={countsOf(placements)} onDown={(id, e) => engine.current?.beginDrag(id, e)} onHeight={setPalH} />
          {sel && showPlan && (
            <Inspector
              config={config}
              L={lotL}
              placement={placements.find((p) => p.uid === sel) ?? null}
              analysis={analysis}
              onRotate={() => engine.current?.rotateSelected()}
              onDelete={() => engine.current?.deleteSelected()}
            />
          )}
          <AnalysisPanel
            config={config}
            L={lotL}
            analysis={analysis}
            pool={pool}
            ranking={ranking}
            weights={weights}
            profileId={profileId}
            onWeights={onWeights}
            tab={tab}
            setTab={setTab}
            year={year}
            setYear={setYear}
            wb={wb}
            setWb={setWb}
            onPlace={place}
            envelope={envelope}
            crossings={crossings}
          />
        </>
      )}
      {memo && analysis && ranking && (
        <MemoModal config={config} analysis={analysis} ranking={ranking} profileLabel={config.stakeholders.profiles.find((p) => p.id === profileId)?.label ?? 'Custom'} onClose={() => setMemo(false)} />
      )}
      {!introDone && (
        <Intro
          app={config.app}
          lotCount={features.length}
          ready={ready}
          leaving={entered}
          error={error}
          onEnter={() => {
            setEntered(true)
            void engine.current?.enter()
            setTimeout(() => setIntroDone(true), 1400)
          }}
        />
      )}
      {tour && config.app.tutorial.chapters[tour]?.length && (
        <Tour key={tour} steps={config.app.tutorial.chapters[tour]!} onFinish={() => endTour('done')} onSkip={() => endTour('skipped')} />
      )}
    </div>
    </HelpContext.Provider>
  )
}
