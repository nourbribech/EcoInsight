import { useMemo } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Measurement } from '../types/api'
import { bucketByTime, findGaps, formatTime } from '../lib/series'

/** Roughly one point per pixel of chart width. Past this, extra points are
 *  invisible — see the reasoning in lib/series.ts. */
const MAX_BUCKETS = 700

/** The columns we average, as a const tuple so the point type is inferred. */
const FIELDS = ['cpu_watts', 'ram_watts', 'baseline_watts'] as const

interface Props {
  rows: Measurement[]
  windowHours: number
}

export function PowerChart({ rows, windowHours }: Props) {
  // Bucketing 3,000+ rows on every render would redo the same work each time
  // the parent re-renders for an unrelated reason. useMemo recomputes only
  // when the inputs actually change — i.e. when a new row arrives.
  const points = useMemo(() => bucketByTime(rows, FIELDS, MAX_BUCKETS), [rows])
  // Any of the bucketed fields works — they're all null in exactly the same
  // buckets, since a bucket is either empty or has every column averaged.
  const gaps = useMemo(() => findGaps(points, 'cpu_watts'), [points])

  if (points.length === 0) {
    return <div className="chart-empty">No power readings for this time range.</div>
  }

  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" vertical={false} />

        {/*
          Shade the stretches where the agent wasn't collecting. Rendered
          before the Areas so it sits behind them. Without this, the break in
          the line reads as a rendering fault rather than as missing data.
        */}
        {gaps.map((gap) => (
          <ReferenceArea
            key={gap.x1}
            x1={gap.x1}
            x2={gap.x2}
            fill="var(--gap)"
            fillOpacity={1}
            stroke="none"
          />
        ))}

        {/*
          type="number" + scale="time" gives a TRUE time axis: points are
          positioned by their real timestamp. The default category axis would
          space every point evenly and render your multi-hour suspend gaps as
          if they were 2-second gaps.
        */}
        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(t: number) => formatTime(t, windowHours)}
          tick={{ fontSize: 11, fill: 'var(--muted)' }}
          minTickGap={60}
        />

        <YAxis
          unit=" W"
          width={56}
          tick={{ fontSize: 11, fill: 'var(--muted)' }}
        />

        <Tooltip
          // Recharts types these callbacks very loosely (label is ReactNode,
          // value is a union), so we coerce at the boundary rather than
          // fighting the signature.
          labelFormatter={(label) => formatTime(Number(label), windowHours)}
          formatter={(value, name) => [`${Number(value).toFixed(2)} W`, String(name)]}
          contentStyle={{
            background: 'var(--panel)',
            border: '1px solid var(--border)',
            fontSize: 12,
          }}
        />

        {/*
          stackId makes these sum visually to total_watts, so the chart shows
          both the total and what's driving it.

          isAnimationActive={false} is essential for live data: with it on,
          Recharts replays its entry animation on every poll, so the chart
          would visibly redraw itself every 2 seconds.

          connectNulls={false} preserves the empty buckets as real breaks in
          the line rather than interpolating across periods where the loop
          wasn't running.
        */}
        <Area
          dataKey="baseline_watts" name="baseline" stackId="power"
          stroke="var(--baseline)" fill="var(--baseline)" fillOpacity={0.35}
          isAnimationActive={false} connectNulls={false}
        />
        <Area
          dataKey="cpu_watts" name="cpu" stackId="power"
          stroke="var(--cpu)" fill="var(--cpu)" fillOpacity={0.35}
          isAnimationActive={false} connectNulls={false}
        />
        <Area
          dataKey="ram_watts" name="ram" stackId="power"
          stroke="var(--ram)" fill="var(--ram)" fillOpacity={0.35}
          isAnimationActive={false} connectNulls={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
