import { usePolling } from '../hooks/usePolling'
import type { Lifecycle } from '../types/api'

/** Changes on the timescale of years. Polled only to survive a restart. */
const POLL_MS = 600_000

/**
 * The carbon this machine cost before it was ever switched on.
 *
 * Every other panel measures electricity, and for a laptop electricity is the
 * small number — manufacturing is roughly twenty years of it. Without this
 * context a dashboard reporting "245 g this week" quietly implies that weekly
 * grams are what matters, when they are a few percent of the total.
 *
 * It is not an argument against the rest of the page. It is what lets the
 * page say something the evidence actually supports: keep the machine longer,
 * and separately, do not waste power while you have it.
 */
export function LifecyclePanel({ days }: { days: number }) {
  const { data, error, loading } = usePolling<Lifecycle>(
    `/api/lifecycle?days=${days}`,
    POLL_MS,
  )

  if (loading) return <div className="chart-empty">Loading…</div>
  if (error) return <div className="chart-empty">Lifecycle unavailable: {error}</div>
  if (!data) return null

  const share = data.manufacturing_share
  const manufacturingPercent = share === null ? 0 : share * 100

  return (
    <div className="lifecycle">
      <p className="lifecycle-headline">
        Making this laptop emitted about{' '}
        <b>{data.embodied_kg.toFixed(0)} kg CO₂eq</b>
        {data.years_of_operation_equivalent !== null && (
          <> — roughly <b>{data.years_of_operation_equivalent.toFixed(0)} years</b> of
          running it at the rate measured here.</>
        )}
      </p>

      {/*
        A single stacked bar rather than two numbers: the whole point is the
        RATIO, and a 82/18 split is understood at a glance in a way that two
        figures on separate lines never are.
      */}
      <div className="lifecycle-bar" role="img"
           aria-label={`Manufacturing ${manufacturingPercent.toFixed(0)} percent of lifetime carbon`}>
        <div className="lifecycle-embodied" style={{ width: `${manufacturingPercent}%` }}>
          <span>manufacture</span>
        </div>
        <div className="lifecycle-operating" style={{ width: `${100 - manufacturingPercent}%` }}>
          <span>electricity</span>
        </div>
      </div>
      <p className="lifecycle-caption">
        Share of this machine's lifetime carbon over an assumed{' '}
        {data.service_life_years.toFixed(0)}-year service life, at{' '}
        {data.annual_operating_kg.toFixed(1)} kg CO₂eq a year of measured use.
      </p>

      <div className="lifecycle-lever">
        <span className="lifecycle-lever-label">The largest lever</span>
        <span>
          Keeping it one year longer avoids about{' '}
          <b>{data.one_more_year_saves_kg.toFixed(0)} kg CO₂eq</b>
          {data.one_more_year_in_operating_years !== null && (
            <> — more than <b>{data.one_more_year_in_operating_years.toFixed(1)} years</b> of
            this machine's electricity.</>
          )}
        </span>
      </div>

      <BatteryRow battery={data.battery} />

      {/*
        Provenance, stated rather than buried. This is the softest number in
        the project: a manufacturer's figure, not a measurement, and published
        footprints carry wide uncertainty of their own.
      */}
      <p className="lifecycle-source">
        {data.embodied_is_estimate
          ? `No published footprint on file for ${data.machine_model} — using a
             ${data.embodied_low_kg.toFixed(0)}–${data.embodied_high_kg.toFixed(0)} kg
             class estimate for a business laptop. Replace it with the
             manufacturer's Product Carbon Footprint datasheet.`
          : `From the manufacturer's Product Carbon Footprint datasheet for
             ${data.machine_model}.`}
        {' '}Operating emissions are measured over {data.measured_days} days and
        scaled to a year, so they under-count any period the agent was not
        running — which makes the multiple above a floor.
      </p>
    </div>
  )
}

function BatteryRow({ battery }: { battery: Lifecycle['battery'] }) {
  if (!battery.available || battery.health_percent === null) {
    return (
      <div className="lifecycle-battery">
        <span className="lifecycle-lever-label">Battery</span>
        <span className="muted">Not reported by this machine.</span>
      </div>
    )
  }

  const health = battery.health_percent
  const tone = health < 60 ? 'poor' : health < 80 ? 'fair' : 'good'

  return (
    <div className="lifecycle-battery">
      <span className="lifecycle-lever-label">Battery</span>
      <span className={`lifecycle-health lifecycle-health-${tone}`}>
        {health.toFixed(0)}% of original
      </span>
      <span className="muted">
        {(battery.full_charge_mwh! / 1000).toFixed(1)} of{' '}
        {(battery.design_mwh! / 1000).toFixed(1)} Wh
        {health < 80 && ' · wear is the usual trigger for replacing a working laptop'}
      </span>
    </div>
  )
}
