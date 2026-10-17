import { useEffect, useRef } from 'react'
import { ArrowDownIcon, BankIcon } from './Icons'

interface Props {
  leaving: boolean
  onDone: () => void
}

/** Full-screen logo moment on load; moves up out of view to reveal the app. */
export default function Intro({ leaving, onDone }: Props) {
  const done = useRef(false)
  const finish = () => {
    if (done.current) return
    done.current = true
    onDone()
  }
  useEffect(() => {
    const t = window.setTimeout(finish, 2600)
    const onKey = (e: KeyboardEvent) => ['Enter', ' ', 'ArrowDown', 'PageDown', 'Escape'].includes(e.key) && finish()
    const onWheel = (e: WheelEvent) => e.deltaY > 0 && finish()
    let touchY = 0
    const onTouchStart = (e: TouchEvent) => (touchY = e.touches[0].clientY)
    const onTouchMove = (e: TouchEvent) => touchY - e.touches[0].clientY > 30 && finish()
    window.addEventListener('keydown', onKey)
    window.addEventListener('wheel', onWheel, { passive: true })
    window.addEventListener('touchstart', onTouchStart, { passive: true })
    window.addEventListener('touchmove', onTouchMove, { passive: true })
    return () => {
      window.clearTimeout(t)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('wheel', onWheel)
      window.removeEventListener('touchstart', onTouchStart)
      window.removeEventListener('touchmove', onTouchMove)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className={`intro ${leaving ? 'leaving' : ''}`} onClick={finish} aria-hidden={leaving}>
      <div className="intro-inner">
        <div className="intro-lockup">
          <span className="intro-seal">
            <BankIcon />
          </span>
          <h1 className="intro-word">
            Compl<span>AI</span>
          </h1>
        </div>
        <p className="intro-slogan">Check every policy clause against the regulations, and approve each fix yourself.</p>
        <button className="intro-cue" onClick={finish} aria-label="Continue to the app">
          Continue
          <ArrowDownIcon />
        </button>
      </div>
    </div>
  )
}
