import { useEffect, useState } from 'react'
import { api } from '../api'
import { PLAN_ID, type Crossing, type Option, type Ranking, type SetbackEnvelope } from '../lib/plan'
import type { Placement } from '../three/engine'
import type { Analysis, Config, EvidenceLeads, Explanation, Unknowns, WorkBackwardsResult } from '../types'
import { ROLE_COLOR, roleOf, usd } from '../lib/format'
import { AskLot, Dots, TypedSentences } from './ai'
import { HelpTip } from './help'
import { NextStepsTab } from './NextSteps'
import { MetricBox, ProvTag, SourceRefs } from './ui'

export type Tab = 'compare' | 'next' | 'priorities' | 'households' | 'emissions' | 'backwards' | 'unknowns'
const TABS: [Tab, string][] = [
  ['compare', 'Compare'],
  ['next', 'Next steps'],
  ['priorities', 'Whose priorities?'],
  ['households', 'Households'],
  ['emissions', 'Carbon'],
  ['backwards', 'Work backwards'],
  ['unknowns', 'What we don’t know'],
]

interface Props {
  config: Config
  L: Record<string, string>
  analysis: Analysis
  pool: Option[]
  ranking: Ranking
  weights: Record<string, number>
  profileId: string | null
  onWeights: (w: Record<string, number>, pid: string | null) => void
  tab: Tab
  setTab: (t: Tab) => void
  year: number
  setYear: (y: number) => void
  wb: { typ: string; units: number; ami: number }
  setWb: (w: { typ: string; units: number; ami: number }) => void
  onPlace: (list: Placement[]) => void
  envelope: SetbackEnvelope | null
  crossings: Crossing[]
}

export function AnalysisPanel(p: Props) {
  const { L } = p
  return (
    <section className="panel" style={{ top: L.pTop, right: L.pRight, bottom: L.pBottom, left: L.pLeft, width: L.pWidth, height: L.pHeight, borderRadius: L.pRadius }}>
      <div className="tabs" data-tour="tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={`tab-${id} ${p.tab === id ? 'on' : ''}`} onClick={() => p.setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      <div className="panel-body">
        {p.tab === 'compare' && <CompareTab {...p} />}
        {p.tab === 'next' && (
          <NextStepsTab
            config={p.config}
            analysis={p.analysis}
            ranking={p.ranking}
            profileLabel={p.config.stakeholders.profiles.find((x) => x.id === p.profileId)?.label ?? 'Custom'}
          />
        )}
        {p.tab === 'priorities' && <Priorities {...p} />}
        {p.tab === 'households' && <Households {...p} />}
        {p.tab === 'emissions' && <Carbon {...p} />}
        {p.tab === 'backwards' && <Backwards {...p} />}
        {p.tab === 'unknowns' && <UnknownsTab config={p.config} />}
      </div>
    </section>
  )
}

function Presets({ config, profileId, onWeights }: Pick<Props, 'config' | 'profileId' | 'onWeights'>) {
  return (
    <div className="presets" data-tour="presets">
      {config.stakeholders.profiles.map((pr) => (
        <button key={pr.id} className={pr.id === profileId ? 'on' : ''} onClick={() => onWeights({ ...pr.weights }, pr.id)}>
          {pr.label}
        </button>
      ))}
    </div>
  )
}

function CompareTab(p: Props) {
  const { config, analysis, ranking, pool } = p
  const plan = pool.find((o) => o.id === PLAN_ID) ?? null
  const par = analysis.parcel
  const [expl, setExpl] = useState<Explanation | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => setExpl(null), [analysis, p.weights])
  const scored = [...ranking.ranked, ...(plan && !plan.eligible ? [plan] : [])]
  const domains: Record<string, [number, number]> = {}
  for (const c of config.criteria) {
    const ms = scored.map((o) => o.metrics[c.metric_id])
    if (ms.length) domains[c.metric_id] = [Math.min(0, ...ms.map((m) => m.low)), Math.max(1e-6, ...ms.map((m) => m.high))]
  }
  const f = ranking.flip
  const crit = f ? config.criteria[f.criterionIndex] : null
  const labelOf = (id: string) => pool.find((o) => o.id === id)?.label ?? id
  const rankedIds = ranking.ranked.filter((o) => !o.isPlan).map((o) => o.id)
  // "typology:metric" -> "Duplex · Income needed to afford a home"
  const chip = (id: string) => {
    const [t, m] = id.split(':')
    const metricLabel =
      config.criteria.find((c) => c.metric_id === m)?.label ?? analysis.scenarios.find((s) => s.typology_id === t)?.metrics[m]?.label ?? m
    return `${config.typologies.find((x) => x.id === t)?.short_label ?? t} · ${metricLabel}`
  }
  const z = plan?.zoning
  const zRole = z ? roleOf(config, z.status) : 'unreviewed'
  const sitePlaceholderCount = analysis.site_context.filter((m) => m.provenance === 'placeholder').length
    + analysis.site_facts.filter((f) => f.provenance === 'placeholder').length
  const scenarioPlaceholderCount = analysis.scenarios.reduce((count, s) =>
    count + Object.values(s.metrics).filter((m) => m.provenance === 'placeholder').length, 0)

  return (
    <div className="compare-grid">
      <div className="col">
        <div>
          <div className="h-lot">{par.address || par.id}</div>
          <div className="muted small lot-meta">
            <span>
              {par.neighborhood} · zoning district <strong>{par.zoning ?? '—'}</strong> · {Math.round(par.lot_area_sf ?? 0).toLocaleString()} sf · parcel {par.id}
            </span>
            {par.public && <span className="pub-badge">publicly held</span>}
          </div>
          <div className="dim small">
            Confirm this lot against{' '}
            {config.city.zoning_links.map((id, index) => {
              const source = config.sources.sources[id]
              return source?.url ? <span key={id}>{index > 0 ? ' · ' : ''}<a href={source.url} target="_blank" rel="noreferrer">{source.name}</a></span> : null
            })}
            {typeof par.zoning_code_url === 'string' && par.zoning_code_url && <span> · <a href={par.zoning_code_url} target="_blank" rel="noreferrer">district code section</a></span>}
            . The mapped base district does not establish what can be built.
          </div>
          {analysis.placeholder_count > 0 && (
            <div className="hatched note-box small">
              {analysis.placeholder_count} displayed values depend on placeholders: {sitePlaceholderCount} site values
              {' '}and {scenarioPlaceholderCount} results across {analysis.scenarios.length} housing types.
              {' '}Several results reuse the same unsourced inputs. Rankings are provisional.
              {' '}{config.app.placeholder_notice}
            </div>
          )}
        </div>
        <div className="h-sec">Your plan<HelpTip id="your_plan" /></div>
        {!plan ? (
          <div className="empty-box">Nothing placed yet. Drag a building from the palette, or place one of the ranked options.</div>
        ) : (
          <>
            <div className="zone-box" style={{ borderColor: ROLE_COLOR[zRole], borderStyle: z!.reviewed ? 'solid' : 'dashed' }}>
              <div className="zone-head">
                <strong style={{ color: ROLE_COLOR[zRole] }}>{z!.status_label}</strong>
                <span className="eyebrow">Title Nine</span>
              </div>
              {!z!.reviewed && <div className="muted small">{z!.note ?? `No zoning rules for ${par.zoning} yet.`} No approval path is claimed.</div>}
              {z!.reviewed && !z!.human_reviewed && <div className="muted small">AI-extracted from Title Nine with a verbatim quote; not checked by a planner.</div>}
              {Object.entries(plan.zoningByType ?? {}).map(([tid, zt]) => (
                <div key={tid} className="small" style={{ color: zt.disqualified ? '#ff7a5c' : '#c5d0d8' }}>
                  {zt.disqualified ? '✗' : '·'} {config.typologies.find((t) => t.id === tid)?.short_label} use: {zt.status_label}
                  {zt.use_citation && <span className="dim"> ({zt.use_citation})</span>}
                </div>
              ))}
              {p.envelope && (
                <div className="small" style={{ color: p.crossings.length ? '#ff7a45' : '#c9dcf0' }}>
                  {p.crossings.length ? '✗' : '✓'} Setbacks: front {p.envelope.front} ft, rear {p.envelope.rear} ft, sides{' '}
                  {p.envelope.left === p.envelope.right ? `${p.envelope.left} ft` : `${p.envelope.left} / ${p.envelope.right} ft`}
                  {p.crossings.length > 0 &&
                    ` — ${p.crossings.length} building${p.crossings.length > 1 ? 's cross' : ' crosses'} the ${[...new Set(p.crossings.flatMap((c) => c.sides))].join(' and ')} setback`}
                  {p.envelope.citation && <span className="dim"> ({p.envelope.citation})</span>}
                </div>
              )}
              {z!.checks.map((c) => (
                <div key={c.rule_id} className="small" style={{ color: c.passed ? '#c5d0d8' : '#ff7a5c' }}>
                  {c.passed ? '✓' : '✗'} {c.label}: needs {c.required.toLocaleString()} {c.unit}, has {c.actual.toLocaleString()}
                  {c.citation && <span className="dim"> ({c.citation})</span>}
                </div>
              ))}
            </div>
            {!plan.eligible && <div className="warn small">Excluded from the ranking: {plan.reason}. A prohibited use can’t be outweighed by other priorities.</div>}
            <div className="col tight">
              {config.criteria.map((c) => (
                <MetricBox key={c.id} m={plan.metrics[c.metric_id]} label={c.label} question={c.question} domain={domains[c.metric_id]} />
              ))}
            </div>
            {plan.notes.map((n) => (
              <div key={n} className="dim small">
                {n}
              </div>
            ))}
          </>
        )}
      </div>

      <div className="col">
        <Presets {...p} />
        <div className="h-sec">Ranking under these priorities<HelpTip id="ranking" /></div>
        <div className="col tight">
          {ranking.ranked.map((o, i) => (
            <div key={o.id} className={`rank-row ${o.isPlan ? 'mine' : ''}`}>
              <span className={`medal m${Math.min(i, 3)}`}>{i + 1}</span>
              <span className="swatch" style={{ background: o.color }} />
              <span className="rank-label">
                {o.label} <span className="dim small">· {o.units} homes</span>
              </span>
              <span className="rank-score">{ranking.score[o.id].toFixed(2)}</span>
              {o.isPlan ? <span className="yours">yours</span> : <button className="go-btn sm" onClick={() => o.placements && p.onPlace(o.placements)}>Place</button>}
            </div>
          ))}
          {ranking.ranked.length === 0 && (
            <div className="warn small">
              No housing type fits this lot on its own. At {Math.round(analysis.lot_shape.frontage_ft)} × {Math.round(analysis.lot_shape.depth_ft)} ft,
              every one of the {config.typologies.length} forms screened here needs more frontage, depth or lot area than this parcel has.
              Parcels this small are usually built on together with a neighboring lot; combining parcels is not modeled here.
            </div>
          )}
          {ranking.notFitting.length > 0 && <div className="dim small">Doesn’t fit this lot: {ranking.notFitting.map((o) => o.label).join(', ')}</div>}
          {ranking.excluded.length > 0 && (
            <div className="warn small">
              Not ranked (hard requirement): {ranking.excluded.map((o) => `${o.label} — ${o.reason}${o.zoning?.human_reviewed ? '' : ' (AI-extracted rule, not checked by a planner)'}`).join('; ')}
            </div>
          )}
        </div>
        <div className="flip-box">
          {f && crit
            ? `${labelOf(f.challengerId)} would overtake ${labelOf(f.winnerId)} if the weight on ${crit.label.toLowerCase()} ${f.delta > 0 ? 'rose' : 'fell'} from ${Math.round(f.from * 100)}% to ${Math.round(f.to * 100)}% of the total.`
            : ranking.ranked.length > 1
              ? 'No single-weight change flips the top two here — the leader wins across every weighting of one criterion.'
              : ranking.ranked.length === 1
                ? 'Only one option can be ranked on this lot.'
                : 'No option can be ranked on this lot, so there is nothing to flip.'}
          <HelpTip id="flip" />
        </div>
        {ranking.ranked.length > 0 && (
          <>
            <div className="h-sec">How often does each option come out on top?<HelpTip id="smaa" /></div>
            <div className="dim small">
              {config.app.smaa.samples.toLocaleString()} runs, each with different weights near your current priorities and every value drawn from its uncertainty range. Darker = better rank.
            </div>
          </>
        )}
        <div className="col tight">
          {ranking.ranked.map((o) => (
            <div key={o.id} className="smaa-row">
              <span className="ellipsis">{o.short}</span>
              <div className="smaa-bar">
                {(ranking.acc[o.id] ?? []).map((a, r) => (
                  <div key={r} title={`Rank ${r + 1}: ${Math.round(a * 100)}% of runs`} style={{ width: `${a * 100}%`, opacity: 1 - (r / Math.max(ranking.ranked.length - 1, 1)) * 0.85 }} />
                ))}
              </div>
              <span className="smaa-first">{Math.round((ranking.acc[o.id]?.[0] ?? 0) * 100)}% first</span>
            </div>
          ))}
        </div>
        <div>
          <button
            className="go-btn"
            disabled={loading}
            aria-busy={loading}
            onClick={() => {
              setLoading(true)
              api
                .explain(par.id, p.weights, rankedIds)
                .then(setExpl)
                .finally(() => setLoading(false))
            }}
          >
            {loading ? (
              <>
                Explaining
                <Dots />
              </>
            ) : (
              'Explain these tradeoffs with AI'
            )}
          </button>
          {expl && (
            <div className="expl">
              <div className="dim small">
                {expl.source === 'template'
                  ? `Plain template (${expl.reason ?? 'no model'}).`
                  : `Written by ${expl.source}, then checked against the numbers on this page.`}{' '}
                Covers the ranked building types; every sentence cites the metrics it uses.
              </div>
              <TypedSentences key={expl.sentences.map((s) => s.text).join('|')} sentences={expl.sentences} chip={chip} />
            </div>
          )}
          <div className="h-sec">Ask about this lot<HelpTip id="ask" /></div>
          <AskLot
            key={par.id}
            parcelId={par.id}
            weights={p.weights}
            ranking={rankedIds}
            examples={config.app.ask.examples}
            maxChars={config.app.api.ask_question_max_chars}
            chip={chip}
          />
        </div>
        <div className="h-sec">About this lot<HelpTip id="about_lot" /></div>
        <div className="ctx-grid">
          <div className={`mbox prov-${analysis.lot_shape.provenance}`}>
            <div className="mbox-head">
              <span className="mbox-label">Frontage × depth</span>
              <ProvTag p={analysis.lot_shape.provenance} />
            </div>
            <strong>
              {Math.round(analysis.lot_shape.frontage_ft)} × {Math.round(analysis.lot_shape.depth_ft)} ft
            </strong>
            <div className="dim small">{analysis.lot_shape.note}</div>
          </div>
          {analysis.site_context.map((m) => <MetricBox key={m.id} m={m} sources={config.sources.sources} />)}
          {analysis.site_facts.map((fact) => (
            <div key={fact.id} className={`mbox prov-${fact.provenance}`}>
              <div className="mbox-head"><span className="mbox-label">{fact.label}</span><ProvTag p={fact.provenance} /></div>
              <strong>{fact.value}</strong>
              <div className="dim small">{fact.note}</div>
              <SourceRefs ids={fact.sourceIds} sources={config.sources.sources} provenance={fact.provenance} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Priorities(p: Props) {
  const { config, weights } = p
  const tot = config.criteria.reduce((a, c) => a + (weights[c.id] ?? 0), 0) || 1
  return (
    <div className="values-box">
      <div className="h-values">Whose priorities?<HelpTip id="priorities" /></div>
      <p className="muted small">These are values, not evidence. Pick a starting point or move the sliders — the evidence doesn’t change, only how it’s weighed. Presets are illustrative, not positions of real organizations.</p>
      <Presets {...p} />
      <div className="col">
        {config.criteria.map((c) => (
          <label key={c.id} className="weight-row" title={c.question}>
            <span>{c.label}</span>
            <input type="range" min={0} max={3} step={0.25} value={weights[c.id] ?? 0} onChange={(e) => p.onWeights({ ...weights, [c.id]: Number(e.target.value) }, null)} />
            <span className="weight-share">{Math.round(((weights[c.id] ?? 0) / tot) * 100)}%</span>
          </label>
        ))}
      </div>
    </div>
  )
}

function Households({ config, pool }: Props) {
  const cols = pool.filter((o) => o.fits)
  const plan = cols.find((o) => o.isPlan)
  const ordered = plan ? [plan, ...cols.filter((o) => !o.isPlan)] : cols
  const V = { yes: ['●', 'Yes', '#2fd06b'], maybe: ['◐', 'Maybe', '#ffb800'], no: ['○', 'No', '#ff7a45'] } as const
  return (
    <div>
      <div className="h-tab">Could this household afford it?<HelpTip id="households" /></div>
      <p className="muted small">Illustrative households, not real people. “Yes” = affordable at 30% of income across the whole cost range; “Maybe” = only at the low end; “No” = not without subsidy.</p>
      <div className="table-wrap">
        <table className="dtable">
          <thead>
            <tr>
              <th>Household</th>
              {ordered.map((o) => (
                <th key={o.id} style={{ borderTop: `3px solid ${o.color}` }}>
                  {o.short}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {config.households.households.map((h, hi) => (
              <tr key={h.id}>
                <td>
                  <strong>{h.label}</strong>
                  <div className="dim small">
                    {h.ami_pct}% of area median · {h.size} {h.size === 1 ? 'person' : 'people'} · {config.households.destinations[h.destination]?.label}
                  </div>
                </td>
                {ordered.map((o) => {
                  const c = o.households[hi]
                  const v = V[c.verdict]
                  return (
                    <td key={o.id} className={`prov-${c.cost_monthly.provenance}`}>
                      <span style={{ color: v[2] }}>{v[0]}</span> {v[1]}
                      <div className="dim small">
                        can pay {usd(c.affordable_monthly)}/mo vs {usd(c.cost_monthly.value)}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="dim small">Commute times for these households are not modeled yet (PRT travel-time matrix pending).</p>
    </div>
  )
}

function Carbon({ pool, year, setYear, config }: Props) {
  const lines = pool.filter((o) => o.fits)
  const n = lines[0]?.carbon.value.length ?? 1
  const last = n - 1
  const vmax = Math.max(10, ...lines.map((l) => l.carbon.value[last])) * 1.08
  const X = (y: number) => 40 + (y / Math.max(last, 1)) * 312
  const Y = (v: number) => 10 + (1 - v / vmax) * 164
  const prov = lines.some((l) => l.carbon.provenance === 'placeholder') ? 'placeholder' : (lines[0]?.carbon.provenance ?? 'placeholder')
  const crossovers: string[] = []
  const pure = lines.filter((l) => !l.isPlan)
  for (let a = 0; a < pure.length; a++)
    for (let b = a + 1; b < pure.length; b++) {
      const A = pure[a].carbon.value
      const B = pure[b].carbon.value
      const s0 = Math.sign(A[0] - B[0])
      const k = A.findIndex((x, i) => i > 0 && Math.sign(x - B[i]) !== s0 && Math.sign(x - B[i]) !== 0)
      if (s0 !== 0 && k > 0) {
        const [hi, lo] = s0 > 0 ? [pure[a], pure[b]] : [pure[b], pure[a]]
        crossovers.push(`${hi.label} starts higher (more embodied carbon) but drops below ${lo.label} by year ${k}.`)
      }
    }
  const y = Math.min(year, last)
  void config
  return (
    <div>
      <div className="row-between">
        <div className="h-tab">Carbon per household over time<HelpTip id="carbon_over_time" /></div>
        <ProvTag p={prov} />
      </div>
      <p className="muted small">Building materials at year 0, then home energy (PA grid, decarbonizing) and travel each year. Tonnes CO₂e.</p>
      <div className="carbon-grid">
        <div>
          <svg viewBox="0 0 360 200" className={`chart prov-${prov}`}>
            {[0, 0.25, 0.5, 0.75, 1].map((k) => (
              <g key={k}>
                <line x1={40} x2={352} y1={Y(vmax * k)} y2={Y(vmax * k)} stroke="#1f3a5a" strokeDasharray="2 4" />
                <text x={34} y={Y(vmax * k) + 3} fill="#7d9cc0" fontSize={9} textAnchor="end" fontFamily="Fredoka">
                  {Math.round(vmax * k)}
                </text>
              </g>
            ))}
            {[0, Math.round(last / 3), Math.round((2 * last) / 3), last].map((t, i) => (
              <text key={i} x={X(t)} y={190} fill="#7d9cc0" fontSize={9} textAnchor="middle" fontFamily="Fredoka">
                yr {t}
              </text>
            ))}
            {lines.map((l) => (
              <path
                key={l.id}
                d={l.carbon.value.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('')}
                fill="none"
                stroke={l.isPlan ? '#2fd06b' : l.color}
                strokeWidth={l.isPlan ? 3 : 1.6}
                strokeDasharray={l.isPlan ? undefined : '5 3'}
              />
            ))}
            <line x1={X(y)} x2={X(y)} y1={8} y2={176} stroke="#2fd06b" strokeWidth={1} />
          </svg>
          <label className="year-row">
            <span>
              Year <strong className="num">{y}</strong>
            </span>
            <input type="range" className="lime-range" min={0} max={last} step={1} value={y} onChange={(e) => setYear(Number(e.target.value))} />
          </label>
        </div>
        <div className="col tight">
          <div className="eyebrow">Cumulative at year {y}</div>
          {[...lines]
            .sort((a, b) => a.carbon.value[y] - b.carbon.value[y])
            .map((l) => (
              <div key={l.id} className="read-row">
                <span className="line-key" style={{ background: l.isPlan ? '#2fd06b' : l.color }} />
                <span className="grow">{l.label}</span>
                <span className="num">{Math.round(l.carbon.value[y])} t</span>
              </div>
            ))}
          {crossovers.slice(0, 4).map((c) => (
            <div key={c} className="muted small">
              {c}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Backwards({ config, analysis, wb, setWb }: Props) {
  const [res, setRes] = useState<WorkBackwardsResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (!wb.typ) return
    const t = setTimeout(() => {
      api
        .workBackwards(analysis.parcel.id, wb.typ, wb.units, wb.ami)
        .then((r) => {
          setRes(r)
          setErr(null)
        })
        .catch((e: Error) => setErr(e.message))
    }, 150)
    return () => clearTimeout(t)
  }, [analysis, wb])
  const scen = analysis.scenarios.find((s) => s.typology_id === wb.typ)
  const role = res ? roleOf(config, res.zoning.status) : 'unreviewed'
  return (
    <div>
      <div className="h-tab">Work backwards<HelpTip id="backwards" /></div>
      <p className="muted small">Pick a target. See what would have to change on this lot to get there.</p>
      <div className="wb-controls">
        <label>
          Housing type
          <select
            className="field-sm"
            value={wb.typ}
            onChange={(e) => {
              const s = analysis.scenarios.find((x) => x.typology_id === e.target.value)
              setWb({ ...wb, typ: e.target.value, units: s?.units ?? 1 })
            }}
          >
            {config.typologies.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Homes
          <input className="field-sm num-in" type="number" min={1} max={500} value={wb.units} onChange={(e) => setWb({ ...wb, units: Math.max(1, Number(e.target.value) || 1) })} />
        </label>
        <label className="wide">
          Affordable to households at {wb.ami}% of area median
          <input type="range" className="lime-range" min={30} max={120} step={10} value={wb.ami} onChange={(e) => setWb({ ...wb, ami: Number(e.target.value) })} />
        </label>
      </div>
      {err && <div className="warn">{err}</div>}
      {res && (
        <div className="wb-grid">
          <div className="card-box">
            <div className="h-card">Zoning</div>
            <p>
              <strong style={{ color: ROLE_COLOR[role] }}>{res.zoning_path}</strong>
              {res.zoning.use_citation && <span className="dim"> — {res.zoning.use_citation}</span>}
            </p>
            {res.failed_rules.map((c) => (
              <div key={c.rule_id} className="warn small">
                {c.label}: needs {c.required.toLocaleString()} {c.unit}, has {c.actual.toLocaleString()} → variance or special exception {c.citation ? `(${c.citation})` : ''}
              </div>
            ))}
            {!res.failed_rules.length && <div className="dim small">{res.zoning.note ?? 'No dimensional rule fails.'}</div>}
            {scen && !scen.form_fits && <div className="warn small">This building form doesn’t physically fit the lot.</div>}
          </div>
          <div className={`card-box prov-${res.subsidy_per_unit.provenance}`}>
            <div className="row-between">
              <div className="h-card">Subsidy gap per home</div>
              <ProvTag p={res.subsidy_per_unit.provenance} />
            </div>
            <div className="big-num">
              {usd(res.subsidy_per_unit.value)} <span className="dim small">(range {usd(res.subsidy_per_unit.low)}–{usd(res.subsidy_per_unit.high)})</span>
            </div>
            <div className="muted small">{res.note}</div>
          </div>
          <div className="card-box">
            <div className="h-card">Site and infrastructure</div>
            {res.infrastructure_flags.map((f) => (
              <div key={f} className="small">
                {f} — expect added engineering and cost; confirm with a site survey.
              </div>
            ))}
            {!res.infrastructure_flags.length && <div className="dim small">No slope, landslide or undermining flag at this lot’s centroid.</div>}
          </div>
        </div>
      )}
    </div>
  )
}

function UnknownsTab({ config }: Pick<Props, 'config'>) {
  const topics = Object.entries(config.app.evidence.topics).filter(([, t]) => t.listed)
  const [u, setU] = useState<Unknowns | null>(null)
  const [evidence, setEvidence] = useState<EvidenceLeads | null>(null)
  const [evidenceError, setEvidenceError] = useState(false)
  const [topic, setTopic] = useState(topics[0]?.[0] ?? '')
  const [evidencePage, setEvidencePage] = useState(0)
  useEffect(() => {
    api.unknowns().then(setU)
  }, [])
  useEffect(() => {
    let cancelled = false
    api.evidence(topic, evidencePage * 20).then((result) => {
      if (!cancelled) setEvidence((previous) => evidencePage === 0 ? result : {
        ...result, items: [...(previous?.items ?? []), ...result.items],
      })
    }).catch(() => { if (!cancelled) setEvidenceError(true) })
    return () => { cancelled = true }
  }, [topic, evidencePage])
  if (!u) return <div className="muted">Loading…</div>
  return (
    <div className="unknowns">
      <div className="h-tab">What we don’t know<HelpTip id="unknowns" /></div>
      <p className="muted">
        This tool is decision support. Here is everything it is not yet sure about. Values marked <ProvTag p="placeholder" /> are stand-ins that show how the tool works — not facts about Pittsburgh.
      </p>
      <div className="h-card">Zoning rules</div>
      <p className="small">
        {Math.round(u.share_covered_by_rules * 100)}% of the city’s {u.vacant_parcels.toLocaleString()} vacant lots are in a district with zoning rules
        {u.require_human_review ? ' a person has reviewed.' : `; ${Math.round(u.share_covered_by_human_reviewed_rules * 100)}% by rules a person has checked. The rest were extracted by AI from the code text, each with a verbatim quote, and are labelled that way.`}
        {' '}Lots in other districts show “Needs planner review.”
      </p>
      <details className="small">
        <summary>{u.uncovered_districts.length} districts with no rules yet (by vacant lots)</summary>
        <div className="columns">
          {u.uncovered_districts.map((d) => (
            <div key={d.district}>
              {d.district}: {d.vacant_parcels.toLocaleString()}
            </div>
          ))}
        </div>
      </details>
      <div className="h-card">Locally classified source passages</div>
      <p className="muted small">
        {evidence?.compiled
          ? `${evidence.passages} passages from ${evidence.documents} documents were classified locally with Laya before deployment. Only supplied files were indexed. These are leads to inspect, not a complete code review, reviewed zoning rules, or verified measurements.`
          : evidenceError ? 'The compiled source index could not be loaded.'
            : evidence ? 'No local Laya evidence index has been committed yet.'
              : 'Loading locally compiled sources…'}
      </p>
      {evidence?.compiled && <label className="small">
        Source topic{' '}
        <select value={topic} onChange={(event) => {
          setEvidence(null)
          setEvidenceError(false)
          setEvidencePage(0)
          setTopic(event.target.value)
        }}>
          {topics.map(([id, t]) => <option key={id} value={id}>{t.label}</option>)}
        </select>
      </label>}
      {evidence?.items.map((item) => (
        <div key={item.id} className="small unk-row">
          <strong>{item.source_name} · {item.document.split('/').pop()?.replace(/\.[^.]+$/, '').replaceAll('-', ' ')}{item.page ? `, page ${item.page}` : `, passage ${item.part}`}</strong>
          {item.source_url && <span> · <a href={item.source_url} target="_blank" rel="noreferrer">source</a></span>}
          <div className="muted">“{item.excerpt}”</div>
        </div>
      ))}
      {evidence?.compiled && evidence.items.length < evidence.total &&
        <button type="button" onClick={() => { setEvidenceError(false); setEvidencePage((page) => page + 1) }}>
          Show more source passages ({evidence.items.length} of {evidence.total})
        </button>}
      <div className="h-card">Coverage of connected data</div>
      <p className="muted small">Counts describe indexed vacant lots, not every property in Pittsburgh.</p>
      {([
        ['acs_income_values', '2024 ACS tract median income'],
        ['acs_renter_burden_values', '2024 ACS tract renter cost burden'],
        ['parcel_polygons_matched', 'County parcel boundaries'],
        ['fema_classified', 'Matched FEMA flood zones'],
        ['combined_sewershed_matched', 'Matched combined sewersheds'],
      ] as const).map(([key, label]) => (
        <div key={key} className="small unk-row">{label}: {(u.pipeline?.counts?.[key] ?? 0).toLocaleString()} of {u.vacant_parcels.toLocaleString()}</div>
      ))}
      <p className="muted small">ACS gaps include special-use tracts. FEMA is a point screen that can miss a hazard on another part of a lot. A missing sewershed match does not establish sewer type or available capacity.</p>
      <div className="h-card">Placeholder numbers ({u.placeholder_assumptions.length})</div>
      {u.placeholder_assumptions.map((a) => (
        <div key={a.id} className="small unk-row">
          <code>{a.id}</code> <span className="dim">({a.unit})</span> — {a.rationale}
        </div>
      ))}
      <div className="h-card">Data sources not connected yet ({u.unverified_sources.length})</div>
      {u.unverified_sources.map((s) => (
        <div key={s.id} className="small unk-row">
          {s.name}
          {s.note && <span className="muted"> — {s.note}</span>}
        </div>
      ))}
      <div className="h-card">Always true</div>
      {[
        'Slope, landslide and undermining flags use parcel centroids. FEMA uses a point inside the parcel boundary where available. These screens can miss a hazard on another part of a lot.',
        'Assessed land values are not market prices.',
        'The 3D city and the neighbors around a lot are stylized; lot positions and dimensions come from county records.',
        'City limits only — other Allegheny County municipalities have their own zoning codes.',
        'Households are illustrative; stakeholder presets are not positions of real organizations.',
      ].map((t) => (
        <div key={t} className="small unk-row muted">
          · {t}
        </div>
      ))}
    </div>
  )
}
