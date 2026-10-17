import type { Revision } from '../types'
import { USE_MOCK } from '../lib/api'
import Collapsible from './Collapsible'

interface Props {
  revision: Revision
  numbers: Map<string, number>
  filename: string
  open: boolean
  onToggle: () => void
  onBack: () => void
}

function downloadText(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** The revised policy after the reviewer's approved fixes, with every change visible. */
export default function RevisionPanel({ revision, numbers, filename, open, onToggle, onBack }: Props) {
  const stem = filename.replace(/\.[^.]+$/, '')
  const text = revision.full_text
  const changes = [...revision.changes].sort((a, b) => a.start - b.start)
  const parts: JSX.Element[] = []
  let cursor = 0
  changes.forEach((c, i) => {
    if (c.start > cursor) parts.push(<span key={`t${i}`}>{text.slice(cursor, c.start)}</span>)
    parts.push(
      <span key={`c${i}`} className="change" title={`Fix ${numbers.get(c.finding_id) ?? c.finding_id}`}>
        {c.kind === 'replace' && <del className="change-old">{c.old_text}</del>}
        <ins className="change-new">{text.slice(c.start, c.end)}</ins>
        <sup className="change-num">{numbers.get(c.finding_id)}</sup>
      </span>,
    )
    cursor = c.end
  })
  parts.push(<span key="tail">{text.slice(cursor)}</span>)

  const replaced = revision.changes.filter((c) => c.kind === 'replace').length
  const added = revision.changes.length - replaced

  return (
    <section className="card revision" id="revision">
      <Collapsible
        title="Revised policy"
        count={`${revision.changes.length} fix${revision.changes.length === 1 ? '' : 'es'} applied`}
        open={open}
        onToggle={onToggle}
        actions={
          <div className="revision-actions no-print">
            <button className="btn ghost" onClick={onBack}>
              Change selection
            </button>
            {USE_MOCK ? (
              <button className="btn primary" disabled title="Word export needs the backend (demo mode)">
                Download Word
              </button>
            ) : (
              <a className="btn primary" href={revision.docx_url} download>
                Download Word
              </a>
            )}
            {USE_MOCK ? (
              <button className="btn ghost" onClick={() => downloadText(text, `${stem}_revised.txt`)}>
                Download .txt
              </button>
            ) : (
              <a className="btn ghost" href={revision.txt_url} download>
                Download .txt
              </a>
            )}
          </div>
        }
      >
        <p className="eyebrow">Your decisions applied</p>
        <p className="muted small">
          {replaced} clause{replaced === 1 ? '' : 's'} rewritten, {added} new clause{added === 1 ? '' : 's'} added.
          Removed wording is struck through and new wording highlighted here so you can review it; the download contains
          only the final text.
        </p>
        {revision.skipped.length > 0 && (
          <div className="skipped">
            <strong>Not applied ({revision.skipped.length})</strong>
            <ul>
              {revision.skipped.map((s, i) => (
                <li key={i}>
                  {s.finding_id && <b>Fix {numbers.get(s.finding_id) ?? s.finding_id}: </b>}
                  {s.reason.replace(/\bF(\d+)\b/g, (m) => `fix ${numbers.get(m) ?? m}`)}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!!revision.unplaced?.length && (
          <p className="muted small">
            {revision.unplaced.length} change(s) could not be placed in the Word layout automatically and were listed at
            the end of the Word file.
          </p>
        )}
        {!USE_MOCK && (
          <p className="muted small">
            The Word file contains only the final wording, with no strikethrough or highlighting.{' '}
            {revision.docx_from_original
              ? 'It is your original document with the approved fixes written in, so its formatting is unchanged.'
              : 'It is generated from the policy text.'}{' '}
            The marked-up view below is for review only.
          </p>
        )}

        <div className="policy-text revised-text">{parts}</div>
      </Collapsible>
    </section>
  )
}
