// Shapes served by the FastAPI server. Config mirrors data/config/*.yaml.

export type Provenance = 'observed' | 'modeled' | 'assumption' | 'placeholder'

export interface Metric {
  id: string
  label: string
  value: number
  low: number
  high: number
  unit: string
  provenance: Provenance
  sourceIds: string[]
  note?: string | null
}

export interface Typology {
  id: string
  label: string
  color: string
  use_key: string
  units: { min: number; max: number }
  unit_size_sf: number
  stories: number
  tenure_default: 'owner' | 'renter'
  supports_senior: boolean
}

export interface Criterion {
  id: string
  metric_id: string
  label: string
  question: string
  direction: 'higher_is_better' | 'lower_is_better'
  group: string
  default_weight: number
}

export interface Household {
  id: string
  label: string
  description: string
  ami_pct: number
  size: number
  tenure: 'owner' | 'renter'
  destination: string
}

export interface StakeholderProfile {
  id: string
  label: string
  weights: Record<string, number>
}

export interface Source {
  name: string
  publisher: string
  url: string | null
  vintage: string
  license: string
  verified: string | boolean
  note?: string | null
}

export interface Config {
  app: {
    name: string
    tagline: string
    disclaimer: string
    placeholder_notice: string
    smaa: { samples: number; seed: number; profile_concentration: number }
  }
  city: {
    name: string
    map: { center: [number, number]; zoom: number; basemap_style: string }
    hazards: Record<string, { source: string; label: string }>
  }
  zoning: { statuses: Record<string, { label: string }>; code: { name: string; url: string } }
  typologies: Typology[]
  criteria: Criterion[]
  households: { households: Household[]; destinations: Record<string, { label: string }> }
  stakeholders: { profiles: StakeholderProfile[] }
  sources: { sources: Record<string, Source> }
  hash: string
}

export interface ParcelSummary {
  id: string
  address: string
  neighborhood: string | null
  zoning: string | null
  lot_area_sf: number | null
  public: boolean
  lon: number
  lat: number
}

export interface ZoningCheck {
  rule_id: string
  label: string
  required: number
  actual: number
  unit: string
  passed: boolean
  citation: string | null
  quote: string | null
}

export interface ZoningResult {
  district: string | null
  status: string
  status_label: string
  reviewed: boolean
  use_citation: string | null
  use_quote: string | null
  checks: ZoningCheck[]
  max_units_by_rule: number | null
  note: string | null
}

export interface HouseholdCheck {
  household_id: string
  verdict: 'yes' | 'maybe' | 'no'
  affordable_monthly: number
  cost_monthly: Metric
  tenure_match: boolean
  note: string | null
}

export interface Scenario {
  typology_id: string
  units: number
  form_fits: boolean
  notes: string[]
  metrics: Record<string, Metric>
  zoning: ZoningResult
  households: HouseholdCheck[]
  carbon: { years: number[]; value: number[]; low: number[]; high: number[]; provenance: Provenance }
}

export interface Analysis {
  parcel: Record<string, unknown> & ParcelSummary
  config_hash: string
  site_context: Metric[]
  scenarios: Scenario[]
  placeholder_count: number
}

export interface Explanation {
  source: string
  reason?: string
  sentences: { text: string; metric_ids: string[] }[]
}

export interface Unknowns {
  placeholder_assumptions: { id: string; unit: string; rationale: string; source: string | null }[]
  unverified_sources: { id: string; name: string; note: string | null }[]
  unreviewed_districts: { district: string; vacant_parcels: number }[]
  vacant_parcels: number
  share_covered_by_reviewed_rules: number
}

export interface WorkBackwardsResult {
  typology_id: string
  units: number
  target_ami_pct: number
  zoning_path: string
  zoning: ZoningResult
  failed_rules: ZoningCheck[]
  subsidy_per_unit: { value: number; low: number; high: number; unit: string; provenance: Provenance }
  infrastructure_flags: string[]
  note: string
}
