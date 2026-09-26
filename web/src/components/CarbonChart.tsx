import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Config, Scenario } from '../types'
import { ProvenanceTag } from './MetricView'

/** Cumulative tCO2e per household over time, with crossover years between scenarios. */
export function CarbonChart({ config, scenarios }: { config: Config; scenarios: Scenario[] }) {
  const typ = Object.fromEntries(config.typologies.map((t) => [t.id, t]))
  const years = scenarios[0]?.carbon.years ?? []
  const data = years.map((y, i) => {
    const row: Record<string, number> = { year: y }
    for (const s of scenarios) row[s.typology_id] = s.carbon.value[i]
    return row
  })
  const crossovers: string[] = []
  for (let a = 0; a < scenarios.length; a++)
    for (let b = a + 1; b < scenarios.length; b++) {
      const A = scenarios[a].carbon.value
      const B = scenarios[b].carbon.value
      const sign0 = Math.sign(A[0] - B[0])
      const k = A.findIndex((x, i) => i > 0 && Math.sign(x - B[i]) !== sign0 && Math.sign(x - B[i]) !== 0)
      if (sign0 !== 0 && k > 0) {
        const [hiStart, loStart] = sign0 > 0 ? [scenarios[a], scenarios[b]] : [scenarios[b], scenarios[a]]
        crossovers.push(
          `${typ[hiStart.typology_id].label} starts higher (more embodied carbon) but drops below ${typ[loStart.typology_id].label} by year ${years[k]}.`,
        )
      }
    }
  const prov = scenarios[0]?.carbon.provenance ?? 'placeholder'
  return (
    <section className={`carbon prov-${prov}`}>
      <div className="metric-head">
        <h3>Carbon per household over time</h3>
        <ProvenanceTag p={prov} />
      </div>
      <p className="small muted">Building materials at year 0, then home energy (PA grid, decarbonizing) and travel each year. Tonnes CO₂e.</p>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#e4dccb" strokeDasharray="2 4" />
          <XAxis dataKey="year" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} width={44} />
          <Tooltip formatter={(v) => `${Math.round(Number(v))} t`} labelFormatter={(y) => `Year ${y}`} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {scenarios.map((s) => (
            <Line
              key={s.typology_id}
              dataKey={s.typology_id}
              name={typ[s.typology_id].label}
              stroke={typ[s.typology_id].color}
              dot={false}
              strokeWidth={2}
              strokeDasharray={prov === 'observed' ? undefined : '5 3'}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      {crossovers.length > 0 && (
        <ul className="small crossovers">
          {crossovers.slice(0, 4).map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
