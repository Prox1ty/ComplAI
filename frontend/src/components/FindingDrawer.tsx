import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { Finding } from '../types'
import FindingDetail from './FindingDetail'
import { CloseIcon } from './Icons'

interface Props {
  findings: Finding[] | null
  numbers: Map<string, number>
  onClose: () => void
}

/** Phone: issues and suggestions slide in from the right over the report. */
export default function FindingDrawer({ findings, numbers, onClose }: Props) {
  const open = !!findings?.length
  const closeRef = useRef<HTMLButtonElement>(null)
  const last = useRef<Finding[]>([])
  if (findings?.length) last.current = findings // keep content while the drawer slides out
  const shown = open ? findings! : last.current
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    window.setTimeout(() => closeRef.current?.focus({ preventScroll: true }), 50)
    return () => {
      document.body.style.overflow = prev
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  const title = shown.length > 1 ? `${shown.length} issues in this passage` : 'Issue'
  // Rendered into <body>: an animated (transformed) ancestor would otherwise become the
  // containing block for position:fixed and the drawer would scroll away with the page.
  return createPortal(
    <>
      <div className={`drawer-backdrop no-print ${open ? 'open' : ''}`} onClick={onClose} aria-hidden />
      <div className="drawer-layer no-print">
        <aside
          className={`drawer no-print ${open ? 'open' : ''}`}
          role="dialog"
          aria-modal="true"
          aria-label={title}
          aria-hidden={!open}
        >
          <div className="drawer-head">
            <h2>{title}</h2>
            <button ref={closeRef} className="icon-btn" onClick={onClose} aria-label="Close">
              <CloseIcon />
            </button>
          </div>
          <div className="drawer-body">
            {shown.map((f) => (
              <FindingDetail key={f.id} finding={f} number={numbers.get(f.id)} />
            ))}
          </div>
        </aside>
      </div>
    </>,
    document.body,
  )
}
