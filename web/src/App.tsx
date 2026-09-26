import { useEffect, useState } from 'react'
import { api } from './api'
import { Compare, useRanking } from './components/Compare'
import { MapPicker } from './components/MapPicker'
import { Memo, WhatWeDontKnow, WorkBackwards } from './components/Pages'
import type { Analysis, Config } from './types'

type Tab = 'compare' | 'backwards' | 'unknowns'

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<Tab>('compare')
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [profileId, setProfileId] = useState<string | null>(null)

  useEffect(() => {
    api
      .config()
      .then((c) => {
        setConfig(c)
        setWeights(Object.fromEntries(c.criteria.map((x) => [x.id, x.default_weight])))
        document.title = `${c.app.name} — Pittsburgh`
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!selected) return
    setLoading(true)
    api
      .analysis(selected)
      .then((a) => {
        setAnalysis(a)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [selected])

  if (!config) return <div className="boot">{error ? `Could not load config: ${error}` : 'Loading…'}</div>

  const onWeights = (w: Record<string, number>, pid: string | null) => {
    setWeights(w)
    setProfileId(pid)
  }

  return (
    <div className="app">
      <div className="disclaimer-banner">{config.app.disclaimer}</div>
      <header className="masthead">
        <div>
          <h1>{config.app.name}</h1>
          <p className="tagline">{config.app.tagline}</p>
        </div>
        <nav>
          <button className={tab === 'compare' ? 'active' : ''} onClick={() => setTab('compare')}>
            Compare
          </button>
          <button className={tab === 'backwards' ? 'active' : ''} onClick={() => setTab('backwards')}>
            Work backwards
          </button>
          <button className={tab === 'unknowns' ? 'active' : ''} onClick={() => setTab('unknowns')}>
            What we don’t know
          </button>
          <button disabled={!analysis} onClick={() => window.print()} title="One printable page">
            Print memo
          </button>
        </nav>
      </header>
      <main className="layout">
        <aside className="left">
          <MapPicker config={config} selectedId={selected} onSelect={setSelected} />
        </aside>
        <section className="right">
          {error && <p className="error">{error}</p>}
          {tab === 'unknowns' ? (
            <WhatWeDontKnow />
          ) : !analysis ? (
            <div className="empty">
              <h2>Pick a lot</h2>
              <p>
                Every vacant lot in the City of Pittsburgh is on the map. Click one, search an address or parcel ID, or start
                from a suggested lot.
              </p>
            </div>
          ) : (
            <div className={loading ? 'loading' : ''}>
              {tab === 'compare' ? (
                <Compare config={config} analysis={analysis} weights={weights} profileId={profileId} onWeights={onWeights} />
              ) : (
                <WorkBackwards config={config} analysis={analysis} />
              )}
              <p className="small muted footer-link">
                Something missing? See <a onClick={() => setTab('unknowns')}>what we don’t know</a>.
              </p>
            </div>
          )}
        </section>
      </main>
      {analysis && <PrintMemo config={config} analysis={analysis} weights={weights} profileId={profileId} />}
    </div>
  )
}

function PrintMemo({
  config,
  analysis,
  weights,
  profileId,
}: {
  config: Config
  analysis: Analysis
  weights: Record<string, number>
  profileId: string | null
}) {
  const { order, acc } = useRanking(config, analysis, weights)
  const label = config.stakeholders.profiles.find((p) => p.id === profileId)?.label ?? 'Custom'
  const firstShare = Object.fromEntries(Object.entries(acc).map(([k, v]) => [k, v[0]]))
  return (
    <div className="print-only">
      <Memo config={config} analysis={analysis} order={order} profileLabel={label} firstShare={firstShare} />
    </div>
  )
}
