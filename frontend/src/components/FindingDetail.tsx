import { useState } from 'react'
import type { Finding } from '../types'
import { GapBadge, SeverityBadge, VerificationBadge } from './Badges'

interface Props {
  finding: Finding
  number?: number
  print?: boolean
}

/** The content of one finding; used both in the hover popup and in the printed Findings section. */
export default function FindingDetail({ finding: f, number, print = false }: Props) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(f.suggestion.text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = f.suggestion.text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }

  return (
    <article className="finding">
      <header className="finding-head">
        {number !== undefined && <span className="finding-num">{number}</span>}
        <h3>{f.title}</h3>
      </header>
      <div className="badges">
        <SeverityBadge severity={f.severity} />
        <GapBadge gap={f.gap_type} />
        <VerificationBadge status={f.verification.status} note={f.verification.note} />
      </div>
      <p className="finding-expl">{f.explanation}</p>
      {f.verification.note && <p className="finding-note">Verifier: {f.verification.note}</p>}
      {f.citations.map((c) => (
        <blockquote key={c.chunk_id} className="cite">
          <span className="cite-quote">“{c.quote}”</span>
          <a href={c.source_url} target="_blank" rel="noreferrer">
            {c.source_title}
            {c.section ? `, ${c.section}` : ''}
          </a>
          {print && <span className="print-url">{c.source_url}</span>}
        </blockquote>
      ))}
      {f.inference_notes.length > 0 && (
        <p className="finding-note">Context: {f.inference_notes.join(' ')}</p>
      )}
      {f.suggestion.text && (
        <div className="suggestion">
          <div className="suggestion-head">
            <span>Suggested {f.gap_type === 'MISSING' ? 'new clause' : 'rewrite'}</span>
            {!print && (
              <button className="btn ghost small no-print" onClick={copy}>
                {copied ? 'Copied' : 'Copy'}
              </button>
            )}
          </div>
          <p className="suggestion-text">{f.suggestion.text}</p>
          {f.suggestion.rationale && <p className="suggestion-why">{f.suggestion.rationale}</p>}
        </div>
      )}
    </article>
  )
}
