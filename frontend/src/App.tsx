import { useState } from 'react'
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
type View = 'today' | 'live' | 'machine'

const VIEWS: { id: View; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'live', label: 'Live' },
  { id: 'machine', label: 'This machine' },
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

function App() {
  const [view, setView] = useState<View>('today')

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

  const latest = rows[rows.length - 1]
  const latestTelemetry = telemetry.data?.[telemetry.data.length - 1]

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
            {status === 'live' && 'live'}
            {status === 'loading' && 'loading…'}
            {status === 'error' && `agent unreachable: ${error}`}
          </span>
        </div>

        <nav className="view-nav">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              className={v.id === view ? 'active' : ''}
              aria-current={v.id === view ? 'page' : undefined}
              onClick={() => setView(v.id)}
            >
              {v.label}
            </button>
          ))}
        </nav>
      </header>

      {view === 'today' && (
        <TodayView
          latest={latest}
          latestTelemetry={latestTelemetry}
          recommendations={recommendations}
        />
      )}

      {view === 'live' && (
        <LiveView
          rows={rows}
          telemetry={telemetry}
          windowHours={windowHours}
          onWindowChange={setWindowHours}
        />
      )}

      {view === 'machine' && <MachineView />}
    </div>
  )
}

/**
 * The verdict and what to do about it. Nothing here changes faster than
 * every couple of minutes, which is why none of it needs the window picker.
 */
function TodayView({
  latest, latestTelemetry, recommendations,
}: {
  latest: Measurement | undefined
  latestTelemetry: Telemetry | undefined
  recommendations: { data: Recommendation[] | null; error: string | null }
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
          <h2>This week's goal</h2>
          <div className="legend">
            <span className="muted">avoidable waste · Monday to Sunday · yours to set</span>
          </div>
        </div>
        <GoalPanel />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Your last 7 days</h2>
          <div className="legend">
            <span className="muted">energy · carbon · avoidable waste</span>
          </div>
        </div>
        <SummaryPanel days={7} />
      </section>

      {/*
        One ranked list, above the event feed. Standing findings outrank any
        single alert - fixing a setting once saves power every day
        afterwards - and ranking them against each other is the whole point:
        three unranked lists made the reader do the prioritising.
      */}
      <section className="panel">
        <div className="panel-head">
          <h2>What to do</h2>
          <div className="legend">
            <span className="muted">power settings · developer workloads · always current</span>
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
        <span className="live-controls-label">Window</span>
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
          {rows.length} samples · applies to the charts below
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
          <h2>Patterns</h2>
          <div className="legend">
            <span className="muted">last 7 days · fixed window</span>
          </div>
        </div>
        <PatternsPanel days={7} />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Top consumers</h2>
          <div className="legend">
            <span className="muted">CPU power attribution · updates every ~2 min</span>
          </div>
        </div>
        <ProcessTable />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>System power draw</h2>
          <div className="legend">
            <span><i className="swatch swatch-baseline" /> baseline</span>
            <span><i className="swatch swatch-cpu" /> cpu</span>
            <span><i className="swatch swatch-ram" /> ram</span>
          </div>
        </div>
        <PowerChart rows={rows} windowHours={windowHours} />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Resource utilisation</h2>
          <div className="legend">
            <span><i className="swatch swatch-cpu" /> cpu</span>
            <span><i className="swatch swatch-ram" /> ram</span>
            <span><i className="swatch swatch-brightness" /> brightness</span>
            {telemetry.data && <span className="muted">{telemetry.data.length} samples</span>}
          </div>
        </div>
        {telemetry.error ? (
          <div className="chart-empty">Telemetry unavailable: {telemetry.error}</div>
        ) : (
          <UtilizationChart rows={telemetry.data ?? []} windowHours={windowHours} />
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Disk I/O</h2>
          <div className="legend">
            <span><i className="swatch swatch-disk-read" /> read (above)</span>
            <span><i className="swatch swatch-disk-write" /> write (below)</span>
          </div>
        </div>
        {telemetry.error ? (
          <div className="chart-empty">Telemetry unavailable: {telemetry.error}</div>
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
          <h2>Network I/O</h2>
          <div className="legend">
            <span><i className="swatch swatch-net-recv" /> received (above)</span>
            <span><i className="swatch swatch-net-sent" /> sent (below)</span>
          </div>
        </div>
        {telemetry.error ? (
          <div className="chart-empty">Telemetry unavailable: {telemetry.error}</div>
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
function MachineView() {
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>Before it was switched on</h2>
          <div className="legend">
            <span className="muted">manufacturing carbon · battery health</span>
          </div>
        </div>
        <LifecyclePanel days={7} />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Left running</h2>
          <div className="legend">
            <span className="muted">WSL distributions · memory held · unattended CPU</span>
          </div>
        </div>
        <WorkloadsPanel />
      </section>
    </>
  )
}

export default App
