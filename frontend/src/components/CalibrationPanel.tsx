import { useState } from 'react'
import { usePolling } from '../hooks/usePolling'
import { Disclosure } from './Disclosure'

/** Changes only when somebody edits it. Polled to survive a restart. */
const POLL_MS = 300_000

interface Profile {
  machine_model: string
  cpu_watts_per_percent: number
  ram_watts_per_gb: number
  baseline_watts: number
  source: 'measured' | 'entered'
  notes: string
  calibrated_at: string | null
}

interface CalibrationData {
  profiles: Profile[]
  writable: boolean
  database: string
  current_machine_key: string | null
  limits: Record<string, [number, number]>
  error: string | null
}

/**
 * The IT team's way to add a calibration profile without source-code access.
 *
 * WHAT THIS DELIBERATELY DOES NOT DO
 * It never stores a profile as "measured". Somebody typing three numbers into
 * a form has not run a battery-discharge sweep, and a profile that claimed
 * they had would inherit the authority of one — and switch off the "this
 * machine is not calibrated" warning, which fires only on "estimated". Typed
 * profiles are "entered", and the dashboard says so.
 *
 * The only path that preserves "measured" is Import, because an exported file
 * carries a profile already classified elsewhere: calibration is per MODEL,
 * so a sweep run on one laptop is genuinely measured for every identical
 * unit, and downgrading it in transit would destroy true information.
 *
 * WHY IT ASKS BEFORE OFFERING
 * `writable` comes from the server actually trying to take a write lock. The
 * `--mode it` flag is not a permission — any employee can pass it — so the
 * real gate is whether Windows lets this account write hardware.db. Showing a
 * form that fails on submit would blame the user for the fleet's access
 * control working correctly.
 */
export function CalibrationPanel() {
  const [refresh, setRefresh] = useState(0)
  const { data, error, loading } = usePolling<CalibrationData>(
    `/api/calibration?r=${refresh}`,
    POLL_MS,
  )
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  if (loading) return <div className="chart-empty">Loading calibration profiles…</div>
  if (error) return <div className="chart-empty">Calibration unavailable: {error}</div>
  if (!data) return null

  async function send(path: string, body: unknown, method = 'POST') {
    setBusy(true); setMessage(null); setFailure(null)
    try {
      const response = await fetch(path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        // 403 is the permission refusal, and it is not a fault — say what it
        // means rather than showing a bare status code.
        throw new Error(payload.detail ?? `${response.status} ${response.statusText}`)
      }
      // A delete and a save both come back with restart_required, so the verb
      // has to come from what the payload actually reports having done.
      const did = payload.deleted ? 'Removed' : 'Saved'
      setMessage(
        payload.restart_required
          ? `${did}. Restart the agent so the collector uses it for new readings.`
          : `${did}.`,
      )
      setRefresh((n) => n + 1)
    } catch (cause: unknown) {
      setFailure(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="calibration">
      <div className="calibration-head">
        <div>
          <p className="eyebrow">IT setup</p>
          <h2>Calibration profiles</h2>
        </div>
        <span className={`setup-state setup-state-${data.writable ? 'calibrated' : 'estimated'}`}>
          {data.writable ? 'Editable' : 'Read-only'}
        </span>
      </div>

      {!data.writable && (
        <p className="calibration-locked">
          This account cannot write the calibration database. On a managed
          machine that file is administrator-only — which is what stops a
          calibration being changed from an ordinary session. Run this session
          as an administrator to add a profile.
        </p>
      )}

      <ProfileList
        profiles={data.profiles}
        currentKey={data.current_machine_key}
        writable={data.writable}
        busy={busy}
        onDelete={(model) =>
          send(`/api/calibration/${encodeURIComponent(model)}`, undefined, 'DELETE')}
      />

      {data.writable && (
        <ProfileForm
          busy={busy}
          currentKey={data.current_machine_key}
          limits={data.limits}
          onSave={(body) => send('/api/calibration', body)}
        />
      )}

      <Transfer
        writable={data.writable}
        busy={busy}
        onImport={(profiles) => send('/api/calibration/import', { profiles })}
      />

      {message && <p className="calibration-ok">{message}</p>}
      {failure && <p className="calibration-error">{failure}</p>}

      <Disclosure label="why typed profiles are never marked “measured”">
        <p className="finding-detail">
          “Measured” means battery-discharge sweeps were run on that exact
          model, and every watt-hour and gram of CO₂eq on this dashboard
          inherits that claim. A number typed into a form may be excellent —
          copied from a sweep on an identical unit — or a guess, and nothing
          here can tell the difference, so it is stored as “entered” and
          labelled that way wherever it surfaces. Importing a file preserves
          whatever it was classified as elsewhere, because calibration belongs
          to the model rather than to one laptop.
        </p>
      </Disclosure>
    </section>
  )
}

/**
 * Removal is a two-step press rather than a browser confirm dialog.
 *
 * This row may be the only record of a battery-discharge sweep that cost hours
 * of controlled measurement, so a single misplaced click must not destroy it —
 * but window.confirm is a modal the page cannot style, phrase precisely, or
 * guarantee is even shown. Asking in the row itself puts the question next to
 * the thing it is about, and names what happens instead of asking "are you
 * sure?".
 *
 * The file is copied before every removal regardless (see the endpoint), so
 * this is the second line of defence, not the only one.
 */
function ProfileList({ profiles, currentKey, writable, busy, onDelete }: {
  profiles: Profile[]
  currentKey: string | null
  writable: boolean
  busy: boolean
  onDelete: (machineModel: string) => void
}) {
  const [confirming, setConfirming] = useState<string | null>(null)

  if (profiles.length === 0) {
    return <p className="muted">No profiles stored. Every machine falls back to an estimate.</p>
  }

  return (
    <table className="calibration-table">
      <thead>
        <tr>
          <th>Model</th><th>CPU W/%</th><th>RAM W/GB</th><th>Baseline W</th><th>Source</th>
          {writable && <th />}
        </tr>
      </thead>
      <tbody>
        {profiles.map((p) => (
          <tr key={p.machine_model} className={p.machine_model === currentKey ? 'is-current' : ''}>
            <td>
              {p.machine_model}
              {p.machine_model === currentKey && <span className="calibration-this"> this machine</span>}
              {p.notes && <div className="calibration-notes">{p.notes}</div>}
            </td>
            <td>{p.cpu_watts_per_percent.toFixed(5)}</td>
            <td>{p.ram_watts_per_gb.toFixed(3)}</td>
            <td>{p.baseline_watts.toFixed(2)}</td>
            <td>
              <span className={`calibration-source calibration-source-${p.source}`}>
                {p.source}
              </span>
            </td>
            {writable && (
              <td className="calibration-actions">
                {confirming === p.machine_model ? (
                  <>
                    <button
                      type="button"
                      className="calibration-remove-confirm"
                      disabled={busy}
                      onClick={() => { onDelete(p.machine_model); setConfirming(null) }}
                    >
                      {p.source === 'measured' ? 'Remove a measured profile' : 'Remove'}
                    </button>
                    <button
                      type="button"
                      className="calibration-remove-cancel"
                      onClick={() => setConfirming(null)}
                    >
                      Keep
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="calibration-remove"
                    disabled={busy}
                    onClick={() => setConfirming(p.machine_model)}
                    title="Machines of this model fall back to an estimate"
                  >
                    Remove
                  </button>
                )}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ProfileForm({ busy, currentKey, limits, onSave }: {
  busy: boolean
  currentKey: string | null
  limits: Record<string, [number, number]>
  onSave: (body: Record<string, unknown>) => void
}) {
  // Prefilled with the key this machine looks itself up by. Getting it wrong
  // by one character means the profile is stored and never found again.
  const [model, setModel] = useState(currentKey ?? '')
  const [cpu, setCpu] = useState('')
  const [ram, setRam] = useState('')
  const [baseline, setBaseline] = useState('')
  const [notes, setNotes] = useState('')

  const range = (key: string) => limits[key] ? `${limits[key][0]}–${limits[key][1]}` : ''

  return (
    <form
      className="calibration-form"
      onSubmit={(event) => {
        event.preventDefault()
        onSave({
          machine_model: model,
          cpu_watts_per_percent: Number(cpu),
          ram_watts_per_gb: Number(ram),
          baseline_watts: Number(baseline),
          notes,
        })
      }}
    >
      <h3>Add or replace a profile</h3>
      <label>
        <span>Machine model key</span>
        <input value={model} onChange={(e) => setModel(e.target.value)} required
               placeholder="Manufacturer Model" />
        <small>Must match exactly what the agent reports for that model.</small>
      </label>
      <div className="calibration-fields">
        <label>
          <span>CPU W per %</span>
          <input type="number" step="0.00001" value={cpu} required
                 onChange={(e) => setCpu(e.target.value)} />
          <small>{range('cpu_watts_per_percent')}</small>
        </label>
        <label>
          <span>RAM W per GB</span>
          <input type="number" step="0.001" value={ram} required
                 onChange={(e) => setRam(e.target.value)} />
          <small>{range('ram_watts_per_gb')}</small>
        </label>
        <label>
          <span>Baseline W</span>
          <input type="number" step="0.01" value={baseline} required
                 onChange={(e) => setBaseline(e.target.value)} />
          <small>{range('baseline_watts')}</small>
        </label>
      </div>
      <label>
        <span>Where these numbers came from</span>
        <input value={notes} onChange={(e) => setNotes(e.target.value)}
               placeholder="e.g. copied from the sweep on an identical unit, 2026-08-20" />
      </label>
      <button type="submit" disabled={busy}>
        {busy ? 'Saving…' : 'Save as “entered”'}
      </button>
    </form>
  )
}

/**
 * Moving profiles between machines.
 *
 * Without this, a profile added on one laptop never reaches another of the
 * same model, and "calibrated by model" quietly becomes "calibrated per
 * machine" — which is not what the architecture claims.
 */
function Transfer({ writable, busy, onImport }: {
  writable: boolean
  busy: boolean
  onImport: (profiles: unknown[]) => void
}) {
  const [error, setError] = useState<string | null>(null)

  async function readFile(file: File) {
    setError(null)
    try {
      const parsed = JSON.parse(await file.text())
      const profiles = Array.isArray(parsed) ? parsed : parsed.profiles
      if (!Array.isArray(profiles) || profiles.length === 0) {
        throw new Error('No profiles found in that file.')
      }
      onImport(profiles)
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <div className="calibration-transfer">
      <a href="/api/calibration/export" download="ecoinsight-calibration.json">
        Export all profiles
      </a>
      {writable && (
        <label className="calibration-import">
          <span>Import a file</span>
          <input
            type="file"
            accept="application/json,.json"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) readFile(file)
              e.target.value = ''
            }}
          />
        </label>
      )}
      {error && <span className="calibration-error">{error}</span>}
    </div>
  )
}
