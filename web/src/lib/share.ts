import type { Placement } from '../three/engine'

/**
 * A shareable scenario: lot, weights and plan, in the URL hash so the link works
 * on a static host and never reaches the server. Everything decoded is treated
 * as untrusted: ids must be known, numbers finite, and the plan size capped.
 */
export interface Shared {
  lot: string
  weights: Record<string, number>
  profile: string | null
  placements: Omit<Placement, 'uid'>[]
}

const KEY = 'share'

function toB64Url(s: string) {
  return btoa(String.fromCharCode(...new TextEncoder().encode(s))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fromB64Url(s: string) {
  const bin = atob(s.replace(/-/g, '+').replace(/_/g, '/'))
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)))
}

export function shareUrl(s: Shared): string {
  const compact = { v: 1, l: s.lot, w: s.weights, p: s.profile, b: s.placements.map((b) => [b.typ, round(b.x), round(b.z), b.rot]) }
  return `${location.origin}${location.pathname}#${KEY}=${toB64Url(JSON.stringify(compact))}`
}

const round = (n: number) => Math.round(n * 100) / 100
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)

/** The scenario in the current URL, or null if there is none or it does not check out. */
export function readShare(known: { parcelId: { pattern: string; minChars: number; maxChars: number }; criteria: Set<string>; typologies: Set<string>; profiles: Set<string>; maxBuildings: number }): Shared | null {
  const m = location.hash.match(new RegExp(`^#${KEY}=([A-Za-z0-9_-]{1,20000})$`))
  if (!m) return null
  try {
    const raw = JSON.parse(fromB64Url(m[1]))
    if (raw?.v !== 1 || typeof raw.l !== 'string' ||
        raw.l.length < known.parcelId.minChars || raw.l.length > known.parcelId.maxChars ||
        !new RegExp(known.parcelId.pattern).test(raw.l)) return null
    const weights = Object.fromEntries(
      Object.entries(raw.w ?? {}).filter(([k, v]) => known.criteria.has(k) && finite(v) && v >= 0 && v <= 1e6),
    ) as Record<string, number>
    const placements = (Array.isArray(raw.b) ? raw.b : [])
      .filter((b: unknown): b is [string, number, number, number] =>
        Array.isArray(b) && known.typologies.has(b[0]) && finite(b[1]) && finite(b[2]) && [0, 1, 2, 3].includes(b[3] as number))
      .slice(0, known.maxBuildings)
      .map(([typ, x, z, rot]: [string, number, number, number]) => ({ typ, x, z, rot }))
    return { lot: raw.l, weights, profile: typeof raw.p === 'string' && known.profiles.has(raw.p) ? raw.p : null, placements }
  } catch {
    return null
  }
}

/** Drop the share hash once applied, so later edits are not confused with the link. */
export function clearShare() {
  if (location.hash.startsWith(`#${KEY}=`)) history.replaceState(null, '', location.pathname + location.search)
}
