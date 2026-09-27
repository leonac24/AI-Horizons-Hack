import { createContext } from 'react'
import type { HelpText, TourChapter } from '../types'

/** Text for the small ? buttons, from `app.yaml: help`. */
export const HelpContext = createContext<Record<string, HelpText>>({})

// --- which tutorial chapters this browser has already seen ---------------------

export type Seen = Partial<Record<TourChapter, 'done' | 'skipped'>>

export function readSeen(key: string): Seen {
  try {
    return JSON.parse(localStorage.getItem(key) ?? '{}') as Seen
  } catch {
    return {}
  }
}

export function writeSeen(key: string, seen: Seen) {
  try {
    localStorage.setItem(key, JSON.stringify(seen))
  } catch {
    // Storage blocked (private window, site data off): the tour just shows again next time.
  }
}

