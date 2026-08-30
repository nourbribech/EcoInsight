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
  /** Why the comparison was withheld: 'calibration_changed' when the
   *  coefficients moved inside the window, 'insufficient_history' when the
   *  earlier period lacks comparable sample coverage. */
  change_blocked_reason: 'calibration_changed' | 'insufficient_history' | null
  profile_changes: { timestamp: string; machine_model: string; source: string; baseline_watts: number }[]
  per_day: DayTotal[]
  top_applications: { name: string; label: string | null; watt_hours: number }[]
  idle_awake_watt_hours: number | null
  /** Idle energy over energy on the TRACKED days, not over the whole period. */
  idle_awake_share: number | null
  energy_on_tracked_days_wh: number | null
  days_tracked: number
  /** Human-scale restatements of the same figures. Empty when the period is
   *  too small for any comparison to be meaningful. */
  equivalences: { label: string; value: number; kind: 'energy' | 'carbon' }[]
  offhours: OffHours
  /**
   * Null when idle tracking has not run for `rating_minimum_days`. Absent is
   * rendered explicitly, never as a passing grade.
   */
  rating: WasteRating | null
  rating_minimum_days: number
}

/** A tier for how much of the period's energy was avoidable. */
export interface WasteRating {
  tier: 'excellent' | 'good' | 'fair' | 'poor'
  label: string
  detail: string
  share: number
  /** Share needed to reach the next band up; null when already at the top. */
  next_tier_share: number | null
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

/** GET /api/lifecycle — manufacturing carbon against operating carbon. */
export interface Lifecycle {
  machine_model: string
  embodied_kg: number
  /** True when no manufacturer datasheet is on file and a class figure was used. */
  embodied_is_estimate: boolean
  embodied_low_kg: number
  embodied_high_kg: number
  annual_operating_kg: number
  /** Null until enough operating data exists to divide by. */
  years_of_operation_equivalent: number | null
  manufacturing_share: number | null
  one_more_year_saves_kg: number
  one_more_year_in_operating_years: number | null
  service_life_years: number
  measured_days: number
  battery: {
    available: boolean
    design_mwh: number | null
    full_charge_mwh: number | null
    health_percent: number | null
  }
}

/** GET/PUT /api/goal — the soft weekly target and progress against it. */
export interface Goal {
  target_share: number
  default_target_share: number
  minimum_target_share: number
  maximum_target_share: number
  /** Null while nobody has chosen one, so the panel can say "assumed"
   *  rather than implying the user picked the default. */
  chosen_at: string | null
  week_start: string
  week_end: string
  status: GoalStatus
  /** Null when the finished week carries too little tracking to judge —
   *  rendered as an absence, never as a pass. */
  previous_week: GoalVerdict | null
}

export interface GoalStatus {
  target_share: number
  share: number | null
  state: 'no_data' | 'too_early' | 'on_track' | 'close' | 'over'
  headline: string
  detail: string
  wasted_watt_hours: number | null
  /** What the target allows over the whole week, projected from the pace so
   *  far. Null before enough of the week has elapsed to project honestly. */
  budget_watt_hours: number | null
  /** What it allows for the energy used so far. */
  pace_watt_hours: number | null
  remaining_watt_hours: number | null
  elapsed_fraction: number
  days_tracked: number
}

export interface GoalVerdict {
  share: number
  met: boolean
  wasted_watt_hours: number | null
  days_tracked: number
}

/** GET /api/workloads — developer workloads left running (today, WSL). */
export interface Workloads {
  wsl: {
    /** False means the question could not be asked — no WSL, or the command
     *  failed. NOT the same as "no distributions", and never rendered as such. */
    available: boolean
    installed: string[]
    running: string[]
    docker: boolean
    vm: {
      running: boolean
      pid: number | null
      /** Host CPU, normalised over cores. Null on the first sample after the
       *  agent starts — there is no baseline to diff against yet. */
      cpu_percent: number | null
      memory_bytes: number | null
      uptime_seconds: number | null
      attached_sessions: number
    }
  }
  history: {
    samples: number
    running_samples: number
    running_hours: number
    observed_hours: number
    peak_cpu_percent: number | null
    mean_cpu_percent: number | null
    peak_memory_bytes: number | null
    unattended_samples: number
    unattended_hours: number
  }
  findings: Finding[]
  calibration_source: string
  days: number
}

/** GET /api/actions — every standing finding, ranked, from all rules. */
export interface Actions {
  actions: Action[]
  summary: ActionSummary
  calibration_source: string
}

/** A Finding plus which rule produced it. */
export interface Action extends Finding {
  source: string
}

export interface ActionSummary {
  total: number
  /** Excludes `ok` rows — those are reassurance, not work. */
  todo: number
  yours: number
  needs_it: number
  high: number
}
