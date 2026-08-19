import { usePolling } from '../hooks/usePolling'
import type { Insights } from '../types/api'

/** The server caches this for 60s; polling faster just refetches it. */
const POLL_MS = 120_000

/**
 * Standing findings about how the machine is configured.
 *
 * Separate from the recommendations feed on purpose. That feed is a log of
 * EVENTS — things that happened, ordered by time, that scroll away. These are
 * STATES: true right now, true until someone changes a setting, and worth
 * fixing once rather than reacting to. Mixing the two would bury a permanent
 * saving underneath a stream of transient alerts.
 *
 * It also guarantees the panel is never empty, which the event feed cannot:
 * measured on this machine, the feed had nothing to show for over 24 hours.
 */
export function InsightsPanel() {
  const { data, error, loading } = usePolling<Insights>('/api/insights', POLL_MS)

  if (loading) return <div className="chart-empty">Checking power settings…</div>
  if (error) return <div className="chart-empty">Settings unavailable: {error}</div>
  if (!data || data.findings.length === 0) {
    return <div className="chart-empty">No configuration findings.</div>
  }

  return (
    <ul className="findings">
      {data.findings.map((finding) => (
        <li key={finding.key} className={`finding finding-${finding.severity}`}>
          <div className="finding-head">
            <span className="finding-title">{finding.title}</span>
            {/*
              WHO can fix it, shown on every row.
              On a company-managed machine some settings belong to the user and
              some to IT. Telling an employee to change a policy their
              administrator has locked wastes their time and costs the tool its
              credibility, so the distinction is never left implicit.
            */}
            <span className={`finding-owner finding-owner-${finding.fixable}`}>
              {OWNER_LABELS[finding.fixable] ?? finding.fixable}
            </span>
          </div>
          <p className="finding-detail">{finding.detail}</p>
          {finding.action && <p className="finding-action">{finding.action}</p>}
        </li>
      ))}
    </ul>
  )
}

const OWNER_LABELS: Record<string, string> = {
  you: 'you can fix this',
  it: 'needs IT',
  none: 'nothing to do',
}
