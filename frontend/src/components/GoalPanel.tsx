import { useState } from 'react'
import { usePolling } from '../hooks/usePolling'
import type { Goal } from '../types/api'

/** Progress moves on the telemetry cadence; a minute is plenty. */
const POLL_MS = 60_000

/** Offered targets, as shares. 15% is the default and the "good" band in
 *  rating.py; the rest bracket it closely enough to be a real choice. */
const PRESETS = [0.05, 0.1, 0.15, 0.2, 0.3]

/**
 * A soft weekly goal the user sets for themselves.
 *
 * Everything else on this page reports. This is the only panel that asks the
 * user to commit to something, and that is the whole reason it exists: a
 * number you did not choose is a verdict, while a number you did choose is a
 * target. The same 18% reads as an accusation in the first case and as
 * feedback in the second.
 *
 * It is deliberately soft — no streaks, no penalty, nothing recorded beyond
 * the target itself. On a company machine a hard goal turns instantly into a
 * performance metric somebody else can read, which is the failure mode this
 * whole project is built to avoid.
 */
export function GoalPanel() {
  // Bumped after a successful PUT. usePolling re-runs its effect when the URL
  // changes, so this refetches immediately instead of leaving the panel stale
  // until the next tick — and avoids holding a local copy of the response
  // that would then have to be reconciled against the poll.
  const [refresh, setRefresh] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const { data, error, loading } = usePolling<Goal>(
    `/api/goal?r=${refresh}`,
    POLL_MS,
  )

  async function choose(target: number) {
    setSaving(true)
    setSaveError(null)
    try {
      const res = await fetch('/api/goal', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_share: target }),
      })
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      setRefresh((n) => n + 1)
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="chart-empty">Loading…</div>
  if (error) return <div className="chart-empty">Goal unavailable: {error}</div>
  if (!data) return null

  const { status } = data
  const days = dayOfWeek(data.week_start, status.elapsed_fraction)

  return (
    <div className={`goal goal-${status.state}`}>
      <div className="goal-head">
        <span className="goal-headline">{status.headline}</span>
        <span className="muted">{days}</span>
      </div>

      <GoalBar status={status} />

      <p className="goal-detail">{status.detail}</p>

      <div className="goal-picker">
        <span className="summary-apps-label">
          Weekly goal
          {/*
            "Assumed" vs "yours" matters more than it looks. A default
            presented as a choice the user made is a small lie, and it is the
            one that would make somebody dismiss the panel as nagging.
          */}
          {data.chosen_at === null && <i className="muted"> · assumed, not yours yet</i>}
        </span>
        <div className="goal-options">
          {PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              disabled={saving}
              className={
                Math.abs(preset - data.target_share) < 0.001 ? 'active' : ''
              }
              onClick={() => choose(preset)}
            >
              {(preset * 100).toFixed(0)}%
            </button>
          ))}
        </div>
        {saveError && <span className="goal-error">Could not save: {saveError}</span>}
      </div>

      <PreviousWeek goal={data} />
    </div>
  )
}

/**
 * How far into the week we are, in words.
 *
 * The elapsed fraction is what the projection is built on, so saying it out
 * loud is the difference between a reader trusting the budget and wondering
 * where it came from.
 */
function dayOfWeek(weekStart: string, elapsed: number): string {
  const day = Math.min(Math.floor(elapsed * 7) + 1, 7)
  const started = new Date(weekStart).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  })
  return `day ${day} of 7 · week of ${started}`
}

/**
 * Waste so far against the week's allowance.
 *
 * The bar is drawn against the BUDGET rather than against total energy, so a
 * full bar means "you have used the whole week's allowance" — a fact worth
 * seeing — instead of "you wasted all your energy", which would never be
 * true and so would never fill.
 */
function GoalBar({ status }: { status: Goal['status'] }) {
  if (status.budget_watt_hours === null || status.wasted_watt_hours === null) {
    // No honest bar to draw yet. Rendering an empty track would read as
    // "nothing wasted", which is the opposite of "not measured".
    return null
  }

  const used = status.wasted_watt_hours / status.budget_watt_hours
  const filled = Math.min(used, 1) * 100

  return (
    <div className="goal-bar-row">
      <div className="goal-bar-track" role="img"
           aria-label={`${(used * 100).toFixed(0)} percent of the week's allowance used`}>
        <div className="goal-bar-fill" style={{ width: `${filled}%` }} />
        {/*
          The elapsed-time marker is what turns the bar into a pace reading.
          Fill behind it means ahead of schedule, fill past it means the
          allowance is going faster than the week is.
        */}
        <div
          className="goal-bar-now"
          style={{ left: `${status.elapsed_fraction * 100}%` }}
          title="where the week itself has got to"
        />
      </div>
      <span className="goal-bar-figure">
        {status.wasted_watt_hours.toFixed(0)} of {status.budget_watt_hours.toFixed(0)} Wh
      </span>
    </div>
  )
}

/**
 * Last week's closed verdict.
 *
 * Without a week that ends, a goal is just another gauge — you can be doing
 * well at it forever and never once have met it. This line is the only place
 * the user gets to have succeeded, which makes it worth more than its size.
 */
function PreviousWeek({ goal }: { goal: Goal }) {
  const previous = goal.previous_week

  if (previous === null) {
    return (
      <div className="goal-previous">
        <span className="goal-previous-label">Last week</span>
        <span className="muted">
          Not enough idle tracking to judge — the first verdict lands next Monday.
        </span>
      </div>
    )
  }

  return (
    <div className="goal-previous">
      <span className="goal-previous-label">Last week</span>
      <span className={`goal-verdict goal-verdict-${previous.met ? 'met' : 'missed'}`}>
        {previous.met ? 'Met' : 'Missed'}
      </span>
      <span className="muted">
        {(previous.share * 100).toFixed(0)}% wasted against a{' '}
        {(goal.target_share * 100).toFixed(0)}% goal
        {previous.wasted_watt_hours !== null &&
          ` · ${previous.wasted_watt_hours.toFixed(0)} Wh`}
      </span>
    </div>
  )
}
