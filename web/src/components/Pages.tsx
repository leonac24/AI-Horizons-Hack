import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Analysis, Config, Unknowns, WorkBackwardsResult } from '../types'
import { fmt, ProvenanceTag } from './MetricView'

export function WorkBackwards({ config, analysis }: { config: Config; analysis: Analysis }) {
  const first = analysis.scenarios[0]
  const [typology, setTypology] = useState(first?.typology_id ?? '')
  const [units, setUnits] = useState(first?.units ?? 1)
  const [ami, setAmi] = useState(60)
  const [res, setRes] = useState<WorkBackwardsResult | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const s = analysis.scenarios.find((x) => x.typology_id === typology)
    if (s) setUnits(s.units)
  }, [typology, analysis])

  useEffect(() => {
    if (!typology) return
    api
      .workBackwards(analysis.parcel.id, typology, units, ami)
      .then((r) => {
        setRes(r)
        setErr(null)
      })
      .catch((e: Error) => setErr(e.message))
  }, [analysis, typology, units, ami])

  return (
    <div className="work-backwards">
      <h2>Work backwards</h2>
      <p className="muted">Pick a target. See what would have to change on this lot to get there.</p>
      <div className="filter-row">
        <label>
          Housing type
          <select value={typology} onChange={(e) => setTypology(e.target.value)}>
            {config.typologies.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Homes
          <input type="number" min={1} max={200} value={units} onChange={(e) => setUnits(Math.max(1, Number(e.target.value)))} />
        </label>
        <label>
          Affordable to households at {ami}% of area median
          <input type="range" min={30} max={120} step={10} value={ami} onChange={(e) => setAmi(Number(e.target.value))} />
        </label>
      </div>
      {err && <p className="error">{err}</p>}
      {res && (
        <div className="wb-result">
          <section>
            <h3>Zoning</h3>
            <p>
              <strong>{res.zoning_path}</strong>
              {res.zoning.use_citation ? ` — ${res.zoning.use_citation}` : ''}
            </p>
            {res.failed_rules.length > 0 ? (
              <ul>
                {res.failed_rules.map((c) => (
                  <li key={c.rule_id}>
                    {c.label}: needs {c.required.toLocaleString()} {c.unit}, lot has {c.actual.toLocaleString()} → variance or
                    special exception {c.citation ? `(${c.citation})` : ''}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="small muted">{res.zoning.note ?? 'No reviewed dimensional rule fails.'}</p>
            )}
          </section>
          <section className={`prov-${res.subsidy_per_unit.provenance}`}>
            <div className="metric-head">
              <h3>Subsidy gap per home</h3>
              <ProvenanceTag p={res.subsidy_per_unit.provenance} />
            </div>
            <p className="big">
              {fmt(res.subsidy_per_unit.value, 'USD')}{' '}
              <span className="muted small">
                (range {fmt(res.subsidy_per_unit.low, 'USD')}–{fmt(res.subsidy_per_unit.high, 'USD')})
              </span>
            </p>
            <p className="small muted">{res.note}</p>
          </section>
          <section>
            <h3>Site and infrastructure</h3>
            {res.infrastructure_flags.length ? (
              <ul>
                {res.infrastructure_flags.map((f) => (
                  <li key={f}>{f} — expect added engineering and cost; confirm with a site survey.</li>
                ))}
              </ul>
            ) : (
              <p className="small muted">No slope, landslide or undermining flag at this lot’s centroid.</p>
            )}
          </section>
        </div>
      )}
    </div>
  )
}

export function WhatWeDontKnow() {
  const [u, setU] = useState<Unknowns | null>(null)
  useEffect(() => {
    api.unknowns().then(setU)
  }, [])
  if (!u) return <p>Loading…</p>
  return (
    <div className="unknowns">
      <h2>What we don’t know</h2>
      <p>
        This tool is decision support. Here is everything it is not yet sure about. Values marked{' '}
        <ProvenanceTag p="placeholder" /> are stand-ins that show how the tool works — not facts about Pittsburgh.
      </p>
      <section>
        <h3>Zoning rules</h3>
        <p>
          {Math.round(u.share_covered_by_reviewed_rules * 100)}% of the city’s {u.vacant_parcels.toLocaleString()} vacant
          lots are in a district whose rules a person has reviewed. Every other lot shows “Needs planner review.”
        </p>
        <details>
          <summary>{u.unreviewed_districts.length} districts not yet reviewed (by vacant lots)</summary>
          <ul className="columns">
            {u.unreviewed_districts.map((d) => (
              <li key={d.district}>
                {d.district}: {d.vacant_parcels.toLocaleString()}
              </li>
            ))}
          </ul>
        </details>
      </section>
      <section>
        <h3>Placeholder numbers ({u.placeholder_assumptions.length})</h3>
        <ul>
          {u.placeholder_assumptions.map((a) => (
            <li key={a.id}>
              <code>{a.id}</code> ({a.unit}) — {a.rationale}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h3>Data sources not connected yet ({u.unverified_sources.length})</h3>
        <ul>
          {u.unverified_sources.map((s) => (
            <li key={s.id}>
              {s.name}
              {s.note ? ` — ${s.note}` : ''}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h3>Always true</h3>
        <ul>
          <li>Hazard flags are tested at each parcel’s centroid, so part of a lot can be steep or flood-prone without a flag.</li>
          <li>Assessed land values are not market prices.</li>
          <li>City limits only — other Allegheny County municipalities have their own zoning codes.</li>
          <li>Households are illustrative; stakeholder presets are not positions of real organizations.</li>
        </ul>
      </section>
    </div>
  )
}

/** One printable page for a community meeting or a City Planning conversation. */
export function Memo({
  config,
  analysis,
  order,
  profileLabel,
  firstShare,
}: {
  config: Config
  analysis: Analysis
  order: string[]
  profileLabel: string
  firstShare: Record<string, number>
}) {
  const labels = Object.fromEntries(config.typologies.map((t) => [t.id, t.label]))
  const byId = Object.fromEntries(analysis.scenarios.map((s) => [s.typology_id, s]))
  const p = analysis.parcel
  return (
    <div className="memo">
      <h1>
        {config.app.name}: {p.address || p.id}
      </h1>
      <p>
        {p.neighborhood} · zoning {p.zoning} · {Math.round(p.lot_area_sf ?? 0).toLocaleString()} sf · parcel {p.id} · printed{' '}
        {new Date().toLocaleDateString()}
      </p>
      <p className="disclaimer">{config.app.disclaimer}</p>
      <h2>Options under “{profileLabel}” priorities</h2>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Option</th>
            <th>Homes</th>
            <th>Zoning path</th>
            {config.criteria.map((c) => (
              <th key={c.id}>{c.label}</th>
            ))}
            <th>Top in % of runs</th>
          </tr>
        </thead>
        <tbody>
          {order.map((id, i) => {
            const s = byId[id]
            return (
              <tr key={id}>
                <td>{i + 1}</td>
                <td>{labels[id]}</td>
                <td>{s.units}</td>
                <td>{s.zoning.status_label}</td>
                {config.criteria.map((c) => {
                  const m = s.metrics[c.metric_id]
                  return (
                    <td key={c.id}>
                      {fmt(m.value, m.unit)}
                      {m.provenance === 'placeholder' ? '*' : ''}
                    </td>
                  )
                })}
                <td>{Math.round((firstShare[id] ?? 0) * 100)}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="small">
        * placeholder value — not yet sourced. {analysis.placeholder_count} placeholders on this lot. Full list: “What we
        don’t know.” Weights are values chosen by the user; the evidence does not change with them.
      </p>
    </div>
  )
}
