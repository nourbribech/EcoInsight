import { useMemo } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Telemetry } from '../types/api'
import { bucketByTime, findGaps, formatTime } from '../lib/series'

const MAX_BUCKETS = 700

/** The columns we average. Typed as a const tuple so bucketByTime infers the
 *  exact field names and the resulting points are properly typed. */
const FIELDS = ['cpu_usage_percent', 'ram_usage_percent', 'brightness_percent'] as const

interface Props {
  rows: Telemetry[]
  windowHours: number
}

export function UtilizationChart({ rows, windowHours }: Props) {
  const points = useMemo(() => bucketByTime(rows, FIELDS, MAX_BUCKETS), [rows])
  const gaps = useMemo(() => findGaps(points, 'cpu_usage_percent'), [points])

  if (points.length === 0) {
    return <div className="chart-empty">No activity readings for this time range.</div>
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
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
          FIXED 0-100 DOMAIN, unlike the power chart's autoscaling axis.
          Utilisation is a percentage of a known maximum, so the axis should
          show that whole maximum. Let Recharts autoscale and a quiet hour
          where CPU sits between 2% and 5% fills the panel with what looks
          like dramatic activity. A fixed axis keeps "busy" and "idle"
          visually comparable across every window you switch to.
        */}
        <YAxis
          domain={[0, 100]}
          ticks={[0, 25, 50, 75, 100]}
          unit="%"
          width={46}
          tick={{ fontSize: 11, fill: 'var(--muted)' }}
        />

        <Tooltip
          labelFormatter={(label) => formatTime(Number(label), windowHours)}
          formatter={(value, name) => [`${Number(value).toFixed(1)}%`, String(name)]}
          contentStyle={{
            background: 'var(--panel)',
            border: '1px solid var(--border)',
            fontSize: 12,
          }}
        />

        {/*
          LINES, NOT A STACKED AREA — the opposite choice from PowerChart,
          and the reason is the units. Watts are additive: cpu + ram +
          baseline genuinely sum to the total draw, so stacking them is
          meaningful. Percentages of two different resources are not: "CPU
          50% + RAM 70% = 120%" describes nothing. Stacking here would
          invent a quantity that doesn't exist.

          dot={false} matters more for Line than for Area — Line renders a
          circle per point by default, which at 700 points means 700 extra
          DOM nodes per series.
        */}
        <Line
          dataKey="cpu_usage_percent" name="cpu" stroke="var(--cpu)"
          strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false}
        />
        <Line
          dataKey="ram_usage_percent" name="ram" stroke="var(--ram)"
          strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false}
        />
        {/*
          Brightness belongs on THIS chart rather than one of its own, because
          it is already a percentage of a known maximum — exactly what the
          fixed 0-100 axis was built for. A separate panel would need its own
          axis to say the same thing.

          Dashed, because it is a different KIND of quantity: cpu and ram are
          load the machine is under, brightness is a setting the user chose.
          Same units, same axis, different meaning — the dashes stop it being
          read as a third resource.

          connectNulls={false} does the heavy lifting here: every row written
          before display tracking existed has a null, so the line simply
          starts where the data does instead of implying history it never had.
        */}
        <Line
          dataKey="brightness_percent" name="brightness" stroke="var(--brightness)"
          strokeWidth={1.5} strokeDasharray="4 3" dot={false}
          isAnimationActive={false} connectNulls={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
