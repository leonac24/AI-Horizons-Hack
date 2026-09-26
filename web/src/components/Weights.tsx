import type { Config } from '../types'
import type { Flip } from '../lib/scoring'

// Values layer UI. Uses the accent color only — never mixed into metric displays.

interface Props {
  config: Config
  weights: Record<string, number>
  profileId: string | null
  onWeights: (w: Record<string, number>, profileId: string | null) => void
}

export function WeightsPanel({ config, weights, profileId, onWeights }: Props) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1
  return (
    <section className="values-panel">
      <h3>Whose priorities?</h3>
      <p className="small muted">
        These are values, not evidence. Pick a starting point or move the sliders — the evidence above doesn’t change,
        only how it’s weighed. Presets are illustrative, not positions of real organizations.
      </p>
      <div className="presets">
        {config.stakeholders.profiles.map((p) => (
          <button
            key={p.id}
            className={`preset ${p.id === profileId ? 'active' : ''}`}
            onClick={() => onWeights({ ...p.weights }, p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>
      {config.criteria.map((c) => (
        <label key={c.id} className="weight-row" title={c.question}>
          <span className="weight-label">{c.label}</span>
          <input
            type="range"
            min={0}
            max={3}
            step={0.25}
            value={weights[c.id] ?? 0}
            onChange={(e) => onWeights({ ...weights, [c.id]: Number(e.target.value) }, null)}
          />
          <span className="weight-share">{Math.round(((weights[c.id] ?? 0) / total) * 100)}%</span>
        </label>
      ))}
    </section>
  )
}

export function SmaaBars({
  config,
  order,
  acc,
  labels,
}: {
  config: Config
  order: string[]
  acc: Record<string, number[]>
  labels: Record<string, string>
}) {
  const n = order.length
  return (
    <section className="smaa">
      <h3>How often does each option come out on top?</h3>
      <p className="small muted">
        {config.app.smaa.samples.toLocaleString()} runs, each with different weights near your current priorities and
        every value drawn from its uncertainty range. Darker = better rank.
      </p>
      {order.map((id) => (
        <div key={id} className="smaa-row">
          <span className="smaa-label">{labels[id]}</span>
          <div className="smaa-bar">
            {acc[id].map((share, r) => (
              <div
                key={r}
                className="smaa-seg"
                style={{ width: `${share * 100}%`, opacity: 1 - (r / Math.max(n - 1, 1)) * 0.85 }}
                title={`Rank ${r + 1}: ${Math.round(share * 100)}% of runs`}
              />
            ))}
          </div>
          <span className="smaa-first">{Math.round(acc[id][0] * 100)}% first</span>
        </div>
      ))}
    </section>
  )
}

export function FlipSentence({
  flip,
  config,
  labels,
  ids,
}: {
  flip: Flip | null
  config: Config
  labels: Record<string, string>
  ids: string[] // scenario ids in the same order as the scoring matrix
}) {
  if (!flip) {
    return (
      <p className="flip">
        No single-weight change flips the top two here — the leader wins across every weighting of one criterion.
      </p>
    )
  }
  const c = config.criteria[flip.criterionIndex]
  const dir = flip.delta > 0 ? 'rose' : 'fell'
  return (
    <p className="flip">
      <strong>{labels[ids[flip.challenger]]}</strong> would overtake <strong>{labels[ids[flip.winner]]}</strong> if
      the weight on <em>{c.label.toLowerCase()}</em> {dir} from {Math.round(flip.from * 100)}% to{' '}
      {Math.round(flip.to * 100)}% of the total.
    </p>
  )
}
