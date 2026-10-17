import { useMemo, useState } from 'react'
import type { GapRow, GapType } from '../types'
import { GAP_LABEL, GapBadge, SeverityBadge } from './Badges'
import { SEV_RANK } from '../lib/segments'

export interface ReviewState {
  selected: Set<string>
  edits: Record<string, string>
  onToggle: (findingId: string) => void
  onToggleAll: (ids: string[], on: boolean) => void
  onEdit: (findingId: string, text: string | null) => void
  applying: boolean
}

/** "Apply selected" / "Apply all" — rendered in the gap table's section header so it stays visible. */
export function ApplyButtons({
  selectedCount,
  fixableCount,
  applying,
  onApply,
}: {
  selectedCount: number
  fixableCount: number
  applying: boolean
  onApply: (mode: 'all' | 'selected') => void
}) {
  return (
    <div className="apply-actions">
      <span className="muted small">
        {selectedCount} of {fixableCount} fixes selected
      </span>
      <button
        className="btn ghost small"
        disabled={applying || selectedCount === 0}
        onClick={() => onApply('selected')}
      >
        Apply selected ({selectedCount})
      </button>
      <button className="btn primary small" disabled={applying || fixableCount === 0} onClick={() => onApply('all')}>
        {applying ? 'Applying…' : 'Apply all fixes'}
      </button>
    </div>
  )
}

interface Props {
  rows: GapRow[]
  numbers: Map<string, number>
  onRowClick: (findingId: string) => void
  printMode?: boolean
  review?: ReviewState
}

export default function GapTable({ rows, numbers, onRowClick, printMode = false, review }: Props) {
  const [desc, setDesc] = useState(true)
  const [filter, setFilter] = useState<GapType | 'ALL'>('ALL')
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const types = useMemo(() => [...new Set(rows.map((r) => r.gap_type))], [rows])

  const shown = useMemo(() => {
    const list = printMode ? [...rows] : rows.filter((r) => filter === 'ALL' || r.gap_type === filter)
    return list.sort((a, b) => {
      if (printMode) return (numbers.get(a.finding_id) ?? 0) - (numbers.get(b.finding_id) ?? 0)
      const d = SEV_RANK[a.severity] - SEV_RANK[b.severity]
      return (desc ? -d : d) || (numbers.get(a.finding_id) ?? 0) - (numbers.get(b.finding_id) ?? 0)
    })
  }, [rows, filter, desc, numbers, printMode])

  const reviewable = !printMode && review
  const shownIds = shown.filter((r) => r.fix.trim() || review?.edits[r.finding_id]?.trim()).map((r) => r.finding_id)
  const allShownSelected = !!review && shownIds.length > 0 && shownIds.every((id) => review.selected.has(id))

  const startEdit = (r: GapRow) => {
    setEditing(r.finding_id)
    setDraft(review?.edits[r.finding_id] ?? r.fix)
  }
  const saveEdit = (r: GapRow) => {
    const t = draft.trim()
    review?.onEdit(r.finding_id, t && t !== r.fix.trim() ? t : null)
    setEditing(null)
  }

  return (
    <div className={`gap-table-wrap ${printMode ? 'print-only' : 'no-print-table'}`}>
      {!printMode && (
        <div className="table-tools no-print">
          <label>
            Gap type{' '}
            <select value={filter} onChange={(e) => setFilter(e.target.value as GapType | 'ALL')}>
              <option value="ALL">All</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {GAP_LABEL[t]}
                </option>
              ))}
            </select>
          </label>
          <span className="muted">
            {shown.length} of {rows.length}
          </span>
          {reviewable && shownIds.length > 0 && (
            <label className="phone-only select-all">
              <input
                type="checkbox"
                checked={allShownSelected}
                onChange={(e) => review.onToggleAll(shownIds, e.target.checked)}
              />
              Select all
            </label>
          )}
        </div>
      )}
      <table className="gap-table">
        <thead>
          <tr>
            {reviewable && (
              <th className="check">
                <input
                  type="checkbox"
                  aria-label="Select all shown fixes"
                  checked={allShownSelected}
                  onChange={(e) => review.onToggleAll(shownIds, e.target.checked)}
                />
              </th>
            )}
            <th>#</th>
            <th>Clause</th>
            <th>Gap type</th>
            <th aria-sort={printMode ? undefined : desc ? 'descending' : 'ascending'}>
              {printMode ? (
                'Severity'
              ) : (
                <button className="sort" onClick={() => setDesc((d) => !d)}>
                  Severity {desc ? '↓' : '↑'}
                </button>
              )}
            </th>
            <th>Issue</th>
            <th>Source</th>
            <th>Suggested fix</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => {
            const edited = review?.edits[r.finding_id]
            const fix = edited ?? r.fix
            const isSel = !!review?.selected.has(r.finding_id)
            return (
              <tr
                key={r.finding_id}
                className={isSel ? 'selected' : ''}
                tabIndex={printMode ? undefined : 0}
                onClick={() => onRowClick(r.finding_id)}
                onKeyDown={(e) => e.key === 'Enter' && e.target === e.currentTarget && onRowClick(r.finding_id)}
              >
                {reviewable && (
                  <td className="check" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      aria-label={`Select fix ${numbers.get(r.finding_id)}`}
                      checked={isSel}
                      disabled={!fix.trim()}
                      onChange={() => review.onToggle(r.finding_id)}
                    />
                  </td>
                )}
                <td className="num">{numbers.get(r.finding_id)}</td>
                <td className="nowrap">{r.clause_ref}</td>
                <td>
                  <GapBadge gap={r.gap_type} />
                </td>
                <td>
                  <SeverityBadge severity={r.severity} />
                </td>
                <td className="issue">{r.issue}</td>
                <td className="src" data-label="Source">
                  {r.source}
                </td>
                <td className="fix" data-label="Suggested fix" onClick={(e) => reviewable && e.stopPropagation()}>
                  {reviewable && editing === r.finding_id ? (
                    <div className="fix-edit">
                      <textarea
                        value={draft}
                        autoFocus
                        rows={Math.min(8, Math.max(3, Math.ceil(draft.length / 60)))}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') setEditing(null)
                          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) saveEdit(r)
                        }}
                      />
                      <div className="fix-edit-actions">
                        <button className="btn primary small" onClick={() => saveEdit(r)}>
                          Save
                        </button>
                        <button className="btn ghost small" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <span>{fix || <em className="muted">No suggestion</em>}</span>
                      {reviewable && (
                        <span className="fix-meta">
                          {edited !== undefined && <span className="edited-tag">Edited by reviewer</span>}
                          <button className="link-btn" onClick={() => startEdit(r)}>
                            Edit
                          </button>
                          {edited !== undefined && (
                            <button className="link-btn" onClick={() => review.onEdit(r.finding_id, null)}>
                              Reset
                            </button>
                          )}
                        </span>
                      )}
                    </>
                  )}
                </td>
              </tr>
            )
          })}
          {shown.length === 0 && (
            <tr>
              <td colSpan={reviewable ? 8 : 7} className="empty">
                No gaps match this filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
