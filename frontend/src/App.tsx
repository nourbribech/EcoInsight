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
import { InsightsPanel } from './components/InsightsPanel'
import type { Recommendation, Telemetry } from './types/api'
import './dashboard.css'

const WINDOWS = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  // 7d is viable now that /api/history aggregates in SQL: the request went
  // from 18.7 MB of raw rows (which froze the tab) to 61 KB.
  { label: '7d', hours: 168 },
]

/** The estimation loop writes a measurement roughly every 2.6s. */
const MEASUREMENT_POLL_MS = 3000

/**
 * Telemetry is written every 120s (TELEMETRY_INTERVAL_SECONDS in
 * estimation_loop.py), so polling it faster than that just refetches
 * identical data. 30s keeps it feeling responsive without being wasteful.
 */
const TELEMETRY_POLL_MS = 30_000

function App() {
  // 6h rather than 1h: the agent isn't always running during development, so
  // a 1h default frequently shows an empty dashboard even though there's
  // plenty of recent data. Worth revisiting once the loop runs unattended —
  // Netdata can default to a short window precisely because its agent never
  // stops.
  const [windowHours, setWindowHours] = useState(6)

  // Measurements: seed-once-then-append, because the payload is large
  // (1.12 MB/24h) and updates every ~2.6s.
  const { rows, status, error } = useLiveSeries(windowHours, MEASUREMENT_POLL_MS)

  // Telemetry: a plain refetch on an interval — and that's the RIGHT call
  // here, not laziness. The seed-and-append pattern exists to avoid
  // re-downloading a big payload for one new row. Telemetry is the opposite
  // case: ~69 rows per day (about 12 KB) that change only every 120s, and
  // there's no single-row /api/telemetry/current endpoint to append from
  // anyway. Applying the complex pattern here would be cargo-culting it.
  //
  // This is what usePolling was built for, so we use it.
  const telemetry = usePolling<Telemetry[]>(
    `/api/telemetry?hours=${windowHours}`,
    TELEMETRY_POLL_MS,
  )

  // Recommendations are written only when telemetry is (every 120s), so
  // there's nothing to gain from polling them faster than telemetry itself.
  const recommendations = usePolling<Recommendation[]>(
    `/api/recommendations?hours=${windowHours}&limit=50`,
    TELEMETRY_POLL_MS,
  )

  const latest = rows[rows.length - 1]
  const latestTelemetry = telemetry.data?.[telemetry.data.length - 1]

  return (
    <div className="dashboard">
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">EcoInsight</span>
          <span className={`status status-${status}`}>
            {status === 'live' && `live · ${rows.length} samples`}
            {status === 'loading' && 'loading…'}
            {status === 'error' && `agent unreachable: ${error}`}
          </span>
        </div>

        <div className="window-picker">
          {WINDOWS.map((w) => (
            <button
              key={w.hours}
              type="button"
              className={w.hours === windowHours ? 'active' : ''}
              onClick={() => setWindowHours(w.hours)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </header>

      <StatsBar latest={latest} latestTelemetry={latestTelemetry} />

      {/*
        The digest sits first because it answers the question the user
        actually has — "am I doing better than last week?" — while everything
        below answers "what is happening right now". A tool for personal
        improvement should lead with the improvement.
      */}
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
        Standing findings, above the event feed: fixing a setting once saves
        power every day afterwards, which outranks any single alert.
      */}
      <section className="panel">
        <div className="panel-head">
          <h2>Fix once</h2>
          <div className="legend">
            <span className="muted">power settings · always current</span>
          </div>
        </div>
        <InsightsPanel />
      </section>

      {/*
        Recommendations sit above the charts deliberately. They're the
        actionable output of the whole pipeline — "here's what to do about it"
        belongs before "here's the raw telemetry", which is also where every
        monitoring tool puts its alarms.
      */}
      <section className="panel">
        <div className="panel-head">
          <h2>Recommendations</h2>
          <div className="legend">
            <span className="muted">
              avoidable waste · unattended jobs · load traced to one app
            </span>
          </div>
        </div>
        <RecommendationsFeed
          recommendations={recommendations.data}
          error={recommendations.error}
          windowHours={windowHours}
        />
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
    </div>
  )
}

export default App
