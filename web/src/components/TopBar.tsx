import type { ParcelSummary } from '../types'

export type Layout = '1a' | '1b' | '1c'
const LAYOUT_NAMES: [Layout, string][] = [
  ['1a', 'Command bar'],
  ['1b', 'Dock'],
  ['1c', 'Bottom sheet'],
]

interface Props {
  mode: 'city' | 'lot'
  lot: ParcelSummary | null
  onCity: () => void
  showPlan: boolean
  setShowPlan: (v: boolean) => void
  canUndo: boolean
  canRedo: boolean
  onUndo: () => void
  onRedo: () => void
  onClear: () => void
  onReset: () => void
  onMemo: () => void
  layout: Layout
  setLayout: (l: Layout) => void
  disclaimer: string
}

export function TopBar(p: Props) {
  const isLot = p.mode === 'lot'
  return (
    <>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">L</div>
          <div className="brand-name">Lotline</div>
          <div className="brand-tag">SIM</div>
        </div>
        <nav className="crumbs">
          <button className={`crumb ${isLot ? 'dimmed' : ''}`} onClick={p.onCity}>
            Pittsburgh
          </button>
          {isLot && p.lot && (
            <>
              <span className="sep">/</span>
              <span className="muted">{p.lot.neighborhood}</span>
              <span className="sep">/</span>
              <span className="crumb-lot">{p.lot.address || p.lot.id}</span>
            </>
          )}
        </nav>
        {isLot && (
          <div className="bar-actions">
            <div className="seg">
              <button className={!p.showPlan ? 'on-info' : ''} onClick={() => p.setShowPlan(false)}>
                Before
              </button>
              <button className={p.showPlan ? 'on-lime' : ''} onClick={() => p.setShowPlan(true)}>
                After
              </button>
            </div>
            <button className="ghost-btn" disabled={!p.canUndo} onClick={p.onUndo} title="Undo (⌘Z)">
              Undo
            </button>
            <button className="ghost-btn" disabled={!p.canRedo} onClick={p.onRedo} title="Redo (⇧⌘Z)">
              Redo
            </button>
            <button className="ghost-btn danger" onClick={p.onClear}>
              Clear lot
            </button>
            <button className="ghost-btn" onClick={p.onReset}>
              Reset view
            </button>
            <button className="go-btn" onClick={p.onMemo}>
              Print memo
            </button>
          </div>
        )}
        <div className="layout-switch">
          <span className="eyebrow">Layout</span>
          {LAYOUT_NAMES.map(([id, name]) => (
            <button key={id} title={name} className={id === p.layout ? 'on' : ''} onClick={() => p.setLayout(id)}>
              {id}
            </button>
          ))}
        </div>
      </header>
      <div className="strip">{p.disclaimer}</div>
    </>
  )
}
