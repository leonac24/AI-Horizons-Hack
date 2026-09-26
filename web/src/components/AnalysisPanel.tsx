import { useEffect, useState } from 'react'
import { api } from '../api'
import { PLAN_ID, type Option, type Ranking } from '../lib/plan'
import type { Placement } from '../three/engine'
import type { Analysis, Config, Explanation, Unknowns, WorkBackwardsResult } from '../types'
import { fmt, ROLE_COLOR, roleOf, usd } from '../lib/format'
import { MetricBox, ProvTag } from './ui'

export type Tab = 'compare' | 'priorities' | 'households' | 'emissions' | 'backwards' | 'unknowns'
const TABS: [Tab, string][] = [
  ['compare', 'Compare'],
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
}

export function AnalysisPanel(p: Props) {
  const { L } = p
  return (
    <section className="panel" style={{ top: L.pTop, right: L.pRight, bottom: L.pBottom, left: L.pLeft, width: L.pWidth, height: L.pHeight, borderRadius: L.pRadius }}>
      <div className="tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={p.tab === id ? 'on' : ''} onClick={() => p.setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      <div className="panel-body">
        {p.tab === 'compare' && <CompareTab {...p} />}
        {p.tab === 'priorities' && <Priorities {...p} />}
        {p.tab === 'households' && <Households {...p} />}
        {p.tab === 'emissions' && <Carbon {...p} />}
        {p.tab === 'backwards' && <Backwards {...p} />}
        {p.tab === 'unknowns' && <UnknownsTab />}
      </div>
    </section>
  )
}

function Presets({ config, profileId, onWeights }: Pick<Props, 'config' | 'profileId' | 'onWeights'>) {
  return (
    <div className="presets">
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
  const z = plan?.zoning
  const zRole = z ? roleOf(config, z.status) : 'unreviewed'

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
          {analysis.placeholder_count > 0 && (
            <div className="hatched note-box small">
              {analysis.placeholder_count} values for this lot are placeholders. {config.app.placeholder_notice}
            </div>
          )}
        </div>
        <div className="h-sec">Your plan</div>
        {!plan ? (
          <div className="empty-box">Nothing placed yet. Drag a building from the palette, or place one of the ranked options.</div>
        ) : (
          <>
            <div className="zone-box" style={{ borderColor: ROLE_COLOR[zRole], borderStyle: z!.reviewed ? 'solid' : 'dashed' }}>
              <div className="zone-head">
                <strong style={{ color: ROLE_COLOR[zRole] }}>{z!.status_label}</strong>
                <span className="eyebrow">Title Nine</span>
              </div>
              {!z!.reviewed && <div className="muted small">Rules for {par.zoning} haven’t been extracted and reviewed by a person yet, so no approval path is claimed.</div>}
              {Object.entries(plan.zoningByType ?? {}).map(([tid, zt]) => (
                <div key={tid} className="small" style={{ color: zt.disqualified ? '#ff7a5c' : '#c5d0d8' }}>
                  {zt.disqualified ? '✗' : '·'} {config.typologies.find((t) => t.id === tid)?.short_label} use: {zt.status_label}
                  {zt.use_citation && <span className="dim"> ({zt.use_citation})</span>}
                </div>
              ))}
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
        <div className="h-sec">Ranking under these priorities</div>
        <div className="col tight">
          {ranking.ranked.map((o, i) => (
            <div key={o.id} className={`rank-row ${o.isPlan ? 'mine' : ''}`}>
              <span className="rank-n">{i + 1}</span>
              <span className="swatch" style={{ background: o.color }} />
              <span className="rank-label">
                {o.label} <span className="dim small">· {o.units} homes</span>
              </span>
              <span className="rank-score">{ranking.score[o.id].toFixed(2)}</span>
              {o.isPlan ? <span className="yours">yours</span> : <button className="place-btn" onClick={() => o.placements && p.onPlace(o.placements)}>Place</button>}
            </div>
          ))}
          {ranking.notFitting.length > 0 && <div className="dim small">Doesn’t fit this lot: {ranking.notFitting.map((o) => o.label).join(', ')}</div>}
          {ranking.excluded.length > 0 && (
            <div className="warn small">
              Not ranked (hard requirement): {ranking.excluded.map((o) => `${o.label} — ${o.reason}`).join('; ')}
            </div>
          )}
        </div>
        <div className="flip-box">
          {f && crit
            ? `${labelOf(f.challengerId)} would overtake ${labelOf(f.winnerId)} if the weight on ${crit.label.toLowerCase()} ${f.delta > 0 ? 'rose' : 'fell'} from ${Math.round(f.from * 100)}% to ${Math.round(f.to * 100)}% of the total.`
            : ranking.ranked.length > 1
              ? 'No single-weight change flips the top two here — the leader wins across every weighting of one criterion.'
              : 'Only one option can be ranked on this lot.'}
        </div>
        <div className="h-sec">How often does each option come out on top?</div>
        <div className="dim small">
          {config.app.smaa.samples.toLocaleString()} runs, each with different weights near your current priorities and every value drawn from its uncertainty range. Darker = better rank.
        </div>
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
            className="solid-btn"
            disabled={loading}
            onClick={() => {
              setLoading(true)
              api
                .explain(par.id, p.weights, ranking.ranked.filter((o) => !o.isPlan).map((o) => o.id))
                .then(setExpl)
                .finally(() => setLoading(false))
            }}
          >
            {loading ? 'Explaining…' : 'Explain these tradeoffs'}
          </button>
          {expl && (
            <div className="expl">
              <div className="dim small">
                {expl.source === 'template'
                  ? `Plain template (${expl.reason ?? 'no model'}).`
                  : `Written by ${expl.source}, then checked against the numbers on this page.`}{' '}
                Covers the ranked building types; every sentence cites the metrics it uses.
              </div>
              {expl.sentences.map((s, i) => (
                <p key={i}>
                  {s.text}{' '}
                  {s.metric_ids.map((id) => {
                    const [t, m] = id.split(':')
                    return (
                      <span key={id} className="chip">
                        {config.typologies.find((x) => x.id === t)?.short_label ?? t} · {config.criteria.find((c) => c.metric_id === m)?.label ?? m}
                      </span>
                    )
                  })}
                </p>
              ))}
            </div>
          )}
        </div>
        <div className="h-sec">About this lot</div>
        <div className="ctx-grid">
          <div className={`mbox prov-${analysis.lot_shape.provenance}`}>
            <div className="mbox-head">
              <span className="mbox-label">Frontage × depth</span>
              <ProvTag p={analysis.lot_shape.provenance} />
            </div>
            <strong>
              {Math.round(analysis.lot_shape.frontage_ft)} × {Math.round(analysis.lot_shape.depth_ft)} ft
            </strong>
          </div>
          {analysis.site_context.map((m) => (
            <div key={m.id} className={`mbox prov-${m.provenance}`} title={m.note ?? undefined}>
              <div className="mbox-head">
                <span className="mbox-label">{m.label}</span>
                <ProvTag p={m.provenance} />
              </div>
              <strong>{fmt(m.value, m.unit)}</strong>
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
      <div className="h-values">Whose priorities?</div>
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
  const V = { yes: ['●', 'Yes', '#5fd49a'], maybe: ['◐', 'Maybe', '#ffc53d'], no: ['○', 'No', '#ff7a5c'] } as const
  return (
    <div>
      <div className="h-tab">Could this household afford it?</div>
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
        <div className="h-tab">Carbon per household over time</div>
        <ProvTag p={prov} />
      </div>
      <p className="muted small">Building materials at year 0, then home energy (PA grid, decarbonizing) and travel each year. Tonnes CO₂e.</p>
      <div className="carbon-grid">
        <div>
          <svg viewBox="0 0 360 200" className={`chart prov-${prov}`}>
            {[0, 0.25, 0.5, 0.75, 1].map((k) => (
              <g key={k}>
                <line x1={40} x2={352} y1={Y(vmax * k)} y2={Y(vmax * k)} stroke="#212b34" strokeDasharray="2 4" />
                <text x={34} y={Y(vmax * k) + 3} fill="#6b7985" fontSize={9} textAnchor="end" fontFamily="Chakra Petch">
                  {Math.round(vmax * k)}
                </text>
              </g>
            ))}
            {[0, Math.round(last / 3), Math.round((2 * last) / 3), last].map((t) => (
              <text key={t} x={X(t)} y={190} fill="#6b7985" fontSize={9} textAnchor="middle" fontFamily="Chakra Petch">
                yr {t}
              </text>
            ))}
            {lines.map((l) => (
              <path
                key={l.id}
                d={l.carbon.value.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('')}
                fill="none"
                stroke={l.isPlan ? '#b6f23e' : lighten(l.color)}
                strokeWidth={l.isPlan ? 3 : 1.6}
                strokeDasharray={l.isPlan ? undefined : '5 3'}
              />
            ))}
            <line x1={X(y)} x2={X(y)} y1={8} y2={176} stroke="#b6f23e" strokeWidth={1} />
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
                <span className="line-key" style={{ background: l.isPlan ? '#b6f23e' : lighten(l.color) }} />
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

/** Dark typology colors disappear on the dark chart; lift them toward white. */
function lighten(hex: string): string {
  const n = parseInt(hex.slice(1), 16)
  const mix = (c: number) => Math.round(c + (255 - c) * 0.35)
  const r = mix((n >> 16) & 255)
  const g = mix((n >> 8) & 255)
  const b = mix(n & 255)
  return `rgb(${r},${g},${b})`
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
      <div className="h-tab">Work backwards</div>
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
            {!res.failed_rules.length && <div className="dim small">{res.zoning.note ?? 'No reviewed dimensional rule fails.'}</div>}
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

function UnknownsTab() {
  const [u, setU] = useState<Unknowns | null>(null)
  useEffect(() => {
    api.unknowns().then(setU)
  }, [])
  if (!u) return <div className="muted">Loading…</div>
  return (
    <div className="unknowns">
      <div className="h-tab">What we don’t know</div>
      <p className="muted">
        This tool is decision support. Here is everything it is not yet sure about. Values marked <ProvTag p="placeholder" /> are stand-ins that show how the tool works — not facts about Pittsburgh.
      </p>
      <div className="h-card">Zoning rules</div>
      <p className="small">
        {Math.round(u.share_covered_by_reviewed_rules * 100)}% of the city’s {u.vacant_parcels.toLocaleString()} vacant lots are in a district whose rules a person has reviewed. Every other lot shows “Needs planner review.”
      </p>
      <details className="small">
        <summary>{u.unreviewed_districts.length} districts not yet reviewed (by vacant lots)</summary>
        <div className="columns">
          {u.unreviewed_districts.map((d) => (
            <div key={d.district}>
              {d.district}: {d.vacant_parcels.toLocaleString()}
            </div>
          ))}
        </div>
      </details>
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
        'Hazard flags are tested at each parcel’s centroid, so part of a lot can be steep or flood-prone without a flag.',
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
