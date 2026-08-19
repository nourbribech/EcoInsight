import { useMemo } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Telemetry } from '../types/api'
import { bucketByTime, findGaps, formatBytesPerSecond, formatTime } from '../lib/series'

const MAX_BUCKETS = 700

/** A numeric throughput column of the telemetry table. */
type ThroughputField = Extract<keyof Telemetry, string>

interface Direction {
  field: ThroughputField
  label: string
  /** A CSS custom property reference, e.g. "var(--disk-read)". */
  color: string
}

interface Props {
  rows: Telemetry[]
  windowHours: number
  /** Plotted above the zero line. */
  up: Direction
  /** Plotted below the zero line (values are negated for you). */
  down: Direction
}

/**
 * A mirrored throughput chart for a pair of opposed byte-rate metrics —
 * disk read/write, network received/sent.
 *
 * This started as DiskIoChart, hardcoded to the disk columns. Network I/O is
 * the second caller with an identical shape, which is the point at which
 * generalising pays for itself. Both callers were written before the
 * abstraction, so its shape is derived from two real cases rather than
 * guessed from one.
 */
export function IoChart({ rows, windowHours, up, down }: Props) {
  const points = useMemo(() => {
    const bucketed = bucketByTime(rows, [up.field, down.field] as const, MAX_BUCKETS)

    // MIRRORING: one direction plots upward, the other downward.
    //
    // These metrics are near-constantly both non-zero, so drawn on the same
    // side they overlap into an unreadable smear. Negating one sends it below
    // the axis, which separates them completely and makes the direction of
    // traffic readable at a glance. Standard idiom for paired bidirectional
    // metrics — Netdata does the same.
    //
    // The cost: the `down` series now carries negative numbers, so every
    // place a value is DISPLAYED must take Math.abs. That's what
    // formatBytesPerSecond does internally.
    return bucketed.map((point) => {
      const downValue = point[down.field]
      return {
        ...point,
        [down.field]: downValue === null ? null : -downValue,
      }
    })
  }, [rows, up.field, down.field])

  // A SYMMETRIC domain, from the larger of the two directions.
  //
  // If each direction auto-scaled to its own peak, a 42 MB/s read and a
  // 16 MB/s write would render at the same height — implying they were
  // equal. One shared scale keeps the halves genuinely comparable.
  const bound = useMemo(() => {
    const magnitudes = points.flatMap((point) => [
      Math.abs(Number(point[up.field] ?? 0)),
      Math.abs(Number(point[down.field] ?? 0)),
    ])
    // Guard the all-zero case, which would give a degenerate [0, 0] domain.
    return Math.max(...magnitudes, 1024)
  }, [points, up.field, down.field])

  const gaps = useMemo(() => findGaps(points, up.field), [points, up.field])

  if (points.length === 0) {
    return <div className="chart-empty">No telemetry in this window.</div>
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" vertical={false} />

        {/* Stretches where the agent wasn't collecting — see PowerChart. */}
        {gaps.map((gap) => (
          <ReferenceArea
            key={gap.x1} x1={gap.x1} x2={gap.x2}
            fill="var(--gap)" fillOpacity={1} stroke="none"
          />
        ))}

        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(t) => formatTime(Number(t), windowHours)}
          tick={{ fontSize: 11, fill: 'var(--muted)' }}
          minTickGap={60}
        />

        {/*
          LINEAR, NOT LOG — despite these metrics spanning four to five orders
          of magnitude, which is exactly what a log axis is for.

          Ruled out by the data: roughly half of the disk-read samples and a
          quarter of the network samples are EXACTLY zero, and log(0) is
          undefined. Recharts turns those into NaN and silently drops them,
          so a large fraction of the series would vanish.

          Going log anyway would mean clamping zeros up to a floor (say
          1 B/s), which draws activity during periods that were genuinely
          idle. Spiky-but-truthful beats smooth-but-invented.

          scale="sqrt" is the honest middle ground if the linear version
          proves too flat — sqrt(0) is 0, so it handles the zeros natively.
        */}
        <YAxis
          domain={[-bound, bound]}
          tickFormatter={(v) => formatBytesPerSecond(Number(v))}
          width={68}
          tick={{ fontSize: 11, fill: 'var(--muted)' }}
        />

        {/* The zero line is the mirror axis, so it should be visible. */}
        <ReferenceLine y={0} stroke="var(--border)" />

        <Tooltip
          labelFormatter={(label) => formatTime(Number(label), windowHours)}
          formatter={(value, name) => [formatBytesPerSecond(Number(value)), String(name)]}
          contentStyle={{
            background: 'var(--panel)',
            border: '1px solid var(--border)',
            fontSize: 12,
          }}
        />

        {/*
          type="linear", NOT "monotone" like the power chart.

          Monotone interpolation draws smooth curves between points and can
          overshoot — inventing values that were never measured. On slowly
          varying averaged power data that's cosmetic. On burst-shaped I/O
          it's a lie: it rounds off the very spikes that are the whole
          signal, and implies gradual ramps where there was an instantaneous
          jump from idle to peak.
        */}
        <Area
          dataKey={up.field} name={up.label} type="linear"
          stroke={up.color} fill={up.color} fillOpacity={0.3}
          strokeWidth={1.2} isAnimationActive={false} connectNulls={false}
        />
        <Area
          dataKey={down.field} name={down.label} type="linear"
          stroke={down.color} fill={down.color} fillOpacity={0.3}
          strokeWidth={1.2} isAnimationActive={false} connectNulls={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
