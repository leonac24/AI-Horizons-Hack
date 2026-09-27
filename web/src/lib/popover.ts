import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from 'react'

const GAP = 10
const MARGIN = 12

/** Keep a box of size w×h next to `r`, inside the window. */
export function placeNear(r: DOMRect | null, w: number, h: number): { left: number; top: number } {
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
 * Open/close state and placement for a popover anchored to a button. The
 * popover closes on an outside click or Escape and follows its button when the
 * page scrolls or resizes. Render the popover through a portal to <body> so
 * scrolling panels can't clip it.
 */
export function useAnchoredPopover() {
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

  const toggle = (e: MouseEvent) => {
    e.stopPropagation()
    e.preventDefault()
    setOpen((v) => !v)
  }
  return { open, setOpen, toggle, btn, pop, style: pos ?? { left: -9999, top: -9999 } }
}

