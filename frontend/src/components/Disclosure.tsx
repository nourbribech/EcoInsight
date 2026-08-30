import type { ReactNode } from 'react'

/**
 * A collapsed explanation, opened on demand.
 *
 * WHAT BELONGS IN HERE, AND WHAT MUST NOT
 * This project explains itself in prose — where a figure came from, what it
 * under-counts, why a coefficient is an estimate — and that prose is the
 * reason its numbers can be trusted. It is also, on a page with ten panels,
 * most of the visual weight, and a reader who has absorbed it once has to
 * scroll past it every time afterwards.
 *
 * So the rule is about consequence, not length:
 *
 *   HIDDEN   provenance and methodology. Where the number came from, how it
 *            was derived, which datasheet is missing. A reader who skips it
 *            still reads the figure correctly.
 *
 *   VISIBLE  anything that changes how the figure should be READ. "Not rated
 *            yet — needs 5 days", "not enough history to compare", "no figure
 *            is attributable to a single distribution". Collapsing one of
 *            these would let a reader over-trust a number, which is exactly
 *            the failure the prose exists to prevent.
 *
 * Built on <details> rather than useState: keyboard support, correct
 * semantics and the open/closed state all come for free, and there is no
 * state to get out of sync.
 */
export function Disclosure({
  label = 'why?',
  children,
}: {
  label?: string
  children: ReactNode
}) {
  return (
    <details className="disclosure">
      <summary className="disclosure-summary">{label}</summary>
      <div className="disclosure-body">{children}</div>
    </details>
  )
}
