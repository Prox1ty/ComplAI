// Client-side mirror of backend/tools/apply.py, used only in mock/demo mode
// (no backend). The backend is the source of truth and also produces the Word file.
import type { AppliedChange, Clause, FixSelection, Result, Revision, SkippedFix } from '../types'
import { SEV_RANK } from './segments'

interface Edit {
  id: string
  kind: 'replace' | 'insert'
  start: number
  end: number
  text: string
  sev: number
}

const num = (id: string) => Number(id.match(/\d+/)?.[0] ?? 0)
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function withLabel(text: string, first: Clause): string {
  const t = text.trim()
  const label = (first.label ?? '').trim()
  if (!label) return t
  const bare = label.replace(/^\(|\)$/g, '')
  return new RegExp(`^\\(?${esc(bare)}\\)?[.:]?\\s`).test(t + ' ') ? t : `${label} ${t}`
}

export function applyFixesLocal(result: Result, fixes: FixSelection[]): Revision {
  const text = result.policy.full_text
  const byId = new Map(result.findings.map((f) => [f.id, f]))
  const skipped: SkippedFix[] = []
  const edits: Edit[] = []
  for (const sel of fixes) {
    const f = byId.get(sel.finding_id)
    if (!f) continue
    const t = (sel.text ?? f.suggestion.text ?? '').trim()
    if (!t) {
      skipped.push({ finding_id: f.id, reason: 'No replacement text to apply.' })
      continue
    }
    if (f.gap_type === 'MISSING' || !f.clause_ids.length) {
      edits.push({ id: f.id, kind: 'insert', start: f.span.start, end: f.span.start, text: t, sev: SEV_RANK[f.severity] })
      continue
    }
    const cs = result.policy.clauses.filter((c) => f.clause_ids.includes(c.id)).sort((a, b) => a.start - b.start)
    if (!cs.length) {
      skipped.push({ finding_id: f.id, reason: 'The clause it refers to was not found.' })
      continue
    }
    edits.push({
      id: f.id,
      kind: 'replace',
      start: cs[0].start,
      end: Math.max(...cs.map((c) => c.end)),
      text: withLabel(t, cs[0]),
      sev: SEV_RANK[f.severity],
    })
  }
  const kept: Edit[] = []
  for (const e of edits.filter((e) => e.kind === 'replace').sort((a, b) => b.sev - a.sev || num(a.id) - num(b.id))) {
    const clash = kept.find((k) => e.start < k.end && k.start < e.end)
    if (clash)
      skipped.push({
        finding_id: e.id,
        conflicts_with: clash.id,
        reason: `Rewrites the same clause as ${clash.id}, which was applied instead. Edit ${clash.id}'s wording to include this fix if both are needed.`,
      })
    else kept.push(e)
  }
  const inserts = edits.filter((e) => e.kind === 'insert')
  for (const ins of inserts) {
    const host = kept.find((k) => k.start < ins.start && ins.start < k.end)
    if (host) ins.start = ins.end = host.end
  }
  const all = [...kept, ...inserts].sort(
    (a, b) => a.start - b.start || (a.kind === 'replace' ? 0 : 1) - (b.kind === 'replace' ? 0 : 1) || num(a.id) - num(b.id),
  )
  let out = ''
  let cursor = 0
  const changes: AppliedChange[] = []
  for (const e of all) {
    out += text.slice(cursor, e.start)
    if (e.kind === 'replace') {
      changes.push({ finding_id: e.id, kind: 'replace', start: out.length, end: out.length + e.text.length, old_text: text.slice(e.start, e.end), new_text: e.text })
      out += e.text
      cursor = e.end
    } else {
      const prefix = e.start > 0 && text[e.start - 1] !== '\n' ? '\n' : ''
      const suffix = text[e.start] === '\n' ? '' : '\n'
      const s = out.length + prefix.length
      changes.push({ finding_id: e.id, kind: 'insert', start: s, end: s + e.text.length, old_text: '', new_text: e.text })
      out += prefix + e.text + suffix
      cursor = e.start
    }
  }
  out += text.slice(cursor)
  return { run_id: result.run_id, full_text: out, changes, skipped, docx_url: '', txt_url: '' }
}
