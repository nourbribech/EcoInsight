/** Anything with an ISO timestamp can be bucketed. */
interface Timestamped {
  timestamp: string
}

/**
 * A downsampled point: an x position plus one averaged value per requested
 * field. Values are nullable because an empty bucket — a stretch of wall
 * clock with no samples in it — must render as a break in the line rather
 * than a straight line interpolated across it.
 */
export type Bucketed<Field extends string> = { t: number } & Record<Field, number | null>

/**
 * Averages rows into a fixed number of equal-duration time buckets.
 *
 * WHY DOWNSAMPLE
 * The estimation loop ticks about every 2.6s, so a continuously-running day
 * produces ~33,000 rows. A chart on screen is ~800px wide — 41 points per
 * pixel, 97% of them invisible whichever library draws them. Reducing to
 * roughly the pixel width isn't an optimisation, it's the only honest way to
 * draw this much data.
 *
 * WHY BUCKET BY TIME, NOT BY INDEX
 * "Keep every Nth row" treats rows as evenly spaced. They aren't: this
 * history contains multi-hour gaps where the laptop was suspended. Index
 * bucketing would squeeze a 5-hour gap into the same width as a 5-second
 * one. Bucketing by wall clock keeps the x-axis truthful, and a stretch with
 * no measurements simply produces an empty bucket -> a null -> a visible
 * break. Gaps render as gaps, which is what they are.
 *
 * WHY IT'S GENERIC
 * It started hardcoded to the measurement columns. The telemetry chart is
 * the second caller with a different set of columns, which is the point at
 * which generalising pays for itself — not before.
 */
export function bucketByTime<Row extends Timestamped, Field extends Extract<keyof Row, string>>(
  rows: Row[],
  fields: readonly Field[],
  maxBuckets: number,
): Bucketed<Field>[] {
  if (rows.length === 0) return []

  const first = Date.parse(rows[0].timestamp)
  const last = Date.parse(rows[rows.length - 1].timestamp)

  // A single row, or every row sharing one timestamp, gives a zero-width
  // span and would divide by zero below.
  const span = Math.max(last - first, 1)

  // NEVER make more buckets than there are rows.
  //
  // This matters enormously for sparse series. Telemetry is written every
  // 120s, so a day of it is ~720 rows — and currently only 69. Splitting 69
  // rows across 700 buckets leaves 631 empty, and since empty buckets break
  // the line, the chart would render as 69 disconnected dots instead of a
  // line. Clamping guarantees at least one row per bucket on average, so
  // the only empty buckets left are the real gaps.
  const bucketCount = Math.min(maxBuckets, rows.length)
  const bucketMs = span / bucketCount

  const sums: (Record<string, number> | null)[] = new Array(bucketCount + 1).fill(null)
  // Counted PER FIELD, not once per row. Some columns are nullable and were
  // added later than others — brightness_percent is NULL on every row written
  // before display tracking existed. Dividing by a shared row count would
  // average those absent values in as Number(null) === 0, drawing a
  // brightness line pinned at 0% that climbs as new rows arrive. Averaging
  // each field over only the rows that actually carried it is the difference
  // between "no data" and "a measured zero".
  const counts: (Record<string, number> | null)[] = new Array(bucketCount + 1).fill(null)

  for (const row of rows) {
    const offset = Date.parse(row.timestamp) - first
    // The last row lands exactly on the upper edge, hence the +1 slot and
    // the clamp.
    const index = Math.min(Math.floor(offset / bucketMs), bucketCount)

    let accumulator = sums[index]
    let counter = counts[index]
    if (accumulator === null || counter === null) {
      accumulator = {}
      counter = {}
      for (const field of fields) {
        accumulator[field] = 0
        counter[field] = 0
      }
      sums[index] = accumulator
      counts[index] = counter
    }

    for (const field of fields) {
      const value = row[field]
      if (value === null || value === undefined) continue
      accumulator[field] += Number(value)
      counter[field] += 1
    }
  }

  // Emit a point for EVERY bucket including empty ones — skipping them would
  // collapse the gaps we just worked to preserve.
  return sums.map((accumulator, index) => {
    const point: Record<string, number | null> = {
      // Plot at the bucket's centre: the mean of the samples inside it best
      // represents the middle of the interval, not its left edge.
      t: first + index * bucketMs + bucketMs / 2,
    }
    const counter = counts[index]
    for (const field of fields) {
      const n = counter === null ? 0 : counter[field]
      // n === 0 means every row in this bucket had no value for this field,
      // which is null rather than zero.
      point[field] = accumulator === null || n === 0 ? null : accumulator[field] / n
    }
    // The loop above builds exactly the shape the signature promises, but
    // TypeScript can't follow that through a string-keyed record.
    return point as Bucketed<Field>
  })
}

/**
 * Drops rows older than `hours` before now.
 *
 * The live poller appends a row every few seconds and never removes one, so
 * without this the array grows unbounded for as long as the dashboard stays
 * open — a real concern for a tool meant to sit in a background tab all day.
 */
export function trimToWindow<Row extends Timestamped>(rows: Row[], hours: number): Row[] {
  const cutoff = Date.now() - hours * 3_600_000

  // Rows arrive sorted ascending, so everything to drop is at the front and
  // we can stop at the first row worth keeping.
  let firstKept = 0
  while (firstKept < rows.length && Date.parse(rows[firstKept].timestamp) < cutoff) {
    firstKept += 1
  }

  return firstKept === 0 ? rows : rows.slice(firstKept)
}

/** A stretch of wall clock with no measurements in it. */
export interface Gap {
  x1: number
  x2: number
}

/**
 * Finds the contiguous runs of empty buckets, so charts can shade them.
 *
 * A break in the line is correct but reads as a rendering fault. Shading the
 * region makes it legible as "the agent wasn't collecting here", which is
 * what it actually means.
 *
 * Note this is NOT the same as the machine being idle. Idle is the agent
 * running and reporting ~9W. A gap is no data at all — the laptop was
 * suspended or the process was down. Drawing it as a drop to zero would
 * claim the machine consumed nothing, which is just as untrue as drawing a
 * straight line across it.
 *
 * `minBuckets` avoids peppering the chart with slivers from single dropped
 * samples, which are noise rather than outages.
 */
export function findGaps<Field extends string>(
  points: Bucketed<Field>[],
  field: Field,
  minBuckets = 2,
): Gap[] {
  const gaps: Gap[] = []
  let runStart: number | null = null

  const closeRun = (endIndex: number) => {
    if (runStart !== null && endIndex - runStart + 1 >= minBuckets) {
      gaps.push({ x1: points[runStart].t, x2: points[endIndex].t })
    }
    runStart = null
  }

  points.forEach((point, index) => {
    if (point[field] === null) {
      if (runStart === null) runStart = index
    } else {
      closeRun(index - 1)
    }
  })
  closeRun(points.length - 1)

  return gaps
}

/**
 * Human-readable throughput. I/O spans six orders of magnitude on a normal
 * machine — idle background writes of a few hundred B/s, bursts of tens of
 * MB/s — so a raw byte count on an axis label is unreadable.
 *
 * Uses decimal (1000) rather than binary (1024) units, matching how disk
 * throughput is conventionally quoted.
 */
export function formatBytesPerSecond(bytes: number): string {
  const value = Math.abs(bytes)

  if (value >= 1e9) return `${(value / 1e9).toFixed(1)} GB/s`
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)} MB/s`
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)} KB/s`
  return `${Math.round(value)} B/s`
}

/** Axis/tooltip label. Short for intraday windows, dated for longer ones. */
export function formatTime(epochMs: number, windowHours: number): string {
  const date = new Date(epochMs)
  const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  if (windowHours <= 24) return time

  const day = date.toLocaleDateString([], { day: '2-digit', month: 'short' })
  return `${day} ${time}`
}
