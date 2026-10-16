import type { GapType, Severity, VerificationStatus } from '../types'

export const GAP_LABEL: Record<GapType, string> = {
  CONTRADICTION: 'Contradiction',
  INSUFFICIENT: 'Insufficient',
  AMBIGUOUS: 'Ambiguous',
  MISSING: 'Missing',
  OUTDATED: 'Outdated',
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`badge sev-${severity}`}>{severity}</span>
}

export function GapBadge({ gap }: { gap: GapType }) {
  return <span className="badge gap">{GAP_LABEL[gap]}</span>
}

const VER_LABEL: Record<VerificationStatus, string> = {
  verified: 'Verified citation',
  partial: 'Partially supported',
  unverified: 'Not verified',
}

export function VerificationBadge({ status, note }: { status: VerificationStatus; note?: string | null }) {
  return (
    <span className={`badge ver-${status}`} title={note ?? undefined}>
      {status === 'verified' ? '✓ ' : status === 'partial' ? '◐ ' : '? '}
      {VER_LABEL[status]}
    </span>
  )
}
