import { useState } from 'react'
import { Disclosure } from './Disclosure'
import type { SessionInfo } from '../App'

/** The payload of POST /api/calibration/run when `ok` is true. */
interface CalibrationResult {
  ok: boolean
  baseline_watts: number
  cpu_watts_per_percent: number
  ram_watts_per_gb: number
  machine_key: string | null
  r2_in_sample: number
  /** The honest one: scored on data the fit never saw. */
  r2_cross_validated: number
  /** A model that ignores the CPU. If the fit cannot beat it, it learned nothing. */
  r2_null_model: number
  written: boolean
}

interface ITSetupWizardProps {
  session: SessionInfo
  onComplete: () => void
  /**
   * Leave IT mode entirely, from inside the walkthrough.
   *
   * WHY THIS IS NOT OPTIONAL POLISH
   * The walkthrough renders INSTEAD of the setup panel, and the panel is where
   * the way out lives. On a machine that had never completed it, unlocking IT
   * mode dropped the reader into a five-step flow whose only exit was to
   * finish it — and finishing it writes a completion flag, so "I opened this
   * by mistake" had no answer that did not change stored state.
   *
   * Absent when IT mode came from `--mode it`, which no button can undo.
   */
  onLeaveItMode?: () => void
  leaving?: boolean
}

export function ITSetupWizard({
  session, onComplete, onLeaveItMode, leaving,
}: ITSetupWizardProps) {
  const [step, setStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [calibrationResult, setCalibrationResult] = useState<CalibrationResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function completeWizard() {
    setLoading(true)
    try {
      await fetch('/api/it/wizard-complete', { method: 'POST' })
      onComplete()
    } finally {
      setLoading(false)
    }
  }

  /**
   * A refusal comes back as HTTP 200 with `ok: false`, not as an error status.
   *
   * "The machine is plugged in" and "the fit was too weak to store" are things
   * the procedure is designed to conclude, and the operator has to read the
   * explanation. Returning them as HTTP errors would put them on the same
   * footing as a crash and lose the reason.
   */
  async function runCalibration(quick: boolean) {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`/api/calibration/run?quick=${quick}`, {
        method: 'POST',
      })
      const payload = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(payload.detail ?? `${response.status} ${response.statusText}`)
      }
      if (!payload.ok) {
        throw new Error(payload.error ?? 'Calibration did not produce a usable result.')
      }

      setCalibrationResult(payload)
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="it-wizard-overlay">
      <div className="it-wizard">
        <div className="wizard-top">
          {/* Progress bar */}
          <div className="wizard-progress">
            {[1, 2, 3, 4, 5].map((s) => (
              <div
                key={s}
                className={`progress-dot ${s === step ? 'active' : s < step ? 'complete' : ''}`}
              />
            ))}
          </div>

          {/*
            Present at every step, not only the last one. Somebody who opened
            this tab to look around must be able to leave at the moment they
            realise it, without finishing a setup they never intended to start
            and without writing a completion flag to say they read it.
          */}
          {onLeaveItMode && (
            <button
              type="button"
              className="wizard-leave"
              onClick={onLeaveItMode}
              disabled={leaving || loading}
              title={loading
                ? 'Wait for the measurement to finish'
                : 'Leave IT mode and return to the employee view'}
            >
              {leaving ? 'Switching…' : '✕ Leave IT setup'}
            </button>
          )}
        </div>

        {/* Step 1: Welcome */}
        {step === 1 && (
          <div className="wizard-step">
            <h1>Welcome to EcoInsight IT Setup</h1>
            <p className="wizard-intro">
              This app monitors energy usage on employee machines. Your role is to calibrate
              the power models so measurements are accurate for your hardware.
            </p>

            <div className="wizard-points">
              <div className="point">
                <span className="point-icon">📊</span>
                <div>
                  <strong>Measure what matters</strong>
                  <p>Employees see accurate power draw and battery drain for their machines.</p>
                </div>
              </div>
              <div className="point">
                <span className="point-icon">⚙️</span>
                <div>
                  <strong>You control calibration</strong>
                  <p>
                    Add power profiles for each model in your fleet. Employees pick them up
                    automatically without restarting.
                  </p>
                </div>
              </div>
              <div className="point">
                <span className="point-icon">🔒</span>
                <div>
                  <strong>No code access needed</strong>
                  <p>Everything is done through this interface. No command line or config files.</p>
                </div>
              </div>
            </div>

            <button className="wizard-next" onClick={() => setStep(2)}>
              Start setup
            </button>
          </div>
        )}

        {/* Step 2: How it works */}
        {step === 2 && (
          <div className="wizard-step">
            <h1>How calibration works</h1>

            <div className="wizard-flow">
              <div className="flow-box">
                <div className="flow-num">1</div>
                <strong>Measured</strong>
                <p>Run a battery discharge sweep on a laptop model. Takes ~2 hours.</p>
              </div>
              <div className="flow-arrow">→</div>
              <div className="flow-box">
                <div className="flow-num">2</div>
                <strong>Enter or import</strong>
                <p>Add the profile here. Or export it from one machine and import on another.</p>
              </div>
              <div className="flow-arrow">→</div>
              <div className="flow-box">
                <div className="flow-num">3</div>
                <strong>Automatic sync</strong>
                <p>Employees with that model pick it up on next login.</p>
              </div>
            </div>

            <div className="wizard-note">
              <strong>Before you start:</strong> A machine that doesn't have a profile falls back
              to an estimate based on its CPU class. The app still works — absolute watts are just
              less accurate until a sweep runs.
            </div>

            <div className="wizard-actions">
              <button className="wizard-secondary" onClick={() => setStep(1)}>
                Back
              </button>
              <button className="wizard-next" onClick={() => setStep(3)}>
                Next
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Current status */}
        {step === 3 && (
          <div className="wizard-step">
            <h1>This machine's status</h1>

            <div className="wizard-status">
              <div className="status-row">
                <span className="label">Model</span>
                <span className="value">{session.machine_model ?? 'unknown'}</span>
              </div>
              <div className="status-row">
                <span className="label">Profile</span>
                <span className={`value value-${session.calibration_source}`}>
                  {session.calibration_source === 'measured'
                    ? '✓ Measured by sweep'
                    : session.calibration_source === 'entered'
                      ? '✓ Entered by hand'
                      : '○ Using an estimate'}
                </span>
              </div>
              {session.calibrated_at && (
                <div className="status-row">
                  <span className="label">Added</span>
                  <span className="value">{new Date(session.calibrated_at).toLocaleDateString()}</span>
                </div>
              )}
            </div>

            <Disclosure label="What this means for employees">
              <p className="finding-detail">
                {session.calibration_source === 'measured'
                  ? 'Employees with this model are seeing coefficients from a controlled battery discharge sweep — the most accurate baseline possible.'
                  : session.calibration_source === 'entered'
                    ? 'Employees with this model are seeing coefficients that were typed in, probably copied from a sweep on an identical unit. Trends are sound; absolute watts are as good as the numbers entered.'
                    : 'Employees with this model are seeing coefficients scaled from the CPU class. Day-to-day trends and relative comparisons work; absolute watts carry an unknown error.'}
              </p>
            </Disclosure>

            <div className="wizard-actions">
              <button className="wizard-secondary" onClick={() => setStep(2)}>
                Back
              </button>
              <button className="wizard-next" onClick={() => setStep(4)}>
                Next
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Run Calibration */}
        {step === 4 && (
          <div className="wizard-step">
            <h1>Measure this machine</h1>
            <p className="wizard-intro">
              The most accurate coefficients come from measuring this machine's own
              battery discharge under controlled CPU load, rather than scaling them
              from its processor class.
            </p>

            <div className="wizard-note">
              <strong>Before you start:</strong> unplug the charger, and close what you
              are not using. The sweep can only add load to what is already running —
              on a busy machine every level measures near the top and the result means
              nothing, so it will refuse rather than store it.
            </div>

            {error && <div className="calibration-error">{error}</div>}

            {loading && (
              <div className="calibration-running">
                <p><strong>Measuring…</strong></p>
                <p className="muted">
                  The machine is being driven to several load levels and its battery
                  read at each one. Leave it alone until this finishes.
                </p>
              </div>
            )}

            {calibrationResult && (
              <div className="calibration-result">
                <p className="success-icon">✓ Profile measured and stored</p>
                <div className="result-values">
                  <div>Baseline · {calibrationResult.baseline_watts.toFixed(2)} W</div>
                  <div>CPU · {calibrationResult.cpu_watts_per_percent.toFixed(5)} W/%</div>
                  <div>
                    RAM · {calibrationResult.ram_watts_per_gb.toFixed(3)} W/GB
                    <span className="muted"> (reference value, not measured here)</span>
                  </div>
                  <div className="result-r2">
                    R² cross-validated · {calibrationResult.r2_cross_validated.toFixed(3)}
                    <span className="muted">
                      {' '}vs {calibrationResult.r2_null_model.toFixed(3)} for a model
                      that ignores the CPU
                    </span>
                  </div>
                </div>
              </div>
            )}

            <div className="wizard-actions">
              <button
                className="wizard-secondary"
                onClick={() => setStep(3)}
                disabled={loading}
              >
                Back
              </button>
              <button
                className="wizard-primary"
                onClick={() => runCalibration(true)}
                disabled={loading || !!calibrationResult}
              >
                {loading ? 'Measuring…' : 'Quick sweep · ~90 s'}
              </button>
              <button
                className="wizard-secondary"
                onClick={() => runCalibration(false)}
                disabled={loading || !!calibrationResult}
              >
                Full sweep · ~6 min
              </button>
              <button
                className="wizard-secondary"
                onClick={() => setStep(5)}
                disabled={loading}
              >
                Skip (manual entry)
              </button>
            </div>
          </div>
        )}

        {/* Step 5: Finish */}
        {step === 5 && (
          <div className="wizard-step">
            <h1>Ready to go</h1>

            <p className="wizard-finish-text">
              You now have access to the calibration panel. You can:
            </p>

            <div className="wizard-actions-list">
              <div className="action">
                <span className="action-icon">➕</span>
                <strong>Add a profile</strong> — Enter the power coefficients for a model
              </div>
              <div className="action">
                <span className="action-icon">📋</span>
                <strong>View all profiles</strong> — See what's stored and who uses it
              </div>
              <div className="action">
                <span className="action-icon">📁</span>
                <strong>Import/Export</strong> — Move profiles between machines
              </div>
              <div className="action">
                <span className="action-icon">🗑️</span>
                <strong>Delete a profile</strong> — Machines will fall back to an estimate
              </div>
            </div>

            <div className="wizard-note">
              <strong>Employees never see this wizard.</strong> They see a one-time message about
              how their machine's figures are derived, then the dashboard.
            </div>

            <button
              className="wizard-finish"
              onClick={completeWizard}
              disabled={loading}
            >
              {loading ? 'Finishing…' : 'Go to calibration panel'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
