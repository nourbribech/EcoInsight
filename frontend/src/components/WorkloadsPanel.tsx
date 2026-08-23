import { usePolling } from '../hooks/usePolling'
import type { Workloads } from '../types/api'

/** The server caches the live reading for 60s; polling faster refetches it. */
const POLL_MS = 120_000

const GB = 1024 ** 3

/**
 * Developer workloads left running — today, WSL distributions.
 *
 * A distribution left up is the developer's version of a machine left awake:
 * nothing on the desktop shows it, the only trace is a process called
 * vmmemWSL, and it can sit there for days.
 *
 * The panel is careful about what it claims. An IDLE distribution costs
 * almost no electricity — hundredths of a watt of CPU, and a memory
 * coefficient this project measured as indistinguishable from zero — so it is
 * reported as reclaimable MEMORY. A BUSY, unattended one is real energy, and
 * only that case gets watts attached to it. The server draws the distinction;
 * this renders it.
 */
export function WorkloadsPanel() {
  const { data, error, loading } = usePolling<Workloads>('/api/workloads', POLL_MS)

  if (loading) return <div className="chart-empty">Checking developer workloads…</div>
  if (error) return <div className="chart-empty">Workloads unavailable: {error}</div>
  if (!data) return null

  if (!data.wsl.available) {
    // "Could not ask" rendered as itself. Showing "nothing running" here would
    // be a claim about a machine we learned nothing about.
    return (
      <div className="chart-empty">
        No WSL on this machine — nothing to report. Containers and virtual
        machines are not tracked yet.
      </div>
    )
  }

  const { vm } = data.wsl

  return (
    <div className="workloads">
      <div className="workload-figures">
        <Figure
          label="Distributions"
          value={`${data.wsl.running.length} of ${data.wsl.installed.length} running`}
          detail={data.wsl.installed.join(', ') || 'none installed'}
        />
        <Figure
          label="Memory held"
          value={vm.memory_bytes === null ? '—' : `${(vm.memory_bytes / GB).toFixed(1)} GB`}
          detail={vm.running ? 'by the shared WSL utility VM' : 'VM not running'}
        />
        <Figure
          label="CPU"
          // Null is the first sample after a restart, which has no baseline.
          // An em dash says "not measured"; 0.0% would say "measured, idle".
          value={vm.cpu_percent === null ? '—' : `${vm.cpu_percent.toFixed(1)}%`}
          detail={
            data.history.samples > 0 && data.history.peak_cpu_percent !== null
              ? `peak ${data.history.peak_cpu_percent.toFixed(1)}% over ${data.history.observed_hours.toFixed(0)} h`
              : 'no history yet'
          }
        />
        <Figure
          label="Up for"
          value={vm.uptime_seconds === null ? '—' : formatUptime(vm.uptime_seconds)}
          detail={
            vm.attached_sessions > 0
              ? `${vm.attached_sessions} session${vm.attached_sessions === 1 ? '' : 's'} attached`
              : 'no session attached'
          }
        />
      </div>

      {/*
        The findings this endpoint also returns are rendered by ActionsPanel,
        ranked against the configuration ones. Repeating them here would put
        the same advice in two places on two tabs, which is the fragmentation
        the merge was meant to end. This panel keeps the measurements.
      */}

      {/*
        WSL2 runs every distribution in ONE utility VM, so the figures above
        cover all of them together. Stating that beats letting a reader assume
        a per-distribution breakdown that the host cannot produce.
      */}
      <p className="workload-note">
        WSL2 runs all running distributions inside a single utility VM, so CPU
        and memory here describe that VM as a whole
        {data.wsl.running.length > 1 && ' — with more than one running, no figure is attributable to a single distribution'}
        .{data.wsl.docker && ' Docker Desktop containers run inside it too and are counted in these totals.'}
      </p>
    </div>
  )
}

function formatUptime(seconds: number): string {
  const hours = seconds / 3600
  if (hours < 1) return `${(seconds / 60).toFixed(0)} min`
  if (hours < 48) return `${hours.toFixed(0)} h`
  return `${(hours / 24).toFixed(1)} d`
}

function Figure({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="workload-figure">
      <span className="stat-label">{label}</span>
      <span className="workload-value">{value}</span>
      <span className="stat-detail">{detail}</span>
    </div>
  )
}
