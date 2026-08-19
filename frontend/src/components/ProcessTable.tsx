import { usePolling } from '../hooks/usePolling'
import type { ProcessSample } from '../types/api'

/**
 * Telemetry cadence is 120s, so this sample only changes every two minutes.
 * Polling faster would refetch identical rows.
 */
const POLL_MS = 30_000

function formatMemory(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  return `${Math.round(bytes / 1e6)} MB`
}

export function ProcessTable() {
  const { data, error, loading } = usePolling<ProcessSample[]>(
    '/api/processes?limit=10',
    POLL_MS,
  )

  if (loading) return <div className="chart-empty">Loading…</div>
  if (error) return <div className="chart-empty">Unavailable: {error}</div>
  if (!data || data.length === 0) {
    return (
      <div className="chart-empty">
        No sample yet — the first one lands within ~2 minutes of the agent starting.
      </div>
    )
  }

  // Scale bars against the busiest app rather than against total CPU power:
  // the top row should always fill the column, so the eye compares the
  // applications with each other instead of against an invisible ceiling.
  const peak = Math.max(...data.map((row) => row.estimated_watts), 0.0001)

  return (
    <table className="process-table">
      <thead>
        <tr>
          <th>Application</th>
          <th className="num">CPU</th>
          <th className="num">Memory</th>
          <th className="num">Power</th>
        </tr>
      </thead>
      <tbody>
        {data.map((row) => (
          <tr key={row.name}>
            {/* The raw exe name stays on the title attribute: the label is
                what a person can act on, but "Windows Services" covers a
                dozen different svchost.exe roles, so the original has to
                remain reachable for anyone actually debugging. */}
            <td title={row.name}>
              {row.label}
              {/* Browsers and editors run dozens of children; showing the
                  count explains why one "application" outweighs the rest. */}
              {row.instances > 1 && <span className="instances"> ×{row.instances}</span>}
            </td>
            <td className="num">{row.cpu_percent.toFixed(1)}%</td>
            <td className="num">{formatMemory(row.memory_bytes)}</td>
            <td className="num watts">
              <span
                className="bar"
                style={{ width: `${(row.estimated_watts / peak) * 100}%` }}
              />
              <span className="bar-label">{row.estimated_watts.toFixed(2)} W</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
