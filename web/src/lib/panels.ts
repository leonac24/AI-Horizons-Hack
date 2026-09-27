import { useEffect, useState } from 'react'

// --- which panels this browser has tucked away (app.yaml: panels) --------------

export type PanelId = 'city' | 'hud' | 'palette' | 'analysis'
export type Tucked = Partial<Record<PanelId, boolean>>

function readTucked(key: string): Tucked {
  try {
    return JSON.parse(localStorage.getItem(key) ?? '{}') as Tucked
  } catch {
    return {}
  }
}

function writeTucked(key: string, t: Tucked) {
  try {
    localStorage.setItem(key, JSON.stringify(t))
  } catch {
    // Storage blocked: panels just open again next visit.
  }
}

/** Open/tucked state per panel. `key` is null until config loads. A panel the
 * viewer never toggled follows `defaults`. */
export function usePanels(key: string | null, defaults: Tucked) {
  const [tucked, setTucked] = useState<Tucked>({})
  useEffect(() => {
    if (key) setTucked(readTucked(key))
  }, [key])
  const isTucked = (id: PanelId) => tucked[id] ?? !!defaults[id]
  const toggle = (id: PanelId) => {
    const next = { ...tucked, [id]: !isTucked(id) }
    setTucked(next)
    if (key) writeTucked(key, next)
  }
  return { isTucked, toggle }
}
