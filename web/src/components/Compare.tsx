import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { rankOrder, rankingFlip, scores, smaa } from '../lib/scoring'
import type { Analysis, Config, Explanation, Scenario } from '../types'
import { CarbonChart } from './CarbonChart'
import { MetricRow } from './MetricView'
import { FlipSentence, SmaaBars, WeightsPanel } from './Weights'

interface Props {
  config: Config
  analysis: Analysis
  weights: Record<string, number>
  profileId: string | null
  onWeights: (w: Record<string, number>, profileId: string | null) => void
}

export function useRanking(config: Config, analysis: Analysis, weights: Record<string, number>) {
  return useMemo(() => {
    const crit = config.criteria
    const sc = analysis.scenarios
    const ids = sc.map((s) => s.typology_id)
    const pick = (k: 'value' | 'low' | 'high') => sc.map((s) => crit.map((c) => s.metrics[c.metric_id][k]))
    const hib = crit.map((c) => c.direction === 'higher_is_better')
    const w = crit.map((c) => weights[c.id] ?? 0)
    const s = scores(pick('value'), hib, w)
    const order = rankOrder(s).map((i) => ids[i])
    const accM = smaa({
      value: pick('value'),
      low: pick('low'),
      high: pick('high'),
      higherIsBetter: hib,
      samples: config.app.smaa.samples,
      seed: config.app.smaa.seed,
      center: w,
      concentration: config.app.smaa.profile_concentration,
    })
    const acc = Object.fromEntries(ids.map((id, i) => [id, accM[i]]))
    const flip = rankingFlip(pick('value'), hib, w)
    return { ids, order, acc, flip, scores: Object.fromEntries(ids.map((id, i) => [id, s[i]])) }
  }, [config, analysis, weights])
}

export function Compare({ config, analysis, weights, profileId, onWeights }: Props) {
  const labels = Object.fromEntries(config.typologies.map((t) => [t.id, t.label]))
  const { ids, order, acc, flip, scores: sc } = useRanking(config, analysis, weights)
  const byId = Object.fromEntries(analysis.scenarios.map((s) => [s.typology_id, s]))
  const [expl, setExpl] = useState<Explanation | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => setExpl(null), [analysis, weights])

  // Shared domain per metric so range bars compare across cards.
  const domains = useMemo(() => {
    const d: Record<string, [number, number]> = {}
    for (const c of config.criteria) {
      const ms = analysis.scenarios.map((s) => s.metrics[c.metric_id])
      d[c.metric_id] = [Math.min(0, ...ms.map((m) => m.low)), Math.max(...ms.map((m) => m.high))]
    }
    return d
  }, [config, analysis])

  const p = analysis.parcel
  return (
    <div className="compare">
      <header className="lot-header">
        <h2>{p.address || p.id}</h2>
        <p className="muted">
          {p.neighborhood} · zoning district <strong>{p.zoning ?? 'unknown'}</strong> ·{' '}
          {Math.round(p.lot_area_sf ?? 0).toLocaleString()} sf · parcel {p.id}
          {p.public ? <span className="badge">publicly held</span> : null}
        </p>
        {analysis.placeholder_count > 0 && (
          <p className="placeholder-banner small">
            {analysis.placeholder_count} values on this page are placeholders. {config.app.placeholder_notice}
          </p>
        )}
      </header>

      <section className="site-context">
        <h3>About this lot</h3>
        <div className="grid-3">
          {analysis.site_context.map((m) => (
            <MetricRow key={m.id} m={m} />
          ))}
        </div>
      </section>

      <div className="values-and-ranking">
        <WeightsPanel config={config} weights={weights} profileId={profileId} onWeights={onWeights} />
        <div className="ranking">
          <h3>Ranking under these priorities</h3>
          <ol className="rank-list">
            {order.map((id) => (
              <li key={id}>
                <span className="swatch" style={{ background: config.typologies.find((t) => t.id === id)?.color }} />
                {labels[id]} <span className="muted small">score {sc[id].toFixed(2)}</span>
              </li>
            ))}
          </ol>
          <FlipSentence flip={flip} config={config} labels={labels} ids={ids} />
          <SmaaBars config={config} order={order} acc={acc} labels={labels} />
          <div className="explain">
            <button
              className="explain-btn"
              disabled={loading}
              onClick={() => {
                setLoading(true)
                api
                  .explain(p.id, weights, order)
                  .then(setExpl)
                  .finally(() => setLoading(false))
              }}
            >
              {loading ? 'Explaining…' : 'Explain these tradeoffs'}
            </button>
            {expl && <ExplanationView config={config} expl={expl} labels={labels} />}
          </div>
        </div>
      </div>

      <section>
        <h3>The options, side by side</h3>
        <div className="cards">
          {order.map((id) => (
            <ScenarioCard key={id} config={config} s={byId[id]} domains={domains} />
          ))}
        </div>
      </section>

      <HouseholdTable config={config} analysis={analysis} order={order} labels={labels} />
      <CarbonChart config={config} scenarios={order.map((id) => byId[id])} />
    </div>
  )
}

function ScenarioCard({ config, s, domains }: { config: Config; s: Scenario; domains: Record<string, [number, number]> }) {
  const t = config.typologies.find((x) => x.id === s.typology_id)!
  const z = s.zoning
  return (
    <article className="card" style={{ borderTopColor: t.color }}>
      <h4>{t.label}</h4>
      <p className="small muted">
        {s.units} {s.units === 1 ? 'home' : 'homes'} · {t.stories} stories · usually {t.tenure_default}-occupied
        {t.supports_senior ? ' · can be senior / accessible housing' : ''}
      </p>
      <div className={`zoning zoning-${z.status}`}>
        <strong>{z.status_label}</strong>
        {z.use_citation && <span className="cite"> — {z.use_citation}</span>}
        {z.use_quote && <blockquote>“{z.use_quote}”</blockquote>}
        {z.checks.map((c) => (
          <div key={c.rule_id} className={`check ${c.passed ? 'pass' : 'fail'}`}>
            {c.passed ? '✓' : '✗'} {c.label}: needs {c.required.toLocaleString()} {c.unit}, has {c.actual.toLocaleString()}
            {c.citation && <span className="cite"> ({c.citation})</span>}
          </div>
        ))}
        {z.note && <div className="small muted">{z.note}</div>}
      </div>
      <div className="receipt">
        {config.criteria.map((c) => (
          <MetricRow key={c.id} m={s.metrics[c.metric_id]} label={c.label} domain={domains[c.metric_id]} />
        ))}
      </div>
      {s.notes.length > 0 && (
        <ul className="notes small">
          {s.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </article>
  )
}

function HouseholdTable({
  config,
  analysis,
  order,
  labels,
}: {
  config: Config
  analysis: Analysis
  order: string[]
  labels: Record<string, string>
}) {
  const byId = Object.fromEntries(analysis.scenarios.map((s) => [s.typology_id, s]))
  const icon = { yes: '●', maybe: '◐', no: '○' }
  const word = { yes: 'Yes', maybe: 'Maybe', no: 'No' }
  return (
    <section className="households">
      <h3>Could this household afford it?</h3>
      <p className="small muted">
        Illustrative households, not real people. “Yes” = affordable at 30% of income across the whole cost range;
        “Maybe” = only at the low end; “No” = not without subsidy.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Household</th>
              {order.map((id) => (
                <th key={id}>{labels[id]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {config.households.households.map((h, hi) => (
              <tr key={h.id}>
                <td>
                  <strong>{h.label}</strong>
                  <div className="small muted">
                    {h.ami_pct}% of area median · {h.size} {h.size === 1 ? 'person' : 'people'} ·{' '}
                    {config.households.destinations[h.destination]?.label}
                  </div>
                </td>
                {order.map((id) => {
                  const c = byId[id].households[hi]
                  return (
                    <td key={id} className={`verdict v-${c.verdict} prov-${c.cost_monthly.provenance}`}>
                      <span className="v-icon">{icon[c.verdict]}</span> {word[c.verdict]}
                      <div className="small muted">
                        can pay ${c.affordable_monthly.toLocaleString()}/mo vs ${Math.round(c.cost_monthly.value).toLocaleString()}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small muted">Commute times for these households are not modeled yet (PRT travel-time matrix pending).</p>
    </section>
  )
}

function ExplanationView({ config, expl, labels }: { config: Config; expl: Explanation; labels: Record<string, string> }) {
  const crit = Object.fromEntries(config.criteria.map((c) => [c.metric_id, c.label]))
  const chip = (id: string) => {
    const [t, m] = id.split(':')
    return `${labels[t] ?? t} · ${crit[m] ?? m}`
  }
  return (
    <div className="explanation">
      <p className="small muted">
        {expl.source === 'template'
          ? `Plain template (${expl.reason ?? 'no model'}). Every sentence cites the numbers it uses.`
          : `Written by ${expl.source}, then checked: every sentence cites metric IDs from this page and uses only these numbers.`}
      </p>
      {expl.sentences.map((s, i) => (
        <p key={i}>
          {s.text}{' '}
          {s.metric_ids.map((id) => (
            <span key={id} className="metric-chip">
              {chip(id)}
            </span>
          ))}
        </p>
      ))}
    </div>
  )
}
