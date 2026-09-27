import { useEffect, useState } from 'react'

/** Live result of a CSS media query; false while `query` is null. */
export function useMedia(query: string | null): boolean {
  const [on, setOn] = useState(() => !!query && window.matchMedia(query).matches)
  useEffect(() => {
    if (!query) return
    const mq = window.matchMedia(query)
    const sync = () => setOn(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [query])
  return on
}

/** True while the window is at most `px` wide (app.yaml: panels.narrow_max_px). */
export const useNarrow = (px: number | null) => useMedia(px ? `(max-width: ${px}px)` : null)

/** True when the main pointer is a finger: no hover, no right button, no keys. */
export const useTouch = () => useMedia('(pointer: coarse)')
