import { usePolling } from '../hooks/usePolling'
import type { PeriodSummary, WasteRating } from '../types/api'

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
          // Says WHICH days the percentage is a share of. The figure is
          // idle energy over energy on the tracked days only — a share
          // against the full period would divide a 3-day numerator by a
          // 7-day total and report 5.3% where the answer is 13.9%.
          detail={
            data.days_tracked > 0
              ? `share of the ${data.days_tracked} day${data.days_tracked === 1 ? '' : 's'} idle was tracked`
              : 'idle not tracked yet'
          }
          // The one figure on the dashboard that is entirely avoidable, so it
          // is the one worth drawing the eye to.
          highlight
        />
      </div>

      <WasteTier
        rating={data.rating}
        minimumDays={data.rating_minimum_days}
        daysTracked={data.days_tracked}
      />

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

      {/*
        The 24-hour draw profile and the costliest-application list moved to
        PatternsPanel on the Live view. They are analysis - where did it go,
        and when - where everything left here is a verdict. Six sub-blocks in
        one panel made this a dashboard inside a dashboard.
      */}
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
 * The period's tier, or an explicit statement that there is not enough
 * evidence for one.
 *
 * It grades the WASTE SHARE, not the energy total. Grading consumption would
 * grade how much somebody worked and how much they were at their desk, and
 * hand the best score to whoever was on leave. A ratio is neutral to both:
 * working more cannot hurt it, and it is the only part of the figure the
 * person is able to change.
 *
 * The "not rated yet" state is rendered rather than hidden. An absent grade
 * that looks like blank space reads as a passing one.
 */
function WasteTier({
  rating, minimumDays, daysTracked,
}: { rating: WasteRating | null; minimumDays: number; daysTracked: number }) {
  if (rating === null) {
    return (
      <div className="tier tier-unrated">
        <span className="tier-badge">Not rated yet</span>
        <span className="tier-text">
          Needs {minimumDays} days of idle tracking to judge — {daysTracked} so far.
        </span>
      </div>
    )
  }

  return (
    <div className={`tier tier-${rating.tier}`}>
      <span className="tier-badge">{rating.label}</span>
      <span className="tier-text">
        {rating.detail}{' '}
        {rating.next_tier_share === null
          ? 'This is the best band.'
          : `Getting below ${(rating.next_tier_share * 100).toFixed(0)}% would reach the next band.`}
      </span>
    </div>
  )
}
