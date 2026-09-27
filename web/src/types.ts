import type { BasemapConfig } from './three/basemap'

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
  /** Assumption ids (keys into Config.assumptions) this number was computed from. */
  dependsOn?: string[]
}

export interface SiteFact {
  id: string
  label: string
  value: string
  provenance: Provenance
  sourceIds: string[]
  note: string
}

export interface Typology {
  id: string
  label: string
  short_label: string
  color: string
  use_key: string
  unit_size_sf: number
  stories: number
  tenure_default: 'owner' | 'renter'
  supports_senior: boolean
  min_lot_sf_for_form: number
  building: {
    footprint_ft: [number, number]
    homes: number
    massing: string
    body: string
    roof: string
    max_in_a_row: number
    party_walls: boolean
  }
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

export interface Assumption {
  label: string | null
  value: number
  low: number
  high: number
  unit: string
  provenance: Provenance
  source: string | null
  rationale: string
  by_typology: Record<string, { value: number; low: number; high: number }> | null
}

/** How one number is made (data/config/methods.yaml), shown behind its (i) button. */
export interface Method {
  title: string
  how: string
  formula: string | null
  limits: string | null
}

export interface Config {
  app: {
    name: string
    tagline: string
    disclaimer: string
    placeholder_notice: string
    api: { ask_question_max_chars: number; lot_search_query_max_chars: number; plan_max_buildings: number }
    smaa: {
      samples: number
      seed: number
      profile_concentration: number
      // Draws and noise floor for the per-criterion leverage runs that order
      // the work plan (web/src/lib/leverage.ts).
      leverage_samples: number
      leverage_epsilon: number
    }
    evidence: { topics: Record<string, { label: string; listed: boolean }> }
    ask: { search_example: string; examples: string[] }
    tutorial: { storage_key: string; chapters: Partial<Record<TourChapter, TourStep[]>> }
    help: Record<string, { title: string; body: string }>
  }
  city: {
    name: string
    map: { center: [number, number]; zoom: number; basemap_style: string }
    scene: {
      origin: [number, number]
      scale: [number, number]
      half_extent: number
      rivers: [number, number][][]
      bridges: [string, number, number, string, number][]
      basemap?: BasemapConfig
    }
    hazards: Record<string, { source: string; label: string; lot_scene?: string }>
    zoning_links: string[]
  }
  zoning: {
    statuses: Record<string, { label: string; role: 'permitted' | 'staff_review' | 'discretionary' | 'variance' | 'prohibited' | 'unreviewed' }>
    code: { name: string; url: string; citation_format: string; source: string }
    district_colors: { prefix: string; color: string }[]
  }
  typologies: Typology[]
  criteria: Criterion[]
  households: { households: Household[]; destinations: Record<string, { label: string }> }
  stakeholders: { profiles: StakeholderProfile[] }
  sources: { sources: Record<string, Source> }
  assumptions: Record<string, Assumption>
  methods: Record<string, Method>
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

export interface Setback {
  rule_id: string
  label: string
  value_ft: number
  citation: string | null
  quote: string | null
}

export interface ZoningResult {
  district: string | null
  status: string
  status_label: string
  reviewed: boolean
  human_reviewed: boolean
  use_citation: string | null
  use_quote: string | null
  checks: ZoningCheck[]
  max_units_by_rule: number | null
  setbacks: Record<string, Setback>
  note: string | null
  disqualified: boolean
  disqualified_reason: string | null
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
  buildings: number
  form_fits: boolean
  eligible: boolean
  ineligible_reason: string | null
  notes: string[]
  metrics: Record<string, Metric>
  zoning: ZoningResult
  households: HouseholdCheck[]
  carbon: CarbonSeries
}

export interface CarbonSeries {
  years: number[]
  value: number[]
  low: number[]
  high: number[]
  provenance: Provenance
}

export interface LotShape {
  frontage_ft: number
  depth_ft: number
  provenance: Provenance
  sourceIds: string[]
  note: string
}

export interface Analysis {
  parcel: Record<string, unknown> & ParcelSummary
  lot_shape: LotShape
  rankable_typology_ids: string[]
  excluded_typology_ids: string[]
  config_hash: string
  site_context: Metric[]
  site_facts: SiteFact[]
  scenarios: Scenario[]
  placeholder_count: number
}

export interface Explanation {
  source: string
  reason?: string
  sentences: { text: string; metric_ids: string[] }[]
}

export interface NextStep {
  id: 'acquire' | 'zoning' | 'confirm' | 'site_check' | 'neighborhood'
  title: string
  why: string
  facts: { id: string; text: string }[]
  questions: string[]
  contact: { label: string; url: string | null; email: string | null; phone: string | null; checked: boolean } | null
  letter: string
  blocking: boolean
  note: string | null
}

export interface OutreachDraft {
  source: string
  reason?: string
  subject: string
  to: string | null
  body: string
}

export interface LotAnswer {
  source: string
  /** null when no checked answer could be produced (see `reason`). */
  answerable: boolean | null
  reason?: string
  sentences: { text: string; metric_ids: string[] }[]
}

export interface LotSearchFilters {
  neighborhoods: string[]
  zoning_districts: string[]
  min_lot_sf: number | null
  max_lot_sf: number | null
  publicly_held_only: boolean
  avoid: string[]
  not_understood: string[]
}

export type LotSearchResult =
  | { ok: true; filters: LotSearchFilters; match_count: number; results: ParcelSummary[] }
  | { ok: false; reason: string }

export interface Unknowns {
  placeholder_assumptions: { id: string; unit: string; rationale: string; source: string | null }[]
  unverified_sources: { id: string; name: string; note: string | null }[]
  uncovered_districts: { district: string; vacant_parcels: number }[]
  vacant_parcels: number
  share_covered_by_rules: number
  share_covered_by_human_reviewed_rules: number
  require_human_review: boolean
  pipeline?: { counts?: Record<string, number>; context?: Record<string, unknown> } | null
}

export interface EvidenceLeads {
  compiled: boolean
  documents: number
  passages: number
  total: number
  items: {
    id: string
    source_id: string
    source_name: string
    source_url: string | null
    document: string
    page: number | null
    part: number
    excerpt: string
    topic: string
  }[]
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

export interface PlanResult {
  units: number
  by_typology: Record<string, number>
  homes_by_typology: Record<string, number>
  metrics: Record<string, Metric>
  zoning: ZoningResult
  zoning_by_typology: Record<string, ZoningResult>
  failed_typologies: string[]
  households: HouseholdCheck[]
  carbon: CarbonSeries
  eligible: boolean
  ineligible_reason: string | null
  notes: string[]
}

export type TourChapter = 'city' | 'lot'
export interface TourStep {
  title: string
  body: string
  target: string | null
}
