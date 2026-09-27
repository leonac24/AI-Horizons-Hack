import { useEffect, useState } from 'react'
import { api } from '../api'
import type { AiSearch } from '../lib/aiSearch'
import type { LotAnswer } from '../types'

type Sentence = { text: string; metric_ids: string[] }

/** Three bouncing dots; the parent says what is loading. */
export function Dots() {
  return (
    <span className="dots" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  )
}

// Words and the spaces between them are separate tokens: ~40 words a second.
const MS_PER_TOKEN = 12

const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/**
 * Checked sentences, typed out word by word. The text has already passed the
 * server's grounding check; the animation only shows it arriving. Each
 * sentence's metric chips appear once that sentence is complete.
 */
export function TypedSentences({ sentences, chip }: { sentences: Sentence[]; chip: (metricId: string) => string }) {
  const words = sentences.map((s) => s.text.split(/(\s+)/))
  const total = words.reduce((n, w) => n + w.length, 0)
  const [shown, setShown] = useState(() => (reducedMotion() ? total : 0))
  useEffect(() => {
    // Driven by elapsed time, not tick count, so a busy frame (the 3D scene)
    // makes the text jump ahead instead of slowing the whole reveal down.
    const t0 = performance.now()
    let raf = 0
    const step = () => {
      const n = Math.min(total, Math.floor((performance.now() - t0) / MS_PER_TOKEN))
      setShown((cur) => Math.max(cur, n))
      if (n < total) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [total])
  const starts = words.map((_, i) => words.slice(0, i).reduce((n, w) => n + w.length, 0))
  return (
    <div onClick={() => setShown(total)} title={shown < total ? 'Click to show all' : undefined}>
      {sentences.map((s, i) => {
        const start = starts[i]
        if (shown <= start) return null
        const done = shown >= start + words[i].length
        return (
          <p key={i}>
            {words[i].slice(0, shown - start).join('')}
            {!done && <span className="caret" aria-hidden="true" />}
            {done && ' '}
            {done && s.metric_ids.map((id) => <span key={id} className="chip">{chip(id)}</span>)}
          </p>
        )
      })}
    </div>
  )
}

/** A free-text question about one lot, answered only from its computed metrics.
 *  Give it `key={parcelId}` so a new lot starts with an empty box. */
export function AskLot({ parcelId, weights, ranking, examples, maxChars, chip }: {
  parcelId: string
  weights: Record<string, number>
  ranking: string[]
  examples: string[]
  maxChars: number
  chip: (metricId: string) => string
}) {
  const [q, setQ] = useState('')
  const [asked, setAsked] = useState('')
  const [answer, setAnswer] = useState<LotAnswer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const submit = (question: string) => {
    const text = question.trim()
    if (!text || loading) return
    setQ(text)
    setAsked(text)
    setAnswer(null)
    setError(null)
    setLoading(true)
    api
      .ask(parcelId, weights, ranking, text)
      .then(setAnswer)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }
  return (
    <div className="ask">
      <form
        className="ask-row"
        onSubmit={(e) => {
          e.preventDefault()
          submit(q)
        }}
      >
        <input className="field" value={q} maxLength={maxChars} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything about this lot…" aria-label="Ask a question about this lot" />
        <button className="go-btn" disabled={loading || !q.trim()} aria-busy={loading}>
          {loading ? <Dots /> : 'Ask AI'}
        </button>
      </form>
      {!answer && !loading && (
        <div className="ask-examples">
          {examples.map((ex) => (
            <button key={ex} className="ask-example" onClick={() => submit(ex)}>
              {ex}
            </button>
          ))}
        </div>
      )}
      {loading && (
        <div className="expl dim small">
          Reading this lot's numbers to answer “{asked}”
          <Dots />
        </div>
      )}
      {error && <div className="expl small">{error}</div>}
      {answer && (
        <div className="expl">
          <div className="dim small">
            “{asked}” ·{' '}
            {answer.answerable === true
              ? `Answered by ${answer.source}, then checked against the numbers on this page.`
              : answer.answerable === false
                ? 'This lot’s data can’t answer that. Try asking about affordability, homes, zoning, carbon or who each option serves.'
                : `No checked answer this time (${answer.reason ?? 'unknown'}). Try rephrasing.`}
          </div>
          {answer.answerable && <TypedSentences key={asked} sentences={answer.sentences} chip={chip} />}
        </div>
      )}
    </div>
  )
}

/** "Describe the lots you want" — the model picks filters, code finds the lots. */
export function LotSearchBox({ search, loading, error, maxChars, example, hazardLabel, onSearch, onClear }: {
  search: AiSearch | null
  example: string
  loading: boolean
  error: string | null
  maxChars: number
  hazardLabel: (id: string) => string
  onSearch: (q: string) => void
  onClear: () => void
}) {
  const [q, setQ] = useState('')
  const f = search?.result.filters
  const chips = f
    ? [
        ...f.neighborhoods,
        ...f.zoning_districts.map((d) => `zoning ${d}`),
        ...(f.min_lot_sf !== null ? [`at least ${Math.round(f.min_lot_sf).toLocaleString()} sf`] : []),
        ...(f.max_lot_sf !== null ? [`at most ${Math.round(f.max_lot_sf).toLocaleString()} sf`] : []),
        ...(f.publicly_held_only ? ['publicly held'] : []),
        ...f.avoid.map((h) => `not ${hazardLabel(h).toLowerCase()}`),
      ]
    : []
  return (
    <div className="ai-search">
      <form
        className="ask-row"
        onSubmit={(e) => {
          e.preventDefault()
          if (q.trim() && !loading) onSearch(q.trim())
        }}
      >
        <input className="field" value={q} maxLength={maxChars} onChange={(e) => setQ(e.target.value)} placeholder="Describe the lots you want, in your own words" aria-label="Describe the lots you want" />
        <button className="go-btn" disabled={loading || !q.trim()} aria-busy={loading}>
          {loading ? <Dots /> : 'Find with AI'}
        </button>
      </form>
      {!search && !loading && !error && example && <div className="dim small">e.g. “{example}”</div>}
      {loading && (
        <div className="dim small">
          Reading your request and turning it into map filters
          <Dots />
        </div>
      )}
      {error && <div className="small">{error}</div>}
      {search && f && (
        <div className="ai-read">
          <div className="small">
            <strong>{search.result.match_count.toLocaleString()}</strong> vacant lots match. AI read your request as:
          </div>
          <div>{chips.length ? chips.map((c) => <span key={c} className="chip">{c}</span>) : <span className="dim small">no filters, so every lot</span>}</div>
          {f.not_understood.length > 0 && (
            <div className="dim small">
              Couldn’t use: {f.not_understood.map((x) => `“${x}”`).join(', ')}. The map has no data for that yet.
            </div>
          )}
          <button className="ghost-btn sm" onClick={onClear}>
            Clear AI search
          </button>
        </div>
      )}
    </div>
  )
}
