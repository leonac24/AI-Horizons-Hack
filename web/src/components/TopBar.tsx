import type { ParcelSummary } from '../types'
import { HelpTip } from './help'

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
  onHelp: () => void
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
        {isLot && (
          <button className="ghost-btn back-btn" onClick={p.onCity} data-tour="back" title="Back to the city map">
            ← City map
          </button>
        )}
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
            <div className="bar-actions" data-tour="plan-controls">
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
            <HelpTip id="plan_controls" />
            </div>
            <button className="ghost-btn" onClick={p.onShare} title="Copy a link to this lot, priorities and plan">
              Share link
            </button>
            <button className="go-btn" onClick={p.onMemo} data-tour="memo">
              Print memo
            </button>
          </div>
        )}
        <button className="ghost-btn help-btn" onClick={p.onHelp} data-tour="help-button" title="Show the tour for this screen" aria-label="Show the tour for this screen">
          ?
        </button>
      </header>
      <div className="strip">{p.disclaimer}</div>
    </>
  )
}
