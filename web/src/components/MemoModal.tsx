import type { Ranking } from '../lib/plan'
import type { Analysis, Config } from '../types'
import { fmt } from '../lib/format'

/** One printable page for a community meeting or a City Planning conversation. */
export function MemoModal({ config, analysis, ranking, profileLabel, onClose }: { config: Config; analysis: Analysis; ranking: Ranking; profileLabel: string; onClose: () => void }) {
  const p = analysis.parcel
  return (
    <div className="memo-backdrop" onClick={onClose}>
      <div id="lotline-memo" onClick={(e) => e.stopPropagation()}>
        <div className="memo-head">
          <div className="memo-title">
            {config.app.name}: {p.address || p.id}
          </div>
          <div className="memo-actions">
            <button className="memo-print" onClick={() => window.print()}>
              Print
            </button>
            <button className="memo-close" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
        <p>
          {p.neighborhood} · zoning {p.zoning ?? '—'} · {p.lot_area_sf == null ? 'area and dimensions unknown' : `${Math.round(p.lot_area_sf).toLocaleString()} sf · lot ${Math.round(analysis.lot_shape.frontage_ft)} × ${Math.round(analysis.lot_shape.depth_ft)} ft`} · parcel {p.id} · printed{' '}
          {new Date().toLocaleDateString()}
        </p>
        <p className="memo-disclaimer">{config.app.disclaimer}</p>
        <div className="memo-h">Options under “{profileLabel}” priorities</div>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Option</th>
              <th>Homes</th>
              <th>Zoning path</th>
              {config.criteria.map((c) => (
                <th key={c.id}>{c.label}</th>
              ))}
              <th>Top in % of runs</th>
            </tr>
          </thead>
          <tbody>
            {ranking.ranked.map((o, i) => (
              <tr key={o.id}>
                <td>{i + 1}</td>
                <td>{o.label}</td>
                <td>{o.units}</td>
                <td>{o.zoning.status_label}</td>
                {config.criteria.map((c) => {
                  const m = o.metrics[c.metric_id]
                  return (
                    <td key={c.id}>
                      {fmt(m.value, m.unit)}
                      {m.provenance === 'placeholder' ? '*' : ''}
                    </td>
                  )
                })}
                <td>{Math.round((ranking.acc[o.id]?.[0] ?? 0) * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        {ranking.excluded.length > 0 && <p className="small">Not ranked (hard requirement): {ranking.excluded.map((o) => `${o.label} — ${o.reason}${o.zoning?.human_reviewed ? '' : ' (AI-extracted rule, not checked by a planner)'}`).join('; ')}.</p>}
        <p className="small">
          * placeholder value — not yet sourced. {analysis.placeholder_count} placeholders on this lot. Full list: “What we don’t know.” Weights are values chosen by the user; the evidence does not change with them.
        </p>
      </div>
    </div>
  )
}
