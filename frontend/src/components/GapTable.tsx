import { useMemo, useState } from 'react'
import type { GapRow, GapType } from '../types'
import { GAP_LABEL, GapBadge, SeverityBadge } from './Badges'
import { SEV_RANK } from '../lib/segments'

interface Props {
  rows: GapRow[]
  numbers: Map<string, number>
  onRowClick: (findingId: string) => void
  printMode?: boolean
}

export default function GapTable({ rows, numbers, onRowClick, printMode = false }: Props) {
  const [desc, setDesc] = useState(true)
  const [filter, setFilter] = useState<GapType | 'ALL'>('ALL')
  const types = useMemo(() => [...new Set(rows.map((r) => r.gap_type))], [rows])

  const shown = useMemo(() => {
    const list = printMode ? [...rows] : rows.filter((r) => filter === 'ALL' || r.gap_type === filter)
    return list.sort((a, b) => {
      if (printMode) return (numbers.get(a.finding_id) ?? 0) - (numbers.get(b.finding_id) ?? 0)
      const d = SEV_RANK[a.severity] - SEV_RANK[b.severity]
      return (desc ? -d : d) || (numbers.get(a.finding_id) ?? 0) - (numbers.get(b.finding_id) ?? 0)
    })
  }, [rows, filter, desc, numbers, printMode])

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
        </div>
      )}
      <table className="gap-table">
        <thead>
          <tr>
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
          {shown.map((r) => (
            <tr
              key={r.finding_id}
              tabIndex={printMode ? undefined : 0}
              onClick={() => onRowClick(r.finding_id)}
              onKeyDown={(e) => e.key === 'Enter' && onRowClick(r.finding_id)}
            >
              <td className="num">{numbers.get(r.finding_id)}</td>
              <td className="nowrap">{r.clause_ref}</td>
              <td>
                <GapBadge gap={r.gap_type} />
              </td>
              <td>
                <SeverityBadge severity={r.severity} />
              </td>
              <td>{r.issue}</td>
              <td className="src">{r.source}</td>
              <td className="fix">{r.fix}</td>
            </tr>
          ))}
          {shown.length === 0 && (
            <tr>
              <td colSpan={7} className="empty">
                No gaps match this filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
