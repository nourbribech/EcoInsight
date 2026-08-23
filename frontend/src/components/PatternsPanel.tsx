import { usePolling } from '../hooks/usePolling'
import type { OffHours, PeriodSummary } from '../types/api'

/** The server caches the digest for 60s; polling faster refetches it. */
const POLL_MS = 60_000

/**
 * Seven-day patterns: when the machine drew power, and what cost the most.
 *
 * These two blocks used to live inside SummaryPanel, which had grown into six
 * separate things in one panel — figures, tier, equivalences, day bars, a
 * 24-hour profile and an application list. A panel that is itself a dashboard
 * is the same flatness problem the page had, one level down.
 *
 * They moved here rather than being deleted because they answer a different
 * question from the digest. The digest is a VERDICT — am I doing well — which
 * is what Today is for. These are ANALYSIS: where did it go, and when. That
 * belongs on the view a reader opens when they want to dig, not on the one
 * they glance at.
 *
 * It fetches /api/summary independently rather than taking props. The usual
 * argument against that — two panels polling the same endpoint can disagree —
 * does not apply here: this view and the digest are never on screen at the
 * same time, so any disagreement is unobservable, and the server caches the
 * payload for a poll interval anyway.
 */
export function PatternsPanel({ days }: { days: number }) {
  const { data, error, loading } = usePolling<PeriodSummary>(
    `/api/summary?days=${days}`,
    POLL_MS,
  )

  if (loading) return <div className="chart-empty">Loading…</div>
  if (error) return <div className="chart-empty">Patterns unavailable: {error}</div>
  if (!data || data.current.samples === 0) {
    return <div className="chart-empty">No measurements in this period yet.</div>
  }

  return (
    <div className="patterns">
      <OffHoursProfile offhours={data.offhours} />

      {data.top_applications.length > 0 && (
        <div className="summary-apps">
          <span className="summary-apps-label">
            Costliest applications · last {data.days} days
          </span>
          {data.top_applications.map((application) => (
            <span className="summary-app" key={application.name}>
              {application.label ?? application.name}
              <b>{application.watt_hours.toFixed(1)} Wh</b>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * When the machine actually drew power, by hour of day.
 *
 * The number on its own does not persuade anybody — "136 Wh outside working
 * hours" is a statistic. Twenty-four bars with the small hours clearly lit is
 * an argument, and it is the one office finding an employee can act on
 * without asking anyone's permission.
 */
function OffHoursProfile({ offhours }: { offhours: OffHours }) {
  const peak = Math.max(...offhours.by_hour, 1)
  const share = offhours.offhours_share

  return (
    <div className="offhours">
      <div className="offhours-head">
        <span className="summary-apps-label">Draw by hour of day</span>
        <span className="offhours-figure">
          {offhours.offhours_watt_hours.toFixed(0)} Wh outside{' '}
          {offhours.workday_start_hour}:00–{offhours.workday_end_hour}:00
          {share !== null && ` · ${(share * 100).toFixed(0)}%`}
          {offhours.weekend_watt_hours > 0 &&
            `, of which ${offhours.weekend_watt_hours.toFixed(0)} Wh at weekends`}
        </span>
      </div>
      <div className="offhours-bars">
        {offhours.by_hour.map((wattHours, hour) => {
          const isWorkHour =
            hour >= offhours.workday_start_hour && hour < offhours.workday_end_hour
          return (
            <div
              className="offhours-hour"
              key={hour}
              title={`${String(hour).padStart(2, '0')}:00 — ${wattHours.toFixed(1)} Wh`}
            >
              <div className="offhours-track">
                <div
                  /* Off-hours bars carry the alert colour: the same height
                     means something different at 03:00 than at 15:00. */
                  className={`offhours-bar${isWorkHour ? '' : ' offhours-bar-off'}`}
                  style={{ height: `${(wattHours / peak) * 100}%` }}
                />
              </div>
              {hour % 6 === 0 && <span className="offhours-tick">{hour}</span>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
