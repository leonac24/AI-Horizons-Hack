import { useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { fmt, unitSuffix } from '../lib/format'
import { useAnchoredPopover } from '../lib/popover'
import { ConfigContext } from '../lib/tour'
import type { Assumption, Metric, Provenance } from '../types'
import { ProvTag } from './ui'

/** An assumption value in its own unit: shares as percents, money with $, the rest as-is. */
function fmtAssumption(x: number, unit: string): string {
  if (unit.startsWith('share')) return `${+(x * 100).toFixed(1)}%`
  if (unit.startsWith('USD')) return `$${x.toLocaleString()}${unit.slice(3)}`
  return `${x.toLocaleString()} ${unit}`
}

function rangeOf(a: Assumption, typologyId?: string) {
  const t = typologyId ? a.by_typology?.[typologyId] : undefined
  return { ...(t ?? a), varies: !t && !!a.by_typology }
}

function evidenceEntries(value: Record<string, unknown> | null | undefined): [string, Record<string, unknown>][] {
  if (!value) return []
  if ('evidence_tier' in value || 'geography' in value) return [['Estimate', value]]
  return Object.entries(value).filter((entry): entry is [string, Record<string, unknown>] =>
    !!entry[1] && typeof entry[1] === 'object' && !Array.isArray(entry[1]))
}

function evidenceText(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null
  if (Array.isArray(value)) {
    const items = value.map(evidenceText).filter((item): item is string => !!item)
    return items.length ? items.join('; ') : null
  }
  if (typeof value === 'object') {
    const fields = value as Record<string, unknown>
    return ['type', 'name', 'geoid', 'id', 'county', 'state', 'vintage', 'join_method', 'parcel_join_method']
      .map(k => evidenceText(fields[k])).filter(Boolean).join(' · ') || null
  }
  return typeof value === 'string' || typeof value === 'number' ? String(value) : null
}

function resolvedInputs(metric?: Metric): Record<string, Record<string, unknown>> {
  const inputs = metric?.evidence?.inputs
  if (!inputs || typeof inputs !== 'object' || Array.isArray(inputs)) return {}
  return Object.fromEntries(Object.entries(inputs).filter((entry): entry is [string, Record<string, unknown>] =>
    !!entry[1] && typeof entry[1] === 'object' && !Array.isArray(entry[1])))
}

function inputValue(value: unknown, unit: string, years?: unknown): string {
  if (Array.isArray(value)) {
    const labels = Array.isArray(years) ? years : []
    const last = value.length - 1
    return `${labels[0] ?? 'Start'}: ${String(value[0])} → ${labels[last] ?? 'End'}: ${String(value[last])} ${unit}`
  }
  return typeof value === 'number' ? fmtAssumption(value, unit) : String(value ?? 'Unknown')
}

interface Props {
  /** Key into methods.yaml. For a metric, its metric id. */
  id: string
  /** The number on screen, when there is one: supplies value, range, provenance, sources and inputs. */
  metric?: Metric
  sourceIds?: string[]
  dependsOn?: string[]
  provenance?: Provenance
  /** Show per-typology assumption values for this housing type. */
  typologyId?: string
  /** Extra evidence for this item, e.g. the zoning quotes. */
  children?: ReactNode
}

/**
 * A small (i) button: where this number comes from. Opens the method from
 * methods.yaml together with the live inputs behind the number on this lot —
 * the assumptions it was computed from, with their ranges and provenance, and
 * the datasets it cites. The ? button says how to use a screen; (i) says what
 * a number rests on.
 */
export function InfoTip({ id, metric, sourceIds, dependsOn, provenance, typologyId, children }: Props) {
  const config = useContext(ConfigContext)
  const { open, setOpen, toggle, btn, pop, style } = useAnchoredPopover()
  const method = config?.methods[id]
  if (!config || !method) return null

  const prov = metric?.provenance ?? provenance
  const resolved = resolvedInputs(metric)
  const inputs = [...new Set([...Object.keys(resolved), ...(metric?.dependsOn ?? dependsOn ?? [])])]
    .filter((k) => resolved[k] || config.assumptions[k])
  const sources = [...new Set(metric?.sourceIds ?? sourceIds ?? [])].filter((k) => config.sources.sources[k])
  const criterion = config.criteria.find((c) => c.metric_id === id)

  return (
    <>
      <button
        ref={btn}
        type="button"
        className={`info-tip ${open ? 'on' : ''}`}
        aria-label={`Where this comes from: ${method.title}`}
        aria-expanded={open}
        onClick={toggle}
      >
        i
      </button>
      {open &&
        createPortal(
          <div ref={pop} className="info-pop" role="dialog" aria-label={method.title} style={style}>
            <div className="help-pop-head">
              <strong>{method.title}</strong>
              <span className="grow" />
              {prov && <ProvTag p={prov} />}
              <button type="button" className="help-x" aria-label="Close" onClick={() => setOpen(false)}>
                ×
              </button>
            </div>

            {metric && (
              <div className="info-value">
                On this lot: <strong>{metric.unavailable ? 'Unknown' : fmt(metric.value, metric.unit)}</strong>
                <span className="muted">{unitSuffix(metric.unit)}</span>
                {!metric.unavailable && metric.low !== metric.high && (
                  <span className="dim">
                    {' '}
                    (range {fmt(metric.low, metric.unit)}–{fmt(metric.high, metric.unit)})
                  </span>
                )}
                {metric.note && <div className="dim small">{metric.note}</div>}
              </div>
            )}

            {evidenceEntries(metric?.evidence).length > 0 && (
              <>
                <div className="info-sec">Evidence behind this estimate</div>
                {evidenceEntries(metric?.evidence).map(([name, detail]) => (
                  <div className="info-source small" key={name}>
                    <strong>{name === 'Estimate' ? 'Source and method' : name.replaceAll('_', ' ')}</strong>
                    <div className="dim">
                      {[
                        evidenceText(detail.evidence_tier),
                        evidenceText(detail.geography),
                        evidenceText(detail.as_of),
                        evidenceText(detail.interval_type),
                      ].filter(Boolean).join(' · ')}
                    </div>
                    {!!(detail.model_id || detail.model_version) &&
                      <div className="dim">Model: {[evidenceText(detail.model_id), evidenceText(detail.model_version)].filter(Boolean).join(' · ')}</div>}
                    {detail.sample_size !== undefined && detail.sample_size !== null &&
                      <div className="dim">Comparable observations: {String(detail.sample_size)}</div>}
                    {Array.isArray(detail.source_ids) && detail.source_ids.length > 0 &&
                      <div className="dim">Sources: {detail.source_ids.map(String).join(', ')}</div>}
                    {evidenceText(detail.limitations) && <div className="muted">{evidenceText(detail.limitations)}</div>}
                    {evidenceText(detail.confirmation_needed) &&
                      <div className="muted">Confirm: {evidenceText(detail.confirmation_needed)}</div>}
                  </div>
                ))}
              </>
            )}

            {criterion && (
              <p className="info-values small">
                Scored criterion ({criterion.direction === 'higher_is_better' ? 'higher is better' : 'lower is better'}). How much it counts is
                your call, on Whose priorities?
              </p>
            )}

            <div className="info-sec">How it’s computed</div>
            <p>{method.how}</p>
            {typeof metric?.evidence?.analysis_start_year === 'number' &&
              <p className="small dim">Calculation starts in {metric.evidence.analysis_start_year}; chart year 0 is the upfront materials estimate.</p>}
            {method.formula && <code className="info-formula">{method.formula}</code>}

            {children}

            {inputs.length > 0 && (
              <>
                <div className="info-sec">Built from ({inputs.length})</div>
                {inputs.map((k) => {
                  const a = config.assumptions[k]
                  const detail = resolved[k]
                  if (detail) {
                    const unit = String(detail.unit ?? a?.unit ?? '')
                    const label = a?.label ?? (k === 'grid_kgco2e_by_year' ? 'Year-by-year grid scenario' : k)
                    const ids = Array.isArray(detail.source_ids) ? detail.source_ids.map(String) : []
                    return (
                      <details key={k} className="info-input">
                        <summary>
                          <span className="grow">{label}</span>
                          <span className="num">
                            {inputValue(detail.value, unit, detail.years)}
                            {!Array.isArray(detail.value) && detail.low !== detail.high &&
                              <span className="dim"> ({inputValue(detail.low, unit)}–{inputValue(detail.high, unit)})</span>}
                          </span>
                          <ProvTag p={detail.provenance as Provenance ?? 'modeled'} />
                        </summary>
                        <p className="small dim">{[evidenceText(detail.geography), evidenceText(detail.as_of), evidenceText(detail.interval_type)].filter(Boolean).join(' · ')}</p>
                        {Array.isArray(detail.value) && <>
                          <p className="small dim">Central pathway: Mid-case. Conservative annual scenario envelope:</p>
                          <p className="small dim">Low: {inputValue(detail.low, unit, detail.years)}</p>
                          <p className="small dim">High: {inputValue(detail.high, unit, detail.years)}</p>
                        </>}
                        <p className="small muted">{evidenceText(detail.limitations)}</p>
                        {ids.map((sid) => {
                          const src = config.sources.sources[sid]
                          return <p className="small dim" key={sid}>{src?.url ? <a href={src.url} target="_blank" rel="noreferrer">{src.name}</a> : (src?.name ?? sid)}</p>
                        })}
                      </details>
                    )
                  }
                  const r = rangeOf(a, typologyId)
                  const src = a.source ? config.sources.sources[a.source] : null
                  return (
                    <details key={k} className="info-input">
                      <summary>
                        <span className="grow">{a.label ?? k}</span>
                        <span className="num">
                          {fmtAssumption(r.value, a.unit)}
                          {r.low !== r.high && (
                            <span className="dim">
                              {' '}
                              ({fmtAssumption(r.low, a.unit)}–{fmtAssumption(r.high, a.unit)})
                            </span>
                          )}
                        </span>
                        <ProvTag p={a.provenance} />
                      </summary>
                      <p className="small muted">{a.rationale}</p>
                      {r.varies && <p className="small dim">Varies by housing type; the base value is shown.</p>}
                      <p className="small dim">
                        <code>{k}</code>
                        {src && (
                          <>
                            {' · '}
                            {src.url ? (
                              <a href={src.url} target="_blank" rel="noreferrer">
                                {src.name}
                              </a>
                            ) : (
                              src.name
                            )}
                          </>
                        )}
                      </p>
                    </details>
                  )
                })}
              </>
            )}

            {sources.length > 0 && (
              <>
                <div className="info-sec">Data sources</div>
                {sources.map((k) => {
                  const s = config.sources.sources[k]
                  return (
                    <div key={k} className="info-source small">
                      {s.url ? (
                        <a href={s.url} target="_blank" rel="noreferrer">
                          {s.name}
                        </a>
                      ) : (
                        <strong>{s.name}</strong>
                      )}
                      <div className="dim">
                        {s.publisher} · {s.vintage} · {s.license} ·{' '}
                        {s.verified ? `checked ${s.verified === true ? '' : s.verified}`.trim() : 'not connected yet'}
                      </div>
                      {s.note && <div className="muted">{s.note}</div>}
                    </div>
                  )
                })}
              </>
            )}

            {method.limits && (
              <>
                <div className="info-sec">What it doesn’t tell you</div>
                <p className="info-limits small">{method.limits}</p>
              </>
            )}
          </div>,
          document.body,
        )}
    </>
  )
}
