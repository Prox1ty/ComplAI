import { useRef, useState } from 'react'
import type { LocationInputs } from '../types'
import { jurisdictionLabel } from '../lib/geo'

interface Props {
  inputs: LocationInputs
  file: File | null
  onFile: (f: File | null) => void
  onEdit: () => void
  onAnalyse: () => void
}

const MAX_BYTES = 10 * 1024 * 1024
const EXT = ['pdf', 'docx', 'txt']

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export default function DashboardScreen({ inputs, file, onFile, onEdit, onAnalyse }: Props) {
  const ref = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const accept = (f: File | undefined) => {
    if (!f) return
    const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
    if (!EXT.includes(ext)) return setError('Please upload a PDF, DOCX or TXT file.')
    if (f.size > MAX_BYTES) return setError('The file is larger than 10 MB.')
    setError(null)
    onFile(f)
  }

  return (
    <section className="card narrow">
      <p className="eyebrow">Step 2 of 2</p>
      <h1>Upload your draft policy</h1>
      <button className="chip" onClick={onEdit} title="Edit jurisdiction">
        <span className="chip-dot" aria-hidden />
        {jurisdictionLabel(inputs)} · {inputs.policy_type} · {inputs.institution_type}
        <span className="chip-edit">Edit</span>
      </button>

      <div
        className={`dropzone ${drag ? 'drag' : ''} ${file ? 'has-file' : ''}`}
        role="button"
        tabIndex={0}
        onClick={() => ref.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && ref.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDrag(false)
          accept(e.dataTransfer.files[0])
        }}
      >
        <input
          ref={ref}
          type="file"
          accept=".pdf,.docx,.txt"
          hidden
          onChange={(e) => {
            accept(e.target.files?.[0])
            e.target.value = ''
          }}
        />
        {file ? (
          <div className="file-info">
            <span className="file-icon" aria-hidden>
              {file.name.split('.').pop()?.toUpperCase()}
            </span>
            <div>
              <strong>{file.name}</strong>
              <span>{formatBytes(file.size)}</span>
            </div>
            <button
              className="btn ghost small"
              onClick={(e) => {
                e.stopPropagation()
                onFile(null)
              }}
            >
              Remove
            </button>
          </div>
        ) : (
          <>
            <p className="drop-title">Drag and drop your policy here</p>
            <p className="drop-sub">or click to browse · PDF, DOCX or TXT · up to 10 MB</p>
          </>
        )}
      </div>
      {error && <p className="error-text">{error}</p>}

      <button className="btn primary" disabled={!file} onClick={onAnalyse}>
        Analyse policy
      </button>
    </section>
  )
}
