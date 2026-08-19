import type { Recommendation } from '../types/api'

interface Props {
  recommendations: Recommendation[] | null
  error: string | null
  windowHours: number
}

/**
 * How each kind of finding is labelled and ranked.
 *
 * `severity` is a property of the RULE, not of how far a number strayed.
 * Something running with nobody at the keyboard is avoidable waste and
 * outranks "this app is busy", however busy it happens to be — busy is
 * usually just work.
 */
const KINDS: Record<string, { label: string; severity: 'high' | 'medium' | 'low' }> = {
  unattended_activity: { label: 'UNATTENDED', severity: 'high' },
  idle_waste: { label: 'IDLE', severity: 'medium' },
  cpu_usage_percent: { label: 'CPU', severity: 'low' },
  ram_usage_percent: { label: 'RAM', severity: 'low' },
}

// NOTE: this row used to show "2.6σ" — how many standard deviations above
// baseline the reading sat. It was removed rather than restyled, because it
// no longer described anything real: the trigger is a p90 percentile plus a
// persistence run plus an energy gate, and sigma is not part of any of them.
// A number that looks precise and means nothing is worse than no number.

export function RecommendationsFeed({ recommendations, error, windowHours }: Props) {
  if (error) {
    return <div className="chart-empty">Recommendations unavailable: {error}</div>
  }

  if (recommendations === null) {
    return <div className="chart-empty">Loading…</div>
  }

  if (recommendations.length === 0) {
    return (
      <div className="chart-empty">
        Nothing worth reporting in the last {windowHours}h.
        <div className="empty-hint">
          The engine looks for avoidable waste, not for busy moments. It
          reports a machine left awake with nobody at it, a job still running
          unattended, and sustained load it can trace to one application. If
          it can't say what's responsible, it stays quiet.
        </div>
      </div>
    )
  }

  return (
    <ul className="rec-feed">
      {recommendations.map((rec) => {
        const kind = KINDS[rec.metric] ?? { label: rec.metric, severity: 'low' as const }
        return (
          <li key={rec.id} className={`rec rec-${kind.severity}`}>
            <div className="rec-meta">
              <span className="rec-time">
                {new Date(rec.timestamp).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
              <span className="rec-metric">{kind.label}</span>
            </div>
            <p className="rec-message">{rec.message}</p>
          </li>
        )
      })}
    </ul>
  )
}
