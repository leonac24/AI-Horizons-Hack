import { useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTouch } from '../lib/media'
import { HelpContext } from '../lib/tour'
import type { TourStep } from '../types'

const GAP = 10
const MARGIN = 12

/** Keep a box of size w×h next to `r`, inside the window. */
function placeNear(r: DOMRect | null, w: number, h: number): { left: number; top: number } {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const clampX = (x: number) => Math.max(MARGIN, Math.min(vw - w - MARGIN, x))
  const clampY = (y: number) => Math.max(MARGIN, Math.min(vh - h - MARGIN, y))
  if (!r) return { left: clampX((vw - w) / 2), top: clampY((vh - h) / 2) }
  if (vh - r.bottom >= h + GAP + MARGIN) return { left: clampX(r.left), top: r.bottom + GAP }
  if (r.top >= h + GAP + MARGIN) return { left: clampX(r.left), top: r.top - h - GAP }
  if (vw - r.right >= w + GAP + MARGIN) return { left: r.right + GAP, top: clampY(r.top) }
  if (r.left >= w + GAP + MARGIN) return { left: r.left - w - GAP, top: clampY(r.top) }
  return { left: clampX((vw - w) / 2), top: clampY(vh - h - MARGIN) }
}

/**
 * A small ? button. Clicking it opens a short explanation from `app.yaml: help`.
 * The popover is portalled to <body> so scrolling panels can't clip it.
 */
export function HelpTip({ id }: { id: string }) {
  const tip = useContext(HelpContext)[id]
  const touch = useTouch()
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const btn = useRef<HTMLButtonElement>(null)
  const pop = useRef<HTMLDivElement>(null)

  const measure = useCallback(() => {
    if (!btn.current || !pop.current) return
    setPos(placeNear(btn.current.getBoundingClientRect(), pop.current.offsetWidth, pop.current.offsetHeight))
  }, [])
  useLayoutEffect(() => {
    if (open) measure()
  }, [open, measure])
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node
      if (!btn.current?.contains(t) && !pop.current?.contains(t)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        btn.current?.focus()
      }
    }
    window.addEventListener('pointerdown', onDown, true)
    window.addEventListener('keydown', onKey)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('pointerdown', onDown, true)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open, measure])

  if (!tip) return null
  return (
    <>
      <button
        ref={btn}
        type="button"
        className={`help-tip ${open ? 'on' : ''}`}
        aria-label={`Help: ${tip.title}`}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation()
          e.preventDefault()
          setOpen((v) => !v)
        }}
      >
        ?
      </button>
      {open &&
        createPortal(
          <div ref={pop} className="help-pop" role="dialog" aria-label={tip.title} style={pos ?? { left: -9999, top: -9999 }}>
            <div className="help-pop-head">
              <strong>{tip.title}</strong>
              <button type="button" className="help-x" aria-label="Close help" onClick={() => setOpen(false)}>
                ×
              </button>
            </div>
            <p>{(touch && tip.touch_body) || tip.body}</p>
          </div>,
          document.body,
        )}
    </>
  )
}

// --- walk-through ---------------------------------------------------------------

const PAD = 6

/**
 * Step-by-step tour. Dims the screen, spotlights the element tagged
 * `data-tour="<target>"`, and shows a card beside it. The screen underneath
 * is blocked while the tour is open so a stray click can't lose your place.
 */
export function Tour({ steps, onFinish, onSkip }: { steps: TourStep[]; onFinish: () => void; onSkip: () => void }) {
  const [i, setI] = useState(0)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const card = useRef<HTMLDivElement>(null)
  const next = useRef<HTMLButtonElement>(null)
  const step = steps[i]
  const last = i === steps.length - 1
  const touch = useTouch()

  // Targets move (panels slide, the palette reflows), so follow them each frame.
  useEffect(() => {
    let raf = 0
    let prev = ''
    const tick = () => {
      const el = step.target ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`) : null
      const r = el && el.offsetParent !== null ? el.getBoundingClientRect() : null
      const c = card.current
      const key = `${r ? [r.left, r.top, r.width, r.height].map(Math.round).join() : '-'}|${window.innerWidth}x${window.innerHeight}|${c?.offsetHeight}`
      if (key !== prev) {
        prev = key
        setRect(r)
        if (c) {
          const hole = r ? new DOMRect(r.left - PAD, r.top - PAD, r.width + 2 * PAD, r.height + 2 * PAD) : null
          setPos(placeNear(hole, c.offsetWidth, c.offsetHeight))
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [step])

  useEffect(() => next.current?.focus(), [i])

  // Capture keys before the 3D engine sees them (it binds R, Del, ⌘Z on window).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      e.stopImmediatePropagation()
      if (e.key === 'Escape') onSkip()
      else if (e.key === 'ArrowRight' && last) onFinish()
      else if (e.key === 'ArrowRight') setI(i + 1)
      else if (e.key === 'ArrowLeft' && i > 0) setI(i - 1)
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [i, last, onFinish, onSkip])

  return (
    <div className="tour" role="presentation">
      <div className="tour-block" />
      {rect ? (
        <div className="tour-hole" style={{ left: rect.left - PAD, top: rect.top - PAD, width: rect.width + 2 * PAD, height: rect.height + 2 * PAD }} />
      ) : (
        <div className="tour-dim" />
      )}
      <div ref={card} className="tour-card" role="dialog" aria-modal="true" aria-labelledby="tour-title" style={pos ?? { left: -9999, top: -9999 }}>
        <div className="eyebrow">
          Tour · {i + 1} of {steps.length}
        </div>
        <div id="tour-title" className="tour-title">
          {step.title}
        </div>
        <p>{(touch && step.touch_body) || step.body}</p>
        <div className="tour-dots" aria-hidden="true">
          {steps.map((_, k) => (
            <span key={k} className={k === i ? 'on' : ''} />
          ))}
        </div>
        <div className="tour-actions">
          {!last && (
            <button type="button" className="tour-skip" onClick={onSkip}>
              Skip tutorial
            </button>
          )}
          <span className="grow" />
          {i > 0 && (
            <button type="button" className="ghost-btn" onClick={() => setI(i - 1)}>
              Back
            </button>
          )}
          <button ref={next} type="button" className="go-btn" onClick={() => (last ? onFinish() : setI(i + 1))}>
            {last ? 'Got it' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
