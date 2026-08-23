import { usePolling } from '../hooks/usePolling'
import { Disclosure } from './Disclosure'
import type { Action, Actions } from '../types/api'

/** The server caches both halves; polling faster just refetches them. */
const POLL_MS = 120_000

/**
 * One ranked list of things to do, from every rule that produces them.
 *
 * This replaces two separate panels. Power settings and developer workloads
 * were rendering the same Finding shape in two places with no ranking between
 * them, so the reader had to compare across panels to work out what mattered
 * most — which is the job the tool was supposed to do for them. Splitting the
 * page into views made it worse: the workload findings ended up on a
 * different tab from the configuration ones, so a row marked "you can fix
 * this" was sitting on a screen the user had no reason to open.
 *
 * The episodic recommendations feed is deliberately NOT merged in here. See
 * estimators/actions.py — those are events with no notion of still being
 * true, and promoting them by recency would infer "happening now" from
 * "happened recently".
 */
export function ActionsPanel() {
  const { data, error, loading } = usePolling<Actions>('/api/actions', POLL_MS)

  if (loading) return <div className="chart-empty">Checking…</div>
  if (error) return <div className="chart-empty">Findings unavailable: {error}</div>
  if (!data) return null

  // Split rather than filtered. An `ok` row is a reassurance, not a task, and
  // ranking it alongside real work dilutes the list — but dropping it
  // entirely brings back the empty panel that config_audit exists to prevent.
  const todo = data.actions.filter((a) => a.severity !== 'ok')
  const clear = data.actions.filter((a) => a.severity === 'ok')

  return (
    <div className="actions">
      <Headline summary={data.summary} />

      {todo.length > 0 && (
        <ul className="findings">
          {todo.map((action) => (
            <ActionRow key={action.key} action={action} />
          ))}
        </ul>
      )}

      {clear.length > 0 && (
        /*
          Compact, muted, and last. It answers "did it actually look?" without
          competing with anything that needs doing.
        */
        <div className="actions-clear">
          <span className="actions-clear-label">Checked, nothing to do</span>
          {clear.map((action) => (
            <span className="actions-clear-item" key={action.key} title={action.detail}>
              {action.title}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function Headline({ summary }: { summary: Actions['summary'] }) {
  if (summary.todo === 0) {
    return (
      <p className="actions-headline actions-headline-clear">
        Nothing to fix right now — all {summary.total} checks are clear.
      </p>
    )
  }

  // "Is any of this mine?" is the only question a reader arrives with, so it
  // is answered in the first line rather than left to be counted off badges.
  const parts: string[] = []
  if (summary.yours > 0) parts.push(`${summary.yours} you can fix`)
  if (summary.needs_it > 0) parts.push(`${summary.needs_it} needs IT`)

  return (
    <p className="actions-headline">
      <b>{summary.todo}</b> thing{summary.todo === 1 ? '' : 's'} worth doing
      {parts.length > 0 && <span className="muted"> — {parts.join(', ')}</span>}
    </p>
  )
}

function ActionRow({ action }: { action: Action }) {
  return (
    <li className={`finding finding-${action.severity}`}>
      <div className="finding-head">
        <span className="finding-title">{action.title}</span>
        {/*
          WHO can fix it, on every row.
          On a company-managed machine some settings belong to the user and
          some to IT. Telling an employee to change a policy their
          administrator has locked wastes their time and costs the tool its
          credibility, so the distinction is never left implicit.
        */}
        <span className={`finding-owner finding-owner-${action.fixable}`}>
          {OWNER_LABELS[action.fixable] ?? action.fixable}
        </span>
      </div>
      {/*
        The REASONING collapses; the fix does not.
        A row is read-complete without it: the title states what is wrong and
        the action states what to do about it, so a reader who never opens
        this still behaves correctly. What is inside is why it matters -
        worth having, not worth re-reading on every visit.
      */}
      <Disclosure label="why this matters">
        <p className="finding-detail">{action.detail}</p>
      </Disclosure>
      {action.action && <p className="finding-action">{action.action}</p>}
      {/*
        Attribution, quiet but present. "power settings" and "developer
        workloads" want different mental models even when the advice looks
        alike, and once the sources are merged the reader can no longer tell
        them apart from position on the page.
      */}
      <span className="finding-source">{action.source}</span>
    </li>
  )
}

const OWNER_LABELS: Record<string, string> = {
  you: 'you can fix this',
  it: 'needs IT',
  none: 'nothing to do',
}
