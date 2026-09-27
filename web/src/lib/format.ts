import type { Config } from '../types'

// Zoning path colors keyed by the semantic role from zoning.yaml.
export const ROLE_COLOR: Record<string, string> = {
  permitted: '#2fd06b',
  discretionary: '#ffb800',
  variance: '#ff7a45',
  prohibited: '#ff3b3b',
  unreviewed: '#9db4cc',
}

/** Pill color for a zoning district code (zoning.yaml district_colors, first prefix match). */
export function districtColor(config: Config, code: string | null): string {
  const hit = config.zoning.district_colors.find((d) => (code ?? '').startsWith(d.prefix))
  return hit?.color ?? '#1f8bff'
}

export function roleOf(config: Config, status: string): string {
  return config.zoning.statuses[status]?.role ?? 'unreviewed'
}

export const usd = (x: number) => '$' + Math.round(x).toLocaleString()

export function fmt(x: number, unit?: string): string {
  if (unit === 'USD' || unit === 'USD/yr' || unit === 'USD/mo') {
    const v = usd(x)
    return unit === 'USD/mo' ? `${v}/mo` : unit === 'USD/yr' ? `${v}/yr` : v
  }
  if (unit === '%' || unit === '% AMI') return `${Math.round(x)}%`
  if (unit === 'yes/no') return x ? 'yes' : 'no'
  if (unit === '0–1') return x.toFixed(2)
  if (Math.abs(x) >= 100) return Math.round(x).toLocaleString()
  if (Math.abs(x) >= 10) return x.toFixed(0)
  return x.toFixed(x % 1 === 0 ? 0 : 1)
}

export function unitSuffix(unit: string): string {
  if (['USD', 'USD/yr', 'USD/mo', '%', 'yes/no', '0–1'].includes(unit)) return ''
  if (unit === '% AMI') return ' of AMI'
  if (unit === 'tCO2e') return ' t CO₂e'
  return ` ${unit}`
}
