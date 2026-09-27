import type { ParcelSummary } from '../types'

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
  onShare: () => void
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
            <button className="ghost-btn" onClick={p.onShare} title="Copy a link to this lot, priorities and plan">
              Share link
            </button>
            <button className="go-btn" onClick={p.onMemo}>
              Print memo
            </button>
          </div>
        )}
      </header>
      <div className="strip">{p.disclaimer}</div>
    </>
  )
}
