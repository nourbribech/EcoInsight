/**
 * Mirrors the rows returned by the FastAPI layer in GreenIT/api/api.py.
 *
 * These are deliberately the *raw* server shapes — no derived fields. The
 * conversion into something a chart can draw happens in lib/series.ts, so
 * that this file stays a faithful description of the API contract and
 * nothing else. If the backend schema changes, this is the only file that
 * has to change to match it.
 */

/** One row of the `measurements` table — /api/current, /api/history. */
export interface Measurement {
  id: number
  timestamp: string // ISO 8601, local time, microsecond precision
  cpu_watts: number
  ram_watts: number
  baseline_watts: number
  total_watts: number
  interval_watt_hours: number
  cumulative_watt_hours: number
  interval_kg_co2eq: number
  cumulative_kg_co2eq: number
}

/** One row of the `telemetry_history` table — /api/telemetry. */
export interface Telemetry {
  id: number
  timestamp: string
  cpu_usage_percent: number
  ram_usage_percent: number
  ram_used_bytes: number
  disk_read_bytes_per_second: number
  disk_write_bytes_per_second: number
  network_bytes_sent_per_second: number
  network_bytes_received_per_second: number
  /** Null on rows written before idle tracking existed. */
  idle_seconds: number | null
  /**
   * Display state. Null on rows written before display tracking existed, and
   * also whenever a panel does not answer DDC/CI — "unknown", never a
   * measured 0%. Sampled every 120s rather than every poll because the read
   * costs ~170ms.
   */
  brightness_percent: number | null
  monitor_count: number | null
}

/** One row of the `recommendations` table — /api/recommendations. */
export interface Recommendation {
  id: number
  timestamp: string
  metric: string
  message: string
  current_value: number
  baseline_mean: number | null
  baseline_stdev: number | null
}

/**
 * /api/current returns `{}` (not 404, not null) when the measurements table
 * is empty — see api.py. So the response type is genuinely a union, and
 * callers must narrow before touching any field.
 */
export type CurrentResponse = Measurement | Record<string, never>

export function isMeasurement(data: CurrentResponse): data is Measurement {
  return 'total_watts' in data
}

// NOTE: the chart-point type used to live here. It moved to lib/series.ts as
// `Bucketed<Field>`, because it describes what the CHARTS need, not what the
// API returns — and this file should stay a faithful description of the
// server contract and nothing else.

/** One row of GET /api/processes — an application, not a single OS process. */
export interface ProcessSample {
  id: number
  timestamp: string
  /** Raw executable name as Windows reports it, e.g. "MsMpEng.exe". */
  name: string
  /**
   * Human-readable application name, e.g. "Windows Defender". Derived by the
   * API from `name` (process_labels.py) rather than stored, so it is always
   * present and always reflects the current lookup table.
   */
  label: string
  cpu_percent: number
  memory_bytes: number
  instances: number
  estimated_watts: number
}

/** One row of GET /api/summary's per-day breakdown. */
export interface DayTotal {
  date: string
  watt_hours: number
}

/** GET /api/summary — the "how am I doing" digest. */
export interface PeriodSummary {
  days: number
  current: { watt_hours: number; grams_co2eq: number; samples: number }
  previous: { watt_hours: number; grams_co2eq: number; samples: number }
  /**
   * Null when the previous period lacks comparable coverage — the agent may
   * simply not have been running. The server withholds it rather than
   * reporting a spectacular number derived from ten minutes of history.
   */
  change_percent: number | null
  per_day: DayTotal[]
  top_applications: { name: string; label: string | null; watt_hours: number }[]
  idle_awake_watt_hours: number | null
  idle_awake_share: number | null
  days_tracked: number
  /** Human-scale restatements of the same figures. Empty when the period is
   *  too small for any comparison to be meaningful. */
  equivalences: { label: string; value: number; kind: 'energy' | 'carbon' }[]
  offhours: OffHours
}

/** Energy drawn outside working hours, plus the shape of a typical day. */
export interface OffHours {
  workday_start_hour: number
  workday_end_hour: number
  total_watt_hours: number
  offhours_watt_hours: number
  offhours_share: number | null
  weekend_watt_hours: number
  /** 24 entries, index = hour of day, summed over the whole period. */
  by_hour: number[]
}

/** One standing configuration finding from GET /api/insights. */
export interface Finding {
  key: string
  title: string
  detail: string
  action: string | null
  /** Who is able to act: "you" | "it" | "none". */
  fixable: string
  severity: 'high' | 'medium' | 'ok'
}

export interface Insights {
  findings: Finding[]
  settings: Record<string, unknown>
  observed: Record<string, unknown>
}
