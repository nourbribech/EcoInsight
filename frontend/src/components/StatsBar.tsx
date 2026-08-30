import type { Measurement, Telemetry } from '../types/api'

interface Props {
  latest: Measurement | undefined
  /**
   * Latest telemetry row. Separate from `latest` because the two tables are
   * written on different cadences — measurements every ~1.5s, telemetry every
   * 120s — so they are genuinely different points in time and merging them
   * into one prop would hide that.
   */
  latestTelemetry: Telemetry | undefined
}

/**
 * The current-values row at the top of the dashboard.
 *
 * NOTE THE SHAPE CHANGE: this no longer fetches anything. It used to call
 * usePolling('/api/current') itself, which meant the tiles and the chart
 * each ran their own independent poll on their own schedule — so the number
 * in the tile could disagree with the right-hand edge of the chart.
 *
 * Now App owns the data and passes the latest row down. This component is
 * pure presentation: same props always render the same output, no network,
 * no state. That's the pattern to reach for by default — fetch high, render
 * low — and it's what keeps every panel on a dashboard consistent with
 * every other panel.
 */
export function StatsBar({ latest, latestTelemetry }: Props) {
  if (!latest) {
    return <div className="stats-bar">Waiting for the first measurement…</div>
  }

  return (
    <div className="stats-bar">
      <Stat
        label="Power right now"
        value={`${latest.total_watts.toFixed(2)} W`}
        detail={
          `apps ${latest.cpu_watts.toFixed(1)} · ` +
          `memory ${latest.ram_watts.toFixed(1)} · ` +
          `machine ${latest.baseline_watts.toFixed(1)}`
        }
      />
      <Stat
        label="Energy this session"
        value={`${latest.cumulative_watt_hours.toFixed(1)} Wh`}
        detail={`${(latest.cumulative_watt_hours / 1000).toFixed(3)} kWh`}
      />
      <Stat
        // The DB column is cumulative_kg_co2eq — in KILOgrams. The previous
        // version printed it straight out labelled "gCO2eq", under-reporting
        // by 1000x. The estimation loop's own console output already does
        // this same x1000 conversion.
        label="Carbon this session"
        value={`${(latest.cumulative_kg_co2eq * 1000).toFixed(1)} g`}
        detail="estimated from the local grid"
      />
      <Stat
        label="Screen"
        value={formatBrightness(latestTelemetry)}
        detail={formatMonitors(latestTelemetry)}
      />
      <Stat
        label="Updated"
        value={new Date(latest.timestamp).toLocaleTimeString()}
        detail="latest reading"
      />
    </div>
  )
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      <span className="stat-detail">{detail}</span>
    </div>
  )
}

/**
 * Brightness is nullable twice over: the telemetry row may not have arrived
 * yet, and a panel that does not answer DDC/CI reports null rather than a
 * number. Both render as an em dash — showing "0%" would claim the screen is
 * off, which is a different and alarming statement.
 */
function formatBrightness(telemetry: Telemetry | undefined): string {
  if (!telemetry || telemetry.brightness_percent === null) return '—'
  return `${telemetry.brightness_percent}%`
}

function formatMonitors(telemetry: Telemetry | undefined): string {
  if (!telemetry || telemetry.monitor_count === null) return 'screen details unavailable'
  const count = telemetry.monitor_count
  return `${count} ${count === 1 ? 'monitor' : 'monitors'}`
}
