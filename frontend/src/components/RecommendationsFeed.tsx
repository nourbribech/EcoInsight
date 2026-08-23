import { Disclosure } from './Disclosure'
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
        Nothing worth reporting in the last {formatWindow(windowHours)}.
        <Disclosure label="what does it look for?">
          <div className="empty-hint">
            The engine looks for avoidable waste, not for busy moments. It
            reports a machine left awake with nobody at it, a job still running
            unattended, and sustained load it can trace to one application. If
            it can't say what's responsible, it stays quiet.
          </div>
        </Disclosure>
      </div>
    )
  }

  return (
    <div className="rec-feed">
      {groupByDay(recommendations).map((group, index) => (
        /*
          Only the most recent day opens. Fifty rows of history was the
          single longest thing on this view, and all but the newest are a
          record rather than news - a reader who wants Tuesday can ask for
          Tuesday. The count stays on the closed row so nothing is hidden
          without being announced.
        */
        <details className="rec-day" key={group.key} open={index === 0}>
          {/*
            Every row used to show only a clock time. Inside a 1h window that
            reads fine; across 7 days it produced fifty rows of bare times
            with nothing to say which were Monday and which were Friday.
            Grouping puts the date in one place per day instead of repeating
            it on every row, which is also how any log or message feed does it.
          */}
          <summary className="rec-day-label">
            {group.label}
            <span className="rec-day-count">{group.items.length}</span>
          </summary>
          <ul className="rec-list">
            {group.items.map((rec) => {
              const kind =
                KINDS[rec.metric] ?? { label: rec.metric, severity: 'low' as const }
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
        </details>
      ))}
    </div>
  )
}

interface DayGroup {
  key: string
  label: string
  items: Recommendation[]
}

/**
 * Splits the feed into calendar days, newest first.
 *
 * Grouping is done on the LOCAL date, not on the ISO string, because the
 * server stores local timestamps and a naive `slice(0, 10)` would put
 * anything after midnight in the wrong bucket for any reader not in the
 * machine's own timezone.
 */
function groupByDay(recommendations: Recommendation[]): DayGroup[] {
  const groups: DayGroup[] = []

  for (const rec of recommendations) {
    const date = new Date(rec.timestamp)
    const key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`

    const last = groups[groups.length - 1]
    // The list arrives newest-first and in order, so a day is finished as
    // soon as a different one appears — no need to sort or index by key.
    if (last && last.key === key) {
      last.items.push(rec)
    } else {
      groups.push({ key, label: dayLabel(date), items: [rec] })
    }
  }

  return groups
}

function dayLabel(date: Date): string {
  const startOfDay = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()

  const daysAgo = Math.round(
    (startOfDay(new Date()) - startOfDay(date)) / 86_400_000,
  )

  if (daysAgo === 0) return 'Today'
  if (daysAgo === 1) return 'Yesterday'
  // Within the last week the weekday is the fastest thing to recognise;
  // beyond that it stops being unambiguous, so the date carries it.
  if (daysAgo < 7) {
    return date.toLocaleDateString([], { weekday: 'long' })
  }
  return date.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
}

/**
 * Windows are passed in hours because that is what the API takes, but "the
 * last 168h" is not a phrase anybody uses. Days above two, hours below.
 */
function formatWindow(hours: number): string {
  if (hours < 48) return `${hours}h`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? '' : 's'}`
}
