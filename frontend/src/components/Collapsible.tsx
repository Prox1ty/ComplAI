import { useEffect, useId, useState, type ReactNode } from 'react'
import { ChevronIcon } from './Icons'

interface Props {
  title: string
  count?: ReactNode
  open: boolean
  onToggle: () => void
  actions?: ReactNode // always visible, even when collapsed
  children: ReactNode
  headingLevel?: 'h2' | 'h3'
}

/** Section whose header (and action buttons) stay visible while the body expands or collapses. */
export default function Collapsible({ title, count, open, onToggle, actions, children, headingLevel = 'h2' }: Props) {
  const id = useId()
  const H = headingLevel
  // Once fully open, stop clipping so popups inside the section are not cut off.
  const [settled, setSettled] = useState(open)
  useEffect(() => {
    if (!open) {
      setSettled(false)
      return
    }
    const t = window.setTimeout(() => setSettled(true), 340)
    return () => window.clearTimeout(t)
  }, [open])
  return (
    <>
      <div className="section-head">
        <button className="section-toggle" aria-expanded={open} aria-controls={id} onClick={onToggle}>
          <span className="chev" aria-hidden>
            <ChevronIcon />
          </span>
          <H>{title}</H>
          {count !== undefined && <span className="section-count">{count}</span>}
        </button>
        {actions && <div className="section-actions">{actions}</div>}
      </div>
      <div id={id} className={`collapse ${open ? '' : 'closed'} ${open && settled ? 'settled' : ''}`}>
        <div className="collapse-inner">
          <div className="collapse-pad">{children}</div>
        </div>
      </div>
    </>
  )
}
