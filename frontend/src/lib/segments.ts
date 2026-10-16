import type { Finding, Severity } from '../types'

export const SEV_RANK: Record<Severity, number> = { high: 3, medium: 2, low: 1 }

export interface Segment {
  key: string
  start: number
  end: number
  findings: Finding[] // empty for plain text
  severity?: Severity
  markers: Finding[] // MISSING anchors rendered after this segment
}

/** Number findings in reading order (by span start, then severity). */
export function numberFindings(findings: Finding[]): Map<string, number> {
  const sorted = [...findings].sort(
    (a, b) => a.span.start - b.span.start || SEV_RANK[b.severity] - SEV_RANK[a.severity] || a.id.localeCompare(b.id),
  )
  return new Map(sorted.map((f, i) => [f.id, i + 1]))
}

const highest = (fs: Finding[]): Severity =>
  fs.reduce<Severity>((s, f) => (SEV_RANK[f.severity] > SEV_RANK[s] ? f.severity : s), 'low')

/**
 * Split the policy text into plain and highlighted segments. Overlapping
 * spans are merged (transitively) into one segment carrying every finding,
 * coloured by the highest severity. Zero-length spans (MISSING findings)
 * become markers; a marker that falls inside a highlight is moved to its end.
 */
export function buildSegments(text: string, findings: Finding[]): Segment[] {
  const len = text.length
  const clamp = (n: number) => Math.max(0, Math.min(len, n))
  const ranged = findings
    .filter((f) => f.span.end > f.span.start && f.gap_type !== 'MISSING')
    .map((f) => ({ f, s: clamp(f.span.start), e: clamp(f.span.end) }))
    .filter((x) => x.e > x.s)
    .sort((a, b) => a.s - b.s || b.e - a.e)
  const anchors = findings
    .filter((f) => !(f.span.end > f.span.start) || f.gap_type === 'MISSING')
    .map((f) => ({ f, at: clamp(f.span.end) }))

  const clusters: { s: number; e: number; fs: Finding[] }[] = []
  for (const r of ranged) {
    const last = clusters[clusters.length - 1]
    if (last && r.s < last.e) {
      last.e = Math.max(last.e, r.e)
      last.fs.push(r.f)
    } else {
      clusters.push({ s: r.s, e: r.e, fs: [r.f] })
    }
  }

  // Move anchors that land strictly inside a cluster to the cluster end.
  for (const a of anchors) {
    const c = clusters.find((c) => a.at > c.s && a.at < c.e)
    if (c) a.at = c.e
  }

  const cuts = new Set<number>([0, len])
  clusters.forEach((c) => {
    cuts.add(c.s)
    cuts.add(c.e)
  })
  anchors.forEach((a) => cuts.add(a.at))
  const points = [...cuts].sort((a, b) => a - b)

  const segs: Segment[] = []
  for (let i = 0; i < points.length - 1; i++) {
    const s = points[i]
    const e = points[i + 1]
    const c = clusters.find((c) => c.s === s && c.e === e)
    segs.push({
      key: `${s}-${e}`,
      start: s,
      end: e,
      findings: c ? c.fs : [],
      severity: c ? highest(c.fs) : undefined,
      markers: anchors.filter((a) => a.at === e).map((a) => a.f),
    })
  }
  // Anchors at position 0 with no preceding text.
  const atZero = anchors.filter((a) => a.at === 0).map((a) => a.f)
  if (atZero.length) segs.unshift({ key: 'anchor-0', start: 0, end: 0, findings: [], markers: atZero })
  return segs
}
