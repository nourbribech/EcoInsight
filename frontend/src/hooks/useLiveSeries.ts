import { useEffect, useState } from 'react'
import type { Measurement, CurrentResponse } from '../types/api'
import { isMeasurement } from '../types/api'
import { trimToWindow } from '../lib/series'

export type ConnectionStatus = 'loading' | 'live' | 'error'

interface LiveSeries {
  rows: Measurement[]
  status: ConnectionStatus
  error: string | null
}

/**
 * Owns the measurement window the whole dashboard draws from.
 *
 * THE CENTRAL DESIGN DECISION
 * The naive approach is to poll /api/history?hours=24 on an interval. That
 * re-downloads 1.12 MB of JSON every couple of seconds to learn about ONE
 * new row. At a 2s interval that's ~560 KB/s of parsing, forever, for a
 * dashboard that might sit open all day.
 *
 * So we split it in two, which is how Netdata and every other agent-style
 * dashboard does it:
 *
 *   1. Fetch the window's history ONCE, when the window changes.
 *   2. Then poll only /api/current — a single row — and append it.
 *
 * Cost per tick drops from ~1.12 MB to ~300 bytes.
 *
 * The seed request also asks the server to downsample (`buckets`), which is
 * what makes long windows viable at all: 7 days of raw rows is ~18.7 MB and
 * freezes the tab, versus ~61 KB aggregated in SQL. Client-side downsampling
 * cannot substitute for this — the cost is in transferring and parsing rows
 * that then get thrown away.
 */

/** Matches the client-side chart budget; a chart is ~800px wide. */
const SERVER_BUCKETS = 700
export function useLiveSeries(hours: number, pollMs: number): LiveSeries {
  const [rows, setRows] = useState<Measurement[]>([])
  const [status, setStatus] = useState<ConnectionStatus>('loading')
  const [error, setError] = useState<string | null>(null)

  // --- 1. Seed the window ------------------------------------------------
  // Runs on mount and again whenever `hours` changes (the window selector).
  useEffect(() => {
    // `cancelled` guards against a race: if the user switches from 24h to 1h
    // while the 24h request is still in flight, the slow response must not
    // land after the fast one and overwrite it with stale data. React would
    // also warn about setting state on an unmounted component.
    let cancelled = false

    setStatus('loading')

    fetch(`/api/history?hours=${hours}&buckets=${SERVER_BUCKETS}`)
      .then((response) => {
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
        return response.json() as Promise<Measurement[]>
      })
      .then((history) => {
        if (cancelled) return
        setRows(history)
        setStatus('live')
        setError(null)
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setStatus('error')
      })

    return () => {
      cancelled = true
    }
  }, [hours])

  // --- 2. Append the live tail -------------------------------------------
  useEffect(() => {
    let cancelled = false

    async function tick() {
      try {
        const response = await fetch('/api/current')
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)

        const latest = (await response.json()) as CurrentResponse
        if (cancelled) return

        // The loop may have written nothing yet, in which case api.py
        // returns `{}` rather than an error.
        if (!isMeasurement(latest)) return

        setRows((previous) => {
          // THE FUNCTIONAL UPDATE MATTERS HERE.
          // This callback lives inside a setInterval created once, on mount.
          // If we wrote `setRows([...rows, latest])`, `rows` would be the
          // value captured when the interval was created — the empty array,
          // forever. That's the classic stale-closure bug. Passing a
          // function makes React hand us the *current* value instead, so the
          // interval never needs to be recreated to see fresh state.

          // We poll faster than the loop ticks, so most responses repeat the
          // row we already have. Appending blindly would pile up duplicates.
          const newest = previous[previous.length - 1]
          if (newest && Date.parse(latest.timestamp) <= Date.parse(newest.timestamp)) {
            // Returning the SAME array reference tells React nothing changed,
            // so it skips the re-render entirely. Returning `[...previous]`
            // here would re-render every poll for no reason.
            return previous
          }

          return trimToWindow([...previous, latest], hours)
        })

        setStatus('live')
        setError(null)
      } catch (cause: unknown) {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setStatus('error')
      }
    }

    const id = setInterval(tick, pollMs)

    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [hours, pollMs])

  return { rows, status, error }
}
