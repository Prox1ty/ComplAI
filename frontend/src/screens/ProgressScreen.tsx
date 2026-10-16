import { useEffect, useRef, useState } from 'react'
import type { LocationInputs, Phase, Result } from '../types'
import { getResult, startRun, subscribe } from '../lib/api'

interface Props {
  inputs: LocationInputs
  file: File
  onDone: (r: Result) => void
  onCancel: () => void
}

const STEPS: { phase: Phase; label: string }[] = [
  { phase: 'parsing', label: 'Reading policy' },
  { phase: 'searching', label: 'Searching regulations' },
  { phase: 'analysing', label: 'Analysing' },
  { phase: 'verifying', label: 'Verifying' },
  { phase: 'suggesting', label: 'Suggesting improvements' },
]

export default function ProgressScreen({ inputs, file, onDone, onCancel }: Props) {
  const [attempt, setAttempt] = useState(0)
  const [active, setActive] = useState(0)
  const [detail, setDetail] = useState('Uploading…')
  const [progress, setProgress] = useState(0.02)
  const [error, setError] = useState<string | null>(null)
  const started = useRef<{ attempt: number; promise: Promise<string> } | null>(null)
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    let cancelled = false
    let unsub: (() => void) | undefined
    setError(null)
    setActive(0)
    setProgress(0.02)
    setDetail('Uploading…')

    // Guard against StrictMode double-invocation starting two runs.
    if (!started.current || started.current.attempt !== attempt) {
      started.current = { attempt, promise: startRun(inputs, file) }
    }
    started.current.promise
      .then((runId) => {
        if (cancelled) return
        unsub = subscribe(runId, (ev) => {
          if (cancelled) return
          if (ev.phase === 'error') {
            setError(ev.detail || 'The analysis failed.')
            return
          }
          if (ev.phase === 'done') {
            setActive(STEPS.length)
            setProgress(1)
            setDetail('Report ready')
            getResult(runId, inputs)
              .then((r) => !cancelled && window.setTimeout(() => doneRef.current(r), 450))
              .catch((e: Error) => !cancelled && setError(e.message))
            return
          }
          const idx = STEPS.findIndex((s) => s.phase === ev.phase)
          if (idx >= 0) setActive((a) => Math.max(a, idx))
          if (ev.detail) setDetail(ev.detail)
          setProgress((p) => Math.max(p, ev.progress))
        })
      })
      .catch((e: Error) => !cancelled && setError(e.message))

    return () => {
      cancelled = true
      unsub?.()
    }
  }, [attempt, file, inputs])

  return (
    <section className="card narrow">
      <p className="eyebrow">{file.name}</p>
      <h1>{error ? 'Analysis stopped' : active >= STEPS.length ? 'Analysis complete' : 'Reviewing your policy'}</h1>
      <div className="progress-track" aria-hidden>
        <div className="progress-fill" style={{ width: `${Math.round(progress * 100)}%` }} />
      </div>
      <ol className="stepper" aria-live="polite">
        {STEPS.map((s, i) => {
          const state = i < active ? 'done' : i === active ? (error ? 'failed' : 'active') : 'todo'
          return (
            <li key={s.phase} className={`step ${state}`}>
              <span className="step-dot">{state === 'done' ? '✓' : state === 'failed' ? '!' : i + 1}</span>
              <div>
                <span className="step-label">{s.label}</span>
                {state === 'active' && <span className="step-detail">{detail}</span>}
                {state === 'failed' && <span className="step-detail error-text">{error}</span>}
              </div>
            </li>
          )
        })}
      </ol>
      {error && (
        <div className="actions">
          <button className="btn primary" onClick={() => setAttempt((a) => a + 1)}>
            Retry
          </button>
          <button className="btn ghost" onClick={onCancel}>
            Back
          </button>
        </div>
      )}
    </section>
  )
}
