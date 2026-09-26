import type { Metric, Provenance } from '../types'

const PROV_LABEL: Record<Provenance, string> = {
  observed: 'observed',
  modeled: 'modeled',
  assumption: 'assumption',
  placeholder: 'placeholder',
}

export function fmt(x: number, unit?: string): string {
  if (unit === 'USD' || unit === 'USD/yr' || unit === 'USD/mo') {
    const v = Math.abs(x) >= 1000 ? `$${Math.round(x).toLocaleString()}` : `$${Math.round(x)}`
    return unit === 'USD/mo' ? `${v}/mo` : unit === 'USD/yr' ? `${v}/yr` : v
  }
  if (unit === '%' || unit === '% AMI') return `${Math.round(x)}%`
  if (unit === 'yes/no') return x ? 'yes' : 'no'
  if (Math.abs(x) >= 100) return Math.round(x).toLocaleString()
  if (Math.abs(x) >= 10) return x.toFixed(0)
  return x.toFixed(x % 1 === 0 ? 0 : 1)
}

function unitSuffix(unit: string): string {
  if (['USD', 'USD/yr', 'USD/mo', '%', '% AMI', 'yes/no'].includes(unit)) return unit === '% AMI' ? ' of AMI' : ''
  return ` ${unit}`
}

export function ProvenanceTag({ p }: { p: Provenance }) {
  return <span className={`prov-tag prov-${p}`}>{PROV_LABEL[p]}</span>
}

/** One metric: value, range bar within a shared domain, provenance styling. */
export function MetricRow({ m, domain, label }: { m: Metric; domain?: [number, number]; label?: string }) {
  const [d0, d1] = domain ?? [Math.min(m.low, 0), m.high || 1]
  const span = d1 - d0 || 1
  const pct = (x: number) => `${Math.max(0, Math.min(100, ((x - d0) / span) * 100))}%`
  const single = m.low === m.high
  return (
    <div className={`metric prov-${m.provenance}`} title={m.note ?? undefined}>
      <div className="metric-head">
        <span className="metric-label">{label ?? m.label}</span>
        <ProvenanceTag p={m.provenance} />
      </div>
      <div className="metric-value">
        <strong>{fmt(m.value, m.unit)}</strong>
        <span className="metric-unit">{unitSuffix(m.unit)}</span>
        {!single && (
          <span className="metric-range">
            {' '}
            (range {fmt(m.low, m.unit)}–{fmt(m.high, m.unit)})
          </span>
        )}
      </div>
      {domain && (
        <div className="range-track" aria-hidden>
          <div className="range-band" style={{ left: pct(m.low), width: `calc(${pct(m.high)} - ${pct(m.low)})` }} />
          <div className="range-tick" style={{ left: pct(m.value) }} />
        </div>
      )}
      {m.note && <div className="metric-note">{m.note}</div>}
    </div>
  )
}
