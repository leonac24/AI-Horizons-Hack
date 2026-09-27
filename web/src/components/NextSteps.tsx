import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import { fmt } from '../lib/format'
import type { Ranking } from '../lib/plan'
import type { Analysis, Config, NextStep, OutreachDraft } from '../types'
import { Dots } from './ai'
import { HelpTip } from './help'

/** What to do next on this lot: who to ask, what to ask, and a draft to send. */
export function NextStepsTab({ config, analysis, ranking, profileLabel }: { config: Config; analysis: Analysis; ranking: Ranking; profileLabel: string }) {
  const id = analysis.parcel.id
  const [steps, setSteps] = useState<{ id: string; list: NextStep[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [handout, setHandout] = useState(false)
  useEffect(() => {
    let live = true
    api
      .nextSteps(id)
      .then((list) => live && setSteps({ id, list }))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [id])
  const list = steps?.id === id ? steps.list : null
  if (error) return <div className="expl small">{error}</div>
  if (!list)
    return (
      <div className="dim small">
        Working out next steps for this lot
        <Dots />
      </div>
    )
  const neighborhood = list.find((s) => s.id === 'neighborhood')
  return (
    <div className="col">
      <div>
        <div className="h-sec">What you can do next<HelpTip id="next_steps" /></div>
        <div className="dim small">
          Worked out from this lot’s ownership, zoning and site flags. Nothing is sent from here: drafts open in your own email for you to edit. {config.app.disclaimer}
        </div>
      </div>
      {list.map((s) => (
        <StepCard key={s.id} parcelId={id} step={s} onHandout={s.id === 'neighborhood' ? () => setHandout(true) : undefined} />
      ))}
      {handout && neighborhood && <Handout config={config} analysis={analysis} ranking={ranking} profileLabel={profileLabel} step={neighborhood} onClose={() => setHandout(false)} />}
    </div>
  )
}

function StepCard({ parcelId, step, onHandout }: { parcelId: string; step: NextStep; onHandout?: () => void }) {
  const [draft, setDraft] = useState<OutreachDraft | null>(null)
  const [body, setBody] = useState('')
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const c = step.contact
  const write = () => {
    setLoading(true)
    setError(null)
    api
      .draft(parcelId, step.id)
      .then((d) => {
        setDraft(d)
        setBody(d.body)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }
  const mailto = draft ? `mailto:${draft.to ?? ''}?subject=${encodeURIComponent(draft.subject)}&body=${encodeURIComponent(body)}` : ''
  return (
    <div className={`step-card ${step.blocking ? 'blocking' : ''}`}>
      <div className="step-head">
        <span className="step-title">{step.title}</span>
        {step.blocking && <span className="step-badge">check first</span>}
      </div>
      <p className="small">{step.why}</p>
      {step.note && <div className="hatched note-box small">{step.note}</div>}
      {step.facts.length > 0 && (
        <ul className="step-facts small">
          {step.facts.map((f) => (
            <li key={f.id}>{f.text}</li>
          ))}
        </ul>
      )}
      {step.questions.length > 0 && (
        <>
          <div className="eyebrow">What to ask</div>
          <ol className="step-qs small">
            {step.questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ol>
        </>
      )}
      {c && (
        <div className="step-contact small">
          <strong>Who:</strong>{' '}
          {c.url ? (
            <a href={c.url} target="_blank" rel="noreferrer">
              {c.label}
            </a>
          ) : (
            c.label
          )}
          {c.email && <> · {c.email}</>}
          {c.phone && <> · {c.phone}</>}
          {c.url && !c.checked && <span className="dim"> · link found by search, not yet confirmed by the team</span>}
        </div>
      )}
      <div className="step-actions">
        <button className="go-btn sm" onClick={write} disabled={loading} aria-busy={loading}>
          {loading ? (
            <>
              Drafting
              <Dots />
            </>
          ) : draft ? (
            'Redraft with AI'
          ) : (
            'Draft email with AI'
          )}
        </button>
        {onHandout && (
          <button className="ghost-btn sm" onClick={onHandout}>
            Neighborhood handout
          </button>
        )}
      </div>
      {error && <div className="small">{error}</div>}
      {draft && (
        <div className="draft">
          <div className="dim small">
            {draft.source === 'template'
              ? `Template letter (${draft.reason ?? 'no model'}). Edit it before sending.`
              : `Drafted by ${draft.source} from the facts above, then checked: no numbers, links or addresses that aren’t on this card. Edit it before sending.`}
          </div>
          <div className="small">
            <strong>To:</strong> {draft.to ?? 'add the recipient'} · <strong>Subject:</strong> {draft.subject}
          </div>
          <textarea className="field draft-body" value={body} onChange={(e) => setBody(e.target.value)} rows={12} aria-label="Email draft" />
          <div className="step-actions">
            <a className="go-btn sm" href={mailto}>
              Open in my email
            </a>
            <button
              className="ghost-btn sm"
              onClick={() =>
                navigator.clipboard.writeText(`Subject: ${draft.subject}\n\n${body}`).then(() => {
                  setCopied(true)
                  setTimeout(() => setCopied(false), 2000)
                })
              }
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** One printable page to bring to the neighborhood's community organization. */
function Handout({ config, analysis, ranking, profileLabel, step, onClose }: { config: Config; analysis: Analysis; ranking: Ranking; profileLabel: string; step: NextStep; onClose: () => void }) {
  const p = analysis.parcel
  const host = document.querySelector('.shell') ?? document.body
  return createPortal(
    <div className="memo-backdrop" onClick={onClose}>
      <div id="lotline-memo" onClick={(e) => e.stopPropagation()}>
        <div className="memo-head">
          <div className="memo-title">Housing on {p.address || p.id}: what do neighbors think?</div>
          <div className="memo-actions">
            <button className="memo-print" onClick={() => window.print()}>
              Print
            </button>
            <button className="memo-close" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
        <p>
          {p.neighborhood} · zoning {p.zoning ?? '—'} · {Math.round(p.lot_area_sf ?? 0).toLocaleString()} sq ft · parcel {p.id}
          {p.public ? ' · publicly held' : ''} · {new Date().toLocaleDateString()}
        </p>
        <p className="memo-disclaimer">{config.app.disclaimer}</p>
        <p>{step.why}</p>
        <div className="memo-h">Options being compared</div>
        <p className="small">
          Ranked under “{profileLabel}” priorities. The ranking changes with whose priorities you use; the numbers do not.
        </p>
        <table>
          <thead>
            <tr>
              <th>Option</th>
              <th>Homes</th>
              <th>Zoning path</th>
              {config.criteria.map((c) => (
                <th key={c.id}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ranking.ranked.map((o) => (
              <tr key={o.id}>
                <td>{o.label}</td>
                <td>{o.units}</td>
                <td>{o.zoning.status_label}</td>
                {config.criteria.map((c) => {
                  const m = o.metrics[c.metric_id]
                  return (
                    <td key={c.id}>
                      {fmt(m.value, m.unit)}
                      {m.provenance === 'placeholder' ? '*' : ''}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small">* placeholder value, not yet sourced.</p>
        <div className="memo-h">Questions for discussion</div>
        <ol>
          {step.questions.map((q) => (
            <li key={q} className="handout-q">
              {q}
            </li>
          ))}
        </ol>
        <div className="memo-h">Community organization</div>
        <p className="small">
          {step.note}
          {step.contact?.url && <> {step.contact.url}</>}
        </p>
      </div>
    </div>,
    host,
  )
}
