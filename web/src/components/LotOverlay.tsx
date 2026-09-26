import type { PointerEvent as RPointerEvent } from 'react'
import { PLAN_ID, subsidyPerHome, type Option, type Ranking } from '../lib/plan'
import type { Placement } from '../three/engine'
import type { Analysis, Config } from '../types'
import { ROLE_COLOR, roleOf, usd } from '../lib/format'

type L = Record<string, string>

export function Hud(p: {
  config: Config
  L: L
  analysis: Analysis
  plan: Option | null
  ranking: Ranking
  profileLabel: string
  year: number
  wbAmi: number
  showPlan: boolean
  empty: boolean
}) {
  const { config, plan, ranking } = p
  const idx = plan ? ranking.ranked.findIndex((o) => o.id === PLAN_ID) : -1
  const rank = !plan ? '—' : !plan.eligible ? 'excluded' : idx >= 0 ? `#${idx + 1} of ${ranking.ranked.length}` : '—'
  const zColor = plan ? ROLE_COLOR[roleOf(config, plan.zoning.status)] : '#6b7985'
  const carbon = plan ? Math.round(plan.carbon.value[Math.min(p.year, plan.carbon.value.length - 1)]) + ' t' : '—'
  const gap = plan ? usd(subsidyPerHome(config, plan.metrics['affordability.monthly_cost'], p.wbAmi)) : '—'
  const short = p.profileLabel.length > 16 ? p.profileLabel.slice(0, 15) + '…' : p.profileLabel
  return (
    <div className="hud" style={{ left: p.L.hudLeft, maxWidth: p.L.hudMax }}>
      <div className="hud-row">
        <Gauge label="Homes" value={String(plan?.units ?? 0)} color="#b6f23e" />
        <div className="gauge wide">
          <div className="eyebrow">Zoning · {p.analysis.parcel.zoning ?? '—'}</div>
          <div className="gauge-text" style={{ color: zColor }}>
            {plan ? plan.zoning.status_label : 'Nothing placed yet'}
          </div>
        </div>
        <Gauge label={`Rank · ${short}`} value={rank} labelColor="#ff5fa2" />
        <Gauge label={`CO₂e / hh · yr ${p.year}`} value={carbon} />
        <Gauge label={`Gap / home · ${p.wbAmi}% AMI`} value={gap} />
      </div>
      {p.empty && p.showPlan && <div className="hud-note lime">Drag a building from the palette onto the outlined lot. R rotates · Del removes.</div>}
      {!p.showPlan && <div className="hud-note info">Before: the lot as it is today. Switch to After to edit your plan.</div>}
      <div className={`hud-note shape prov-${p.analysis.lot_shape.provenance}`}>
        Lot {Math.round(p.analysis.lot_shape.frontage_ft)} × {Math.round(p.analysis.lot_shape.depth_ft)} ft — {p.analysis.lot_shape.note} Neighbors are illustrative.
      </div>
    </div>
  )
}

function Gauge({ label, value, color, labelColor }: { label: string; value: string; color?: string; labelColor?: string }) {
  return (
    <div className="gauge">
      <div className="eyebrow" style={labelColor ? { color: labelColor } : undefined}>
        {label}
      </div>
      <div className="gauge-val" style={color ? { color } : undefined}>
        {value}
      </div>
    </div>
  )
}

export function Palette(p: { config: Config; L: L; analysis: Analysis; counts: Record<string, number>; onDown: (id: string, e: RPointerEvent) => void }) {
  const { L } = p
  const W = Math.round(p.analysis.lot_shape.frontage_ft)
  const D = Math.round(p.analysis.lot_shape.depth_ft)
  const maxW = Math.max(...p.config.typologies.map((t) => t.building.footprint_ft[0]))
  const maxS = Math.max(...p.config.typologies.map((t) => t.stories))
  return (
    <div
      className="palette"
      style={{ left: L.palLeft, right: L.palRight, top: L.palTop, bottom: L.palBottom, flexDirection: L.palDir as 'row' | 'column', maxWidth: L.palMax, maxHeight: L.palMaxH }}
    >
      {p.config.typologies.map((t) => {
        const s = p.analysis.scenarios.find((x) => x.typology_id === t.id)
        const fits = s?.form_fits ?? false
        const [w, d] = t.building.footprint_ft
        const n = p.counts[t.id] ?? 0
        return (
          <div key={t.id} className="pal-card" title="Drag onto the lot" onPointerDown={(e) => p.onDown(t.id, e)}>
            <div className="pal-swatch">
              <div style={{ width: Math.round((w / maxW) * 58 + 10), height: Math.round((t.stories / maxS) * 30 + 6), background: t.building.body, borderTop: `3px solid ${t.building.roof}` }} />
            </div>
            <div className="pal-name">{t.short_label}</div>
            <div className={`pal-meta ${fits ? '' : 'warn'}`}>
              {fits ? `${t.building.homes} ${t.building.homes === 1 ? 'home' : 'homes'} · ${t.stories} st · ${w}×${d}` : `too big for ${W}×${D} lot`}
            </div>
            {n > 0 && <div className="pal-count">{n}</div>}
          </div>
        )
      })}
    </div>
  )
}

export function Inspector(p: { config: Config; L: L; placement: Placement | null; analysis: Analysis; onRotate: () => void; onDelete: () => void }) {
  if (!p.placement) return null
  const t = p.config.typologies.find((x) => x.id === p.placement!.typ)
  if (!t) return null
  const z = p.analysis.scenarios.find((s) => s.typology_id === t.id)?.zoning
  const role = z ? roleOf(p.config, z.status) : 'unreviewed'
  return (
    <div className="inspector" style={{ left: p.L.inspLeft, bottom: p.L.inspBottom }}>
      <div className="insp-title">
        <span className="swatch" style={{ background: t.color }} />
        <span className="strong">{t.label}</span>
      </div>
      <div className="muted small">
        {t.building.homes} {t.building.homes === 1 ? 'home' : 'homes'} · {t.stories} stories · usually {t.tenure_default}-occupied
        {t.supports_senior ? ' · can be senior / accessible housing' : ''}
      </div>
      <div className="small" style={{ color: ROLE_COLOR[role], margin: '6px 0 8px' }}>
        {z ? `${z.status_label} in ${p.analysis.parcel.zoning ?? 'this district'}${z.use_citation ? ` (${z.use_citation})` : ''}` : '—'}
      </div>
      <div className="insp-actions">
        <button className="ghost-btn" onClick={p.onRotate}>
          Rotate · R
        </button>
        <button className="ghost-btn danger" onClick={p.onDelete}>
          Delete · Del
        </button>
      </div>
      <div className="dim small">Drag the building to move it. Red means it’s off the lot or overlapping.</div>
    </div>
  )
}
