import type { Metric, Provenance } from '../types'
import { fmt, unitSuffix } from '../lib/format'

export function ProvTag({ p }: { p: Provenance }) {
  return <span className={`prov-tag prov-${p}`}>{p}</span>
}

/** One metric with its range band inside a shared domain. */
export function MetricBox({ m, label, domain, question }: { m: Metric; label?: string; domain?: [number, number]; question?: string }) {
  const [a, b] = domain ?? [Math.min(0, m.low), Math.max(m.high, 1e-6)]
  const pct = (x: number) => Math.max(0, Math.min(100, ((x - a) / (b - a || 1)) * 100))
  return (
    <div className={`mbox prov-${m.provenance}`} title={question ?? m.note ?? undefined}>
      <div className="mbox-head">
        <span className="mbox-label">{label ?? m.label}</span>
        <ProvTag p={m.provenance} />
      </div>
      <div>
        <strong className="mbox-val">{fmt(m.value, m.unit)}</strong>
        <span className="muted">{unitSuffix(m.unit)}</span>
        {m.low !== m.high && (
          <span className="dim small">
            {' '}
            (range {fmt(m.low, m.unit)}–{fmt(m.high, m.unit)})
          </span>
        )}
      </div>
      {domain && (
        <div className="band-track">
          <div className="band" style={{ left: `${pct(m.low)}%`, width: `${Math.max(1, pct(m.high) - pct(m.low))}%` }} />
          <div className="tick" style={{ left: `${pct(m.value)}%` }} />
        </div>
      )}
    </div>
  )
}
