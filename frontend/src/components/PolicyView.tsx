import { memo } from 'react'
import type { Finding } from '../types'
import type { Segment } from '../lib/segments'

interface Props {
  text: string
  segments: Segment[]
  numbers: Map<string, number>
  openKey: string | null
  onOpen: (key: string, findings: Finding[], el: HTMLElement, pin: boolean) => void
  onLeave: () => void
}

function PolicyView({ text, segments, numbers, openKey, onOpen, onLeave }: Props) {
  const nums = (fs: Finding[]) =>
    fs
      .map((f) => numbers.get(f.id))
      .filter((n): n is number => n !== undefined)
      .sort((a, b) => a - b)
      .join(',')

  return (
    <div className="policy-text">
      {segments.map((seg) => {
        const body = text.slice(seg.start, seg.end)
        const markers = seg.markers.map((m) => {
          const key = `m-${m.id}`
          return (
            <button
              key={key}
              type="button"
              className={`missing-marker sev-${m.severity} ${openKey === key ? 'open' : ''}`}
              data-fids={m.id}
              aria-label={`Missing obligation: ${m.title}`}
              onMouseEnter={(e) => onOpen(key, [m], e.currentTarget, false)}
              onMouseLeave={onLeave}
              onFocus={(e) => onOpen(key, [m], e.currentTarget, false)}
              onBlur={onLeave}
              onClick={(e) => onOpen(key, [m], e.currentTarget, true)}
            >
              + Missing<sup className="fn">{numbers.get(m.id)}</sup>
            </button>
          )
        })
        if (!seg.findings.length) {
          return (
            <span key={seg.key}>
              {body}
              {markers}
            </span>
          )
        }
        return (
          <span key={seg.key}>
            <mark
              className={`hl sev-${seg.severity} ${openKey === seg.key ? 'open' : ''}`}
              tabIndex={0}
              role="button"
              aria-label={`${seg.findings.length} finding(s): ${seg.findings.map((f) => f.title).join('; ')}`}
              data-fids={seg.findings.map((f) => f.id).join(' ')}
              onMouseEnter={(e) => onOpen(seg.key, seg.findings, e.currentTarget, false)}
              onMouseLeave={onLeave}
              onFocus={(e) => onOpen(seg.key, seg.findings, e.currentTarget, false)}
              onBlur={onLeave}
              onClick={(e) => onOpen(seg.key, seg.findings, e.currentTarget, true)}
            >
              {body}
            </mark>
            <sup className="fn">{nums(seg.findings)}</sup>
            {markers}
          </span>
        )
      })}
    </div>
  )
}

export default memo(PolicyView)
