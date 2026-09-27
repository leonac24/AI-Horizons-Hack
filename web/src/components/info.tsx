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
  const inputs = (metric?.dependsOn ?? dependsOn ?? []).filter((k) => config.assumptions[k])
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
                On this lot: <strong>{fmt(metric.value, metric.unit)}</strong>
                <span className="muted">{unitSuffix(metric.unit)}</span>
                {metric.low !== metric.high && (
                  <span className="dim">
                    {' '}
                    (range {fmt(metric.low, metric.unit)}–{fmt(metric.high, metric.unit)})
                  </span>
                )}
                {metric.note && <div className="dim small">{metric.note}</div>}
              </div>
            )}

            {criterion && (
              <p className="info-values small">
                Scored criterion ({criterion.direction === 'higher_is_better' ? 'higher is better' : 'lower is better'}). How much it counts is
                your call, on Whose priorities?
              </p>
            )}

            <div className="info-sec">How it’s computed</div>
            <p>{method.how}</p>
            {method.formula && <code className="info-formula">{method.formula}</code>}

            {children}

            {inputs.length > 0 && (
              <>
                <div className="info-sec">Built from ({inputs.length})</div>
                {inputs.map((k) => {
                  const a = config.assumptions[k]
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
