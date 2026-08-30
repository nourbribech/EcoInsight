import { useState, useEffect } from 'react'
import { useLiveSeries } from './hooks/useLiveSeries'
import { usePolling } from './hooks/usePolling'
import { StatsBar } from './components/StatsBar'
import { PowerChart } from './components/PowerChart'
import { UtilizationChart } from './components/UtilizationChart'
import { IoChart } from './components/IoChart'
import { ProcessTable } from './components/ProcessTable'
import { RecommendationsFeed } from './components/RecommendationsFeed'
import { SummaryPanel } from './components/SummaryPanel'
import { GoalPanel } from './components/GoalPanel'
import { ActionsPanel } from './components/ActionsPanel'
import { LifecyclePanel } from './components/LifecyclePanel'
import { WorkloadsPanel } from './components/WorkloadsPanel'
import { PatternsPanel } from './components/PatternsPanel'
import { CalibrationPanel } from './components/CalibrationPanel'
import { ITSetupWizard } from './components/ITSetupWizard'
import type { Measurement, Recommendation, Telemetry } from './types/api'
import './dashboard.css'

const WINDOWS = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  // 7d is viable now that /api/history aggregates in SQL: the request went
  // from 18.7 MB of raw rows (which froze the tab) to 61 KB.
  { label: '7d', hours: 168 },
]

/**
 * The page is split by QUESTION, not by data source.
 *
 * Before this it was twelve sections in one column, every one wrapped in an
 * identical panel, so nothing signalled where to look and the eye had to read
 * all of it. That flatness — not the amount of data — is what made it
 * overwhelming.
 *
 * The three views also separate two timescales that were interleaved. "How am
 * I doing this week" changes weekly; "what is happening right now" changes
 * every 1.5 seconds. Mixing them meant scrolling past a 7-day digest to reach
 * a live chart, which is a different question asked in a different mood.
 */
type View = 'today' | 'live' | 'machine' | 'setup' | 'guide'

const VIEWS: { id: View; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'live', label: 'Live' },
  { id: 'machine', label: 'Machine' },
  { id: 'setup', label: 'IT setup' },
  { id: 'guide', label: 'Guide' },
]

/** The estimation loop writes a measurement roughly every 1.5s. */
const MEASUREMENT_POLL_MS = 3000

/**
 * Telemetry is written every 120s (TELEMETRY_INTERVAL_SECONDS in
 * estimation_loop.py), so polling it faster than that just refetches
 * identical data. 30s keeps it feeling responsive without being wasteful.
 */
const TELEMETRY_POLL_MS = 30_000

/**
 * The feed lives on Today, where the window picker does not, so it needs a
 * window of its own. Seven days matches the digest directly above it, and the
 * feed already groups its rows by day.
 */
const RECOMMENDATIONS_WINDOW_HOURS = 168

interface WeekSelection {
  start: Date
  end: string
  isCurrent: boolean
}

function startOfWeek(date: Date): Date {
  const result = new Date(date)
  const day = result.getDay()
  const distance = day === 0 ? 6 : day - 1
  result.setHours(0, 0, 0, 0)
  result.setDate(result.getDate() - distance)
  return result
}

function currentWeek(): WeekSelection {
  const start = startOfWeek(new Date())
  return { start, end: localIso(new Date(start.getTime() + 7 * 86400000)), isCurrent: true }
}

function weekSelection(start: Date): WeekSelection {
  const current = startOfWeek(new Date()).getTime() === start.getTime()
  return { start, end: localIso(new Date(start.getTime() + 7 * 86400000)), isCurrent: current }
}

function localIso(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function weekLabel(start: Date): string {
  return start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function WeekCalendar({ selectedWeek, onWeekChange }: {
  selectedWeek: WeekSelection
  onWeekChange: (week: WeekSelection) => void
}) {
  const weeks = Array.from({ length: 7 }, (_, index) => {
    const start = new Date(currentWeek().start)
    start.setDate(start.getDate() - index * 7)
    return weekSelection(start)
  })

  return (
    <section className="week-calendar" aria-label="Choose a week to review">
      <div className="week-calendar-head">
        <div>
          <p className="eyebrow">History</p>
          <h2>Review a week</h2>
        </div>
        <span className="muted">Energy and waste by week</span>
      </div>
      <div className="week-strip">
        {weeks.map((week) => (
          <button
            key={week.start.toISOString()}
            type="button"
            className={`week-option${selectedWeek.start.getTime() === week.start.getTime() ? ' active' : ''}`}
            aria-pressed={selectedWeek.start.getTime() === week.start.getTime()}
            onClick={() => onWeekChange(week)}
          >
            <span>{week.isCurrent ? 'This week' : weekLabel(week.start)}</span>
            <small>{week.isCurrent ? weekLabel(week.start) : 'Mon–Sun'}</small>
          </button>
        ))}
      </div>
    </section>
  )
}

function App() {
  const [view, setView] = useState<View>('today')
  const [selectedWeek, setSelectedWeek] = useState<WeekSelection>(() => currentWeek())

  // 6h rather than 1h: the agent isn't always running during development, so
  // a 1h default frequently shows an empty dashboard even though there's
  // plenty of recent data.
  const [windowHours, setWindowHours] = useState(6)

  // Kept mounted for every view, not just Live.
  //
  // Two reasons. The tail effect appends rows from /api/current, so `latest`
  // is a genuine most-recent measurement within one poll of mount — which is
  // what the Today tiles need, and it does not depend on the window at all.
  // And the topbar's connection status has to mean something on every tab,
  // not only the one with charts on it.
  const { rows, status, error } = useLiveSeries(windowHours, MEASUREMENT_POLL_MS)

  // Telemetry: a plain refetch on an interval — and that's the RIGHT call
  // here, not laziness. The seed-and-append pattern exists to avoid
  // re-downloading a big payload for one new row. Telemetry is the opposite
  // case: ~69 rows per day (about 12 KB) that change only every 120s, and
  // there's no single-row /api/telemetry/current endpoint to append from
  // anyway. Applying the complex pattern here would be cargo-culting it.
  const telemetry = usePolling<Telemetry[]>(
    `/api/telemetry?hours=${windowHours}`,
    TELEMETRY_POLL_MS,
  )

  // Recommendations are written only when telemetry is (every 120s), so
  // there's nothing to gain from polling them faster than telemetry itself.
  const recommendations = usePolling<Recommendation[]>(
    `/api/recommendations?hours=${RECOMMENDATIONS_WINDOW_HOURS}&limit=50`,
    TELEMETRY_POLL_MS,
  )
  const session = usePolling<SessionInfo>('/api/session', 300_000)

  const latest = rows[rows.length - 1]
  const latestTelemetry = telemetry.data?.[telemetry.data.length - 1]

  // The IT setup tab is now shown to everyone, because it is the only route
  // to the unlock button - hiding it until IT mode is on made unlocking
  // impossible from inside the app. What the tab CONTAINS still depends on
  // the session: a user without write permission sees an explanation, a user
  // with it sees the unlock button, and an IT session sees the real panel.
  const visibleViews = VIEWS

  // An IT session that is replaced by a user session must not strand the
  // reader on a tab that no longer exists, which would render a blank page.
  const activeView = visibleViews.some((v) => v.id === view) ? view : 'today'

  const [leavingIt, setLeavingIt] = useState(false)

  /**
   * Leaving IT mode, owned here so the topbar badge and the setup screens
   * share one implementation rather than two that can drift apart.
   *
   * Undefined — and therefore rendered as no control at all — unless IT mode
   * came from the in-app unlock. `--mode it` is re-read on every request, so a
   * button clearing the stored preference would appear to do nothing.
   *
   * Reloading rather than re-rendering: switching mode changes which tabs
   * exist and what half the panels may show, and several hold their own
   * polled state. A reload is the honest way to start again as the other kind
   * of session.
   */
  const leaveItMode = session.data?.it_mode_source === 'unlocked'
    ? async () => {
        setLeavingIt(true)
        try {
          const response = await fetch('/api/session/lock-it', { method: 'POST' })
          if (response.ok) {
            window.location.reload()
            return
          }
          const payload = await response.json().catch(() => ({}))
          window.alert(payload.detail ?? 'Could not leave IT setup.')
        } finally {
          setLeavingIt(false)
        }
      }
    : undefined

  return (
    <div className="dashboard">
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">EcoInsight</span>
          {/*
            Connection state only. The sample count moved to the Live view,
            next to the picker that determines it — quoting "240 samples" on
            a tab with no window control describes something the reader
            cannot see.
          */}
          <span className={`status status-${status}`}>
            title={status === 'error' ? error ?? undefined : undefined}
            {status === 'live' && 'connected'}
            {status === 'loading' && 'connecting…'}
            {status === 'error' && 'connection lost'}
          </span>
          {/*
            The badge that NAMES the mode is also what leaves it.

            The exit lived only inside the IT setup tab, which meant the way
            out was reachable only from the screen somebody was trying to get
            away from — and invisible from the four views where they would
            actually notice they were in the wrong mode. Here it is on every
            view, and it sits on the one element that already tells the reader
            which mode they are in.

            It stays a plain label when leaving is impossible: a user session
            has nothing to leave, and IT mode from `--mode it` cannot be
            undone by any button.
          */}
          {session.data && (
            leaveItMode ? (
              <button
                type="button"
                className="session-mode session-mode-leave"
                onClick={leaveItMode}
                disabled={leavingIt}
                title="Leave IT setup and return to the employee view"
              >
                {leavingIt ? 'switching…' : 'IT setup ✕'}
              </button>
            ) : (
              <span className="session-mode">
                {session.data.mode === 'it' ? 'IT setup' : 'user session'}
              </span>
            )
          )}
        </div>

        <nav className="view-nav">
          {visibleViews.map((v) => (
            <button
              key={v.id}
              type="button"
              className={v.id === activeView ? 'active' : ''}
              aria-current={v.id === activeView ? 'page' : undefined}
              onClick={() => setView(v.id)}
            >
              {v.label}
            </button>
          ))}
        </nav>
      </header>

      {/*
        A setup banner appears only when the session is KNOWN and something
        actually needs doing.

        Both halves of this were wrong before. The user-side notice tested
        `session.data?.setup_state !== 'calibrated'`, which is true while
        session.data is still null - so every page load of a fully calibrated
        machine showed "Machine setup is needed" until /api/session answered.
        That call costs a WMI round trip: measured at 4.5s cold, and forever
        if the request failed.

        The IT-side panel had the opposite fault. It rendered on every view
        EXCEPT setup, so an IT session carried a full "Prepare this machine"
        block above Today, Live, Machine and Guide, duplicating the setup tab
        rather than complementing it - and it appeared even when the machine
        was already calibrated and there was nothing to prepare.

        Requiring session.data makes "unknown" render nothing, which is the
        only honest state before the answer arrives.
      */}
      {session.data && session.data.setup_state !== 'calibrated' && activeView !== 'setup' && (
        session.data.mode === 'it'
          ? <SetupPanel session={session.data} />
          : session.data.calibration_acknowledged
            ? <SetupNotice session={session.data} />
            : <CalibrationIntro session={session.data} onAcknowledge={() => setView('guide')} />
      )}

      {activeView === 'today' && (
        <TodayView
          latest={latest}
          latestTelemetry={latestTelemetry}
          recommendations={recommendations}
          selectedWeek={selectedWeek}
          onWeekChange={setSelectedWeek}
        />
      )}

      {activeView === 'live' && (
        <LiveView
          rows={rows}
          telemetry={telemetry}
          windowHours={windowHours}
          onWindowChange={setWindowHours}
        />
      )}

      {activeView === 'machine' && <MachineView />}

      {activeView === 'setup' && (
        <SetupView
          session={session.data}
          onLeaveItMode={leaveItMode}
          leaving={leavingIt}
        />
      )}

      {activeView === 'guide' && <GuideView />}
    </div>
  )
}

/**
 * The verdict and what to do about it. Nothing here changes faster than
 * every couple of minutes, which is why none of it needs the window picker.
 */
function TodayView({
  latest, latestTelemetry, recommendations, selectedWeek, onWeekChange,
}: {
  latest: Measurement | undefined
  latestTelemetry: Telemetry | undefined
  recommendations: { data: Recommendation[] | null; error: string | null }
  selectedWeek: WeekSelection
  onWeekChange: (week: WeekSelection) => void
}) {
  return (
    <>
      <StatsBar latest={latest} latestTelemetry={latestTelemetry} />

      {/*
        The goal leads, because it is the only thing on the page the user
        chose. The digest reports; this is a commitment they made, and a
        target you set yourself reads as feedback where the same number
        handed to you reads as a verdict.
      */}
      <section className="panel">
        <div className="panel-head">
          <h2>This week’s goal</h2>
          <div className="legend">
            <span className="muted">energy you could save · Monday to Sunday</span>
          </div>
        </div>
        <GoalPanel />
      </section>

      {/*
        Directly above the digest it scopes, and below the goal it does not.
        Sitting at the top it read as a filter over the whole view, which it
        never was: the goal is always about the current week, so selecting
        March left the panel beneath the picker unchanged and made the control
        look broken. A control belongs next to the thing it changes.
      */}
      <WeekCalendar selectedWeek={selectedWeek} onWeekChange={onWeekChange} />

      <section className="panel">
        <div className="panel-head">
          <h2>{selectedWeek.isCurrent ? 'Your current week' : 'Your selected week'}</h2>
          <div className="legend">
            <span className="muted">energy · carbon · energy used while away</span>
          </div>
        </div>
        <SummaryPanel days={7} end={selectedWeek.end} />
      </section>

      {/*
        One ranked list, above the event feed. Standing findings outrank any
        single alert - fixing a setting once saves power every day
        afterwards - and ranking them against each other is the whole point:
        three unranked lists made the reader do the prioritising.
      */}
      <section className="panel">
        <div className="panel-head">
          <h2>What you can improve</h2>
          <div className="legend">
            <span className="muted">settings and apps · checked regularly</span>
          </div>
        </div>
        <ActionsPanel />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Recommendations</h2>
          <div className="legend">
            <span className="muted">last 7 days · grouped by day</span>
          </div>
        </div>
        <RecommendationsFeed
          recommendations={recommendations.data}
          error={recommendations.error}
          windowHours={RECOMMENDATIONS_WINDOW_HOURS}
        />
      </section>
    </>
  )
}

/**
 * Live telemetry, and the only view the window picker applies to.
 *
 * The picker used to sit in the topbar, where it looked global and was not:
 * it scoped five of eleven panels, and SummaryPanel and LifecyclePanel were
 * hardcoded to seven days regardless. Selecting "1h" left the digest
 * unchanged, so a reader either concluded the app was broken or that the
 * digest was showing one hour. Putting the control inside the view it
 * governs makes its scope self-evident.
 */
function LiveView({
  rows, telemetry, windowHours, onWindowChange,
}: {
  rows: Measurement[]
  telemetry: { data: Telemetry[] | null; error: string | null }
  windowHours: number
  onWindowChange: (hours: number) => void
}) {
  return (
    <>
      <div className="live-controls">
          <span className="live-controls-label">Time range</span>
        <div className="window-picker">
          {WINDOWS.map((w) => (
            <button
              key={w.hours}
              type="button"
              className={w.hours === windowHours ? 'active' : ''}
              onClick={() => onWindowChange(w.hours)}
            >
              {w.label}
            </button>
          ))}
        </div>
        <span className="muted">
          {rows.length} readings · applies to the charts below
        </span>
      </div>

      {/*
        Seven-day patterns, above the live charts and below the window
        picker that does NOT apply to them - hence the explicit "last 7
        days" in the heading. Sitting next to Top consumers is deliberate:
        one is what is drawing power now, the other what cost the most all
        week, and the pair is more informative than either alone.
      */}
      <section className="panel">
        <div className="panel-head">
          <h2>Daily patterns</h2>
          <div className="legend">
            <span className="muted">last 7 days</span>
          </div>
        </div>
        <PatternsPanel days={7} />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Top apps</h2>
          <div className="legend">
            <span className="muted">which apps use the most power · updates every ~2 min</span>
          </div>
        </div>
        <ProcessTable />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Power use</h2>
          <div className="chart-meta">
            <span className="chart-unit">watts · where the power goes</span>
            <div className="legend">
              <span><i className="swatch swatch-baseline" /> baseline</span>
              <span><i className="swatch swatch-cpu" /> cpu</span>
              <span><i className="swatch swatch-ram" /> ram</span>
            </div>
          </div>
        </div>
        <PowerChart rows={rows} windowHours={windowHours} />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Computer activity</h2>
          <div className="chart-meta">
            <span className="chart-unit">percent used · 0–100 scale</span>
            <div className="legend">
              <span><i className="swatch swatch-cpu" /> cpu</span>
              <span><i className="swatch swatch-ram" /> ram</span>
              <span><i className="swatch swatch-brightness" /> brightness</span>
              {telemetry.data && <span className="muted">{telemetry.data.length} readings</span>}
            </div>
          </div>
        </div>
        {telemetry.error ? (
          <div className="chart-empty">Activity data is unavailable right now.</div>
        ) : (
          <UtilizationChart rows={telemetry.data ?? []} windowHours={windowHours} />
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>File activity</h2>
          <div className="chart-meta">
            <span className="chart-unit">data per second</span>
            <div className="legend">
              <span><i className="swatch swatch-disk-read" /> read (above)</span>
              <span><i className="swatch swatch-disk-write" /> write (below)</span>
            </div>
          </div>
        </div>
        {telemetry.error ? (
          <div className="chart-empty">File activity is unavailable right now.</div>
        ) : (
          <IoChart
            rows={telemetry.data ?? []}
            windowHours={windowHours}
            up={{ field: 'disk_read_bytes_per_second', label: 'read', color: 'var(--disk-read)' }}
            down={{ field: 'disk_write_bytes_per_second', label: 'write', color: 'var(--disk-write)' }}
          />
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Internet activity</h2>
          <div className="chart-meta">
            <span className="chart-unit">data per second</span>
            <div className="legend">
              <span><i className="swatch swatch-net-recv" /> received (above)</span>
              <span><i className="swatch swatch-net-sent" /> sent (below)</span>
            </div>
          </div>
        </div>
        {telemetry.error ? (
          <div className="chart-empty">Internet activity is unavailable right now.</div>
        ) : (
          // Received above, sent below — matching the download-up/upload-down
          // convention every network monitor uses, so the shape reads the way
          // people already expect.
          <IoChart
            rows={telemetry.data ?? []}
            windowHours={windowHours}
            up={{ field: 'network_bytes_received_per_second', label: 'received', color: 'var(--net-recv)' }}
            down={{ field: 'network_bytes_sent_per_second', label: 'sent', color: 'var(--net-sent)' }}
          />
        )}
      </section>
    </>
  )
}

/**
 * The machine itself, on a timescale of months and years.
 *
 * Manufacturing carbon and battery wear had no business sitting next to a
 * chart that redraws every 1.5 seconds — the placement implied they were the
 * same kind of fact. Here they are the only kind of fact.
 */
export interface SessionInfo {
  mode: 'user' | 'it'
  /**
   * How IT mode was reached, null when the session is a user one.
   *
   * 'unlocked' came from the button and can be undone from the button.
   * 'flag' came from `--mode it` on the command line, and cannot: the flag is
   * re-read on every request, so clearing the stored preference would change
   * nothing. The UI needs the difference to avoid offering a way out that
   * silently fails.
   */
  it_mode_source: 'flag' | 'unlocked' | null
  machine_model: string | null
  /** 'entered' means somebody typed the coefficients in rather than sweeping
   *  them. Never folded into 'measured' — see models/calibration.py. */
  calibration_source: 'measured' | 'entered' | 'estimated' | null
  calibration_notes: string
  calibrated_at: string | null
  setup_state: 'calibrated' | 'entered' | 'estimated' | 'unconfigured'
  /** Whether THIS account can write hardware.db. The real gate is filesystem
   *  permission, not the --mode flag, so the form asks before offering. */
  calibration_writable: boolean
  calibration_acknowledged: boolean
  it_wizard_completed: boolean
}

function MachineView() {
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>Before you used it</h2>
          <div className="legend">
            <span className="muted">making the machine · battery health</span>
          </div>
        </div>
        <LifecyclePanel days={7} />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Apps left running</h2>
          <div className="legend">
            <span className="muted">developer tools · memory · activity while away</span>
          </div>
        </div>
        <WorkloadsPanel />
      </section>
    </>
  )
}

function SetupView({ session, onLeaveItMode, leaving }: {
  session: SessionInfo | null
  /** Owned by App, because the topbar badge offers the same exit. */
  onLeaveItMode?: () => void
  leaving?: boolean
}) {
  const [wizardDone, setWizardDone] = useState(session?.it_wizard_completed ?? false)
  const [unlocking, setUnlocking] = useState(false)
  const [unlockError, setUnlockError] = useState<string | null>(null)

  // Sync local state with the session data — when the wizard-complete endpoint
  // is called, the session will update and we need to reflect that change.
  useEffect(() => {
    setWizardDone(session?.it_wizard_completed ?? false)
  }, [session?.it_wizard_completed])

  // Reloading rather than re-rendering on the new session: switching mode
  // changes which tabs exist and what half the panels are allowed to show, and
  // several of them hold their own polled state. A reload is the honest way to
  // start again as the other kind of session.
  async function unlock() {
    setUnlocking(true)
    setUnlockError(null)
    try {
      const response = await fetch('/api/session/unlock-it', { method: 'POST' })
      if (response.ok) {
        window.location.reload()
        return
      }
      const payload = await response.json().catch(() => ({}))
      setUnlockError(payload.detail ?? `${response.status} ${response.statusText}`)
    } catch (cause: unknown) {
      setUnlockError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setUnlocking(false)
    }
  }

  if (!session) {
    return <div className="chart-empty">Checking setup access…</div>
  }

  // The way out is passed to the wizard as well as the panel. The wizard
  // renders INSTEAD of the panel, so on a machine that never completed it the
  // panel's exit was unreachable and IT mode was a one-way door — which is
  // exactly how it was found.
  if (session.mode === 'it' && !wizardDone) {
    return (
      <ITSetupWizard
        session={session}
        onComplete={() => setWizardDone(true)}
        onLeaveItMode={onLeaveItMode}
        leaving={leaving}
      />
    )
  }

  return (
    <>
      {unlockError && <p className="calibration-error">{unlockError}</p>}

      {session.mode === 'it' ? (
        <>
          <SetupPanel
            session={session}
            onReplayWizard={() => setWizardDone(false)}
            onLeaveItMode={onLeaveItMode}
            leaving={leaving}
          />
          {/* No hand-off of the sweep's numbers into the form: the sweep
              already stored them as "measured", and the form saves as
              "entered". Pre-filling it would invite somebody to re-save a
              measurement as a typed value and quietly downgrade it. */}
          <CalibrationPanel />
        </>
      ) : (
        <section className="setup-access">
          <p className="eyebrow">IT setup</p>
          <h2>Setup is available in this app</h2>
          {session.calibration_writable ? (
            <>
              <p>
                You have permission to manage calibration profiles for this fleet.
                Click below to unlock IT setup mode.
              </p>
              <button
                className="unlock-it-button"
                onClick={unlock}
                disabled={unlocking}
              >
                {unlocking ? 'Unlocking…' : '🔓 Unlock IT Mode'}
              </button>
              <p className="setup-note">
                You can leave IT setup at any time from the badge next to the
                app name, on any view.
              </p>
            </>
          ) : (
            <>
              <p>
                You are viewing the regular user session. IT setup can be opened
                here when the app is started with IT access.
              </p>
              <code>python -m GreenIT.agent --mode it</code>
            </>
          )}
        </section>
      )}
    </>
  )
}

function SetupPanel({ session, onReplayWizard, onLeaveItMode, leaving }: {
  session: SessionInfo
  /** Absent on the banner shown above other views, where re-opening a
   *  five-step walkthrough over somebody's dashboard would be an ambush. */
  onReplayWizard?: () => void
  /** Absent when IT mode came from `--mode it`, which no button can undo. */
  onLeaveItMode?: () => void
  leaving?: boolean
}) {
  const isReady = session.setup_state === 'calibrated'
  // 'entered' is configured but not measured. Folding it into either
  // neighbour would either overstate it as a sweep or understate a profile
  // somebody deliberately set.
  const isEntered = session.setup_state === 'entered'
  return (
    <section className="setup-panel" aria-labelledby="setup-title">
      <div className="setup-panel-head">
        <div>
          <p className="eyebrow">IT setup</p>
          <h2 id="setup-title">Prepare this machine</h2>
        </div>
        <span className={`setup-state setup-state-${session.setup_state}`}>
          {isReady ? 'Ready'
            : isEntered ? 'Entered by hand'
            : session.setup_state === 'estimated' ? 'Using an estimate'
            : 'Needs setup'}
        </span>
      </div>
      <div className="setup-details">
        <div><span>Machine</span><strong>{session.machine_model ?? 'Not identified'}</strong></div>
        <div><span>Profile</span><strong>{
          isReady ? 'Measured for this model'
            : isEntered ? 'Entered by hand, not swept'
            : 'Estimated from CPU class'
        }</strong></div>
        {session.calibrated_at && (
          <div><span>Recorded</span><strong>{new Date(session.calibrated_at).toLocaleDateString()}</strong></div>
        )}
      </div>
      <p className="setup-copy">
        {isReady
          ? 'This machine already has a measured profile. The user session can use the dashboard with trusted model data.'
          : isEntered
            ? 'Coefficients for this model were typed in rather than swept. Trends are sound; absolute watts are only as good as the numbers entered. A sweep replaces them.'
            : 'This machine has no stored profile yet, so coefficients are scaled from its CPU class. Add one below, or run the sweeps for a measured profile.'}
      </p>
      {/* Points at the automated sweep, which is also what the wizard's
          button runs. The older run_calibration entry point drives the CPU by
          asking an operator to do it by hand, so naming it here would send
          somebody to a procedure the button already performs. */}
      {!isReady && (
        <code className="setup-command">
          python -m GreenIT.scripts.calibration.auto_calibration
        </code>
      )}
      <p className="setup-note">
        A stored profile is never permanent — adding, replacing or removing one
        here changes what this machine uses from the next restart.
      </p>
      {/*
        The walkthrough is shown once, which is right for somebody setting a
        machine up and wrong for everybody else: an operator who wants to
        re-read how calibration works, or who is showing it to a colleague,
        had no route back to it short of editing the settings table by hand.

        Re-opening it is a display change and nothing else. The completion
        flag stays set, so this does not resurrect the wizard for the next
        session — it reopens it for the person asking, now.
      */}
      <div className="setup-footer-actions">
        {onReplayWizard && (
          <button type="button" className="setup-replay" onClick={onReplayWizard}>
            ↻ Replay the walkthrough
          </button>
        )}
        {/*
          Leaving is offered whether or not the machine was ever set up.
          Gating it on a finished calibration would trap somebody who opened
          this tab to look, in a screen built for a job they decided not to
          do — and nothing here is dangerous to leave half-done: a profile is
          either stored or it is not.
        */}
        {onLeaveItMode && (
          <button
            type="button"
            className="setup-replay"
            onClick={onLeaveItMode}
            disabled={leaving}
          >
            {leaving ? 'Switching…' : '← Return to the employee view'}
          </button>
        )}
      </div>
    </section>
  )
}

/** Never receives null: the caller now requires a resolved session, so the
 *  "setup needed" wording can no longer stand in for "not asked yet". */

/**
 * Shown once, before the user has been told how their figures are derived.
 *
 * WHY IT IS AN ACKNOWLEDGEMENT AND NOT A CHOICE
 * The obvious design offers "use the fallback" or "wait for IT calibration",
 * but the second has nowhere to go: sweeps take hours under controlled
 * conditions, and until one runs the only alternative to estimated
 * coefficients is no absolute numbers at all. A modal whose second button
 * cannot do anything is worse than no modal.
 *
 * So it states the basis plainly and offers one real action plus a route to
 * the explanation. It returns whenever that basis changes - a fallback
 * replaced by typed coefficients is a different claim about the numbers, and
 * consent to the first is not consent to the second.
 */
function CalibrationIntro({ session, onAcknowledge }: {
  session: SessionInfo
  onAcknowledge: () => void
}) {
  const estimated = session.setup_state === 'estimated'

  async function accept(thenGuide: boolean) {
    try {
      await fetch('/api/session/acknowledge', { method: 'POST' })
    } finally {
      // Dismiss regardless: a failed write means it asks again next time,
      // which is a far better failure than a banner that cannot be closed.
      if (thenGuide) onAcknowledge()
      else window.location.reload()
    }
  }

  return (
    <section className="calibration-intro">
      <p className="eyebrow">Before you start</p>
      <h2>{estimated
        ? 'This model has not been calibrated yet'
        : 'This machine uses hand-entered calibration'}</h2>
      <p>
        {estimated
          ? 'Power figures are scaled from the CPU class of this machine rather than measured on it. Day-to-day trends and the share of energy wasted are reliable; the absolute watts carry an unknown error until IT runs a calibration.'
          : 'Coefficients for this model were typed in rather than produced by a battery-discharge sweep. The figures are only as good as the numbers entered.'}
      </p>
      <div className="calibration-intro-actions">
        <button type="button" onClick={() => accept(false)}>Got it — continue</button>
        <button type="button" className="secondary" onClick={() => accept(true)}>
          How the numbers are made
        </button>
      </div>
    </section>
  )
}

function SetupNotice({ session }: { session: SessionInfo }) {
  return (
    <section className="setup-notice">
      <span className="setup-notice-mark">!</span>
      <div>
        <strong>{session.setup_state === 'estimated' ? 'Using an estimated profile' : 'Machine setup is needed'}</strong>
        <p>{session.setup_state === 'estimated'
          ? 'Your trends still work, but the power numbers are best used to compare this machine with itself.'
          : 'Ask IT to calibrate this machine so its power numbers are more accurate.'}</p>
      </div>
    </section>
  )
}

function GuideView() {
  return (
    <div className="guide">
      <section className="guide-intro">
        <p className="eyebrow">Using EcoInsight</p>
        <h1>What your numbers mean</h1>
        <p>
          EcoInsight estimates how much power this machine uses and the carbon
          linked to it. Use Today for a quick answer, Live to see details, and
          Machine to learn how the estimates are made.
        </p>
      </section>

      <section className="guide-section">
        <div className="guide-section-head">
          <p className="eyebrow">At a glance</p>
          <h2>The five numbers you see first</h2>
        </div>
        <div className="guide-grid">
          <GuideCard title="Power right now" marker="W">
            How much power the machine is estimated to use at this moment. A
            higher number means more electricity is being used now.
          </GuideCard>
          <GuideCard title="Energy this session" marker="Wh">
            The total electricity used since EcoInsight started. This grows as
            the machine keeps running.
          </GuideCard>
          <GuideCard title="Carbon this session" marker="CO₂">
            The estimated carbon linked to this session’s energy use. It is
            shown in grams so it is easier to understand and compare.
          </GuideCard>
          <GuideCard title="Screen" marker="%">
            The latest screen brightness and number of monitors. If the screen
            cannot report its brightness, EcoInsight leaves the value blank.
          </GuideCard>
          <GuideCard title="Updated" marker="TIME">
            When EcoInsight last received a reading. Use this to tell a quiet
            machine apart from one that has stopped sending data.
          </GuideCard>
        </div>
      </section>

      <section className="guide-section">
        <div className="guide-section-head">
          <p className="eyebrow">Reading the charts</p>
          <h2>What the charts show</h2>
        </div>
        <div className="guide-list">
          <GuideRow title="Power use" color="chart-guide-cpu">
            The colors show where the power goes: the machine itself, apps,
            and memory. Empty spaces mean no reading was saved, not zero use.
          </GuideRow>
          <GuideRow title="Computer activity" color="chart-guide-ram">
            CPU and memory show how busy the machine is, from 0% to 100%.
            Brightness is a screen setting, so it uses a dashed line.
          </GuideRow>
          <GuideRow title="Files and internet" color="chart-guide-io">
            Reading files and receiving data appear above the centre line.
            Writing files and sending data appear below it. Taller means more
            data moved each second.
          </GuideRow>
        </div>
      </section>

      <section className="guide-section guide-notes">
        <div className="guide-section-head">
          <p className="eyebrow">About the numbers</p>
          <h2>What to keep in mind</h2>
        </div>
        <div className="guide-notes-grid">
          <GuideCard title="These are estimates" marker="MODEL">
            EcoInsight calculates power from a profile for this machine. The
            Machine tab tells you whether that profile was measured or estimated.
          </GuideCard>
          <GuideCard title="Not everything updates together" marker="LIVE">
            Power updates about every 1.5 seconds. App activity and suggestions
            update less often so monitoring uses very little power itself.
          </GuideCard>
          <GuideCard title="Gaps are honest" marker="GAP">
            A gap means EcoInsight was paused, the machine was asleep, or a
            sensor was unavailable. We do not fill gaps with made-up values.
          </GuideCard>
        </div>
      </section>
    </div>
  )
}

function GuideCard({ title, marker, children }: { title: string; marker: string; children: string }) {
  return (
    <article className="guide-card">
      <span className="guide-marker">{marker}</span>
      <h3>{title}</h3>
      <p>{children}</p>
    </article>
  )
}

function GuideRow({ title, color, children }: { title: string; color: string; children: string }) {
  return (
    <article className="guide-row">
      <span className={`guide-row-marker ${color}`} />
      <div>
        <h3>{title}</h3>
        <p>{children}</p>
      </div>
    </article>
  )
}

export default App
