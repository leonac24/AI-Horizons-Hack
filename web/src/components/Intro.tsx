import type { Config } from '../types'

/** Cinematic title over the orbiting city; Enter unlocks once the terrain is built. */
export function Intro({ app, lotCount, ready, leaving, error, onEnter }: { app: Config['app'] | null; lotCount?: number; ready: boolean; leaving: boolean; error: string | null; onEnter: () => void }) {
  return (
    <div className={`intro${ready ? ' intro-ready' : ''}${leaving ? ' intro-leaving' : ''}`}>
      <div className="intro-vignette" />
      <div className="intro-content">
        {app && (
          <h1 className="intro-name" aria-label={app.name}>
            {[...app.name].map((ch, i) => (
              <span key={i} style={{ animationDelay: `${0.25 + i * 0.07}s` }}>{ch}</span>
            ))}
          </h1>
        )}
        {app && <p className="intro-tagline">{app.tagline}</p>}
        {error ? (
          <p className="intro-error">Could not load: {error}</p>
        ) : ready ? (
          <button className="go-btn intro-enter" onClick={onEnter} disabled={leaving} autoFocus>
            Explore {lotCount ? `${lotCount.toLocaleString()} mapped lots` : 'the city'} →
          </button>
        ) : (
          <div className="intro-loading">
            <div className="intro-progress"><div /></div>
            <span className="dim small">{app ? 'Building the city…' : 'Loading…'}</span>
          </div>
        )}
      </div>
      {app && <p className="intro-disclaimer">{app.disclaimer}</p>}
    </div>
  )
}
