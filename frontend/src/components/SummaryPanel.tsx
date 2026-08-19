import { usePolling } from '../hooks/usePolling'
import type { OffHours, PeriodSummary } from '../types/api'

/** Nothing here changes faster than the telemetry cadence. */
const POLL_MS = 60_000

/**
 * "How am I doing" — the question every other panel leaves to the reader.
 *
 * The charts show what happened; this says whether it was good or bad, which
 * is the only thing a personal-improvement tool is really for. A number on
 * its own can't do that: 476 Wh is meaningless without either a comparison
 * or a share, so every figure here carries one.
 */
export function SummaryPanel({ days }: { days: number }) {
  const { data, error, loading } = usePolling<PeriodSummary>(
    `/api/summary?days=${days}`,
    POLL_MS,
  )

  if (loading) return <div className="chart-empty">Loading…</div>
  if (error) return <div className="chart-empty">Summary unavailable: {error}</div>
  if (!data || data.current.samples === 0) {
    return <div className="chart-empty">No measurements in this period yet.</div>
  }

  const peak = Math.max(...data.per_day.map((d) => d.watt_hours), 1)

  return (
    <div className="summary">
      <div className="summary-figures">
        <Figure
          label={`Energy · last ${data.days} days`}
          value={`${data.current.watt_hours.toFixed(0)} Wh`}
          detail={formatChange(data.change_percent)}
        />
        <Figure
          label="Carbon"
          value={`${data.current.grams_co2eq.toFixed(0)} g`}
          detail="CO₂eq · Tunisia grid"
        />
        <Figure
          label="Spent with nobody there"
          value={formatWaste(data)}
          detail={
            data.days_tracked > 0
              ? `idle tracking on ${data.days_tracked} of ${data.days} days`
              : 'idle not tracked yet'
          }
          // The one figure on the dashboard that is entirely avoidable, so it
          // is the one worth drawing the eye to.
          highlight
        />
      </div>

      {data.equivalences.length > 0 && (
        /*
          The same energy, restated in units the reader already owns. Nobody
          knows whether 476 Wh is a lot; everybody knows what boiling a kettle
          feels like. Carbon-derived comparisons are marked so they are not
          read as having the same precision as the measured ones.
        */
        <p className="equivalences">
          <span className="equivalences-label">About the same as</span>
          {data.equivalences.map((equivalence, index) => (
            <span className="equivalence" key={equivalence.label}>
              {index > 0 && <i className="equivalence-sep">·</i>}
              <b>{equivalence.value.toFixed(0)}</b> {equivalence.label}
              {equivalence.kind === 'carbon' && <i className="equivalence-kind"> (CO₂eq)</i>}
            </span>
          ))}
        </p>
      )}

      <div className="summary-days">
        {data.per_day.map((day) => (
          <div className="summary-day" key={day.date} title={`${day.date}: ${day.watt_hours.toFixed(0)} Wh`}>
            <div className="summary-bar-track">
              <div
                className="summary-bar"
                style={{ height: `${(day.watt_hours / peak) * 100}%` }}
              />
            </div>
            <span className="summary-day-label">{day.date.slice(8)}</span>
          </div>
        ))}
      </div>

      <OffHoursProfile offhours={data.offhours} />

      {data.top_applications.length > 0 && (
        <div className="summary-apps">
          <span className="summary-apps-label">Costliest applications</span>
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
 * A missing comparison is rendered as text, not hidden and not faked. The
 * server withholds change_percent when the previous period lacks comparable
 * coverage — saying so is more useful than an empty space the reader has to
 * interpret.
 */
function formatChange(changePercent: number | null): string {
  if (changePercent === null) return 'not enough history to compare'
  const direction = changePercent < 0 ? 'less' : 'more'
  return `${Math.abs(changePercent).toFixed(0)}% ${direction} than the period before`
}

function formatWaste(summary: PeriodSummary): string {
  if (summary.idle_awake_watt_hours === null) return '—'
  const share = summary.idle_awake_share
  const percent = share === null ? '' : ` · ${(share * 100).toFixed(0)}%`
  return `${summary.idle_awake_watt_hours.toFixed(0)} Wh${percent}`
}

function Figure({
  label, value, detail, highlight,
}: { label: string; value: string; detail: string; highlight?: boolean }) {
  return (
    <div className={`summary-figure${highlight ? ' summary-figure-alert' : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="summary-value">{value}</span>
      <span className="stat-detail">{detail}</span>
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
