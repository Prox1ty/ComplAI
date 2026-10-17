import mockResult from '../../mock/result.json'
import type { FixSelection, LocationInputs, ProgressEvent, Result, Revision } from '../types'
import { applyFixesLocal } from './applyFixes'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === '1'
const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

export async function startRun(inputs: LocationInputs, file: File): Promise<string> {
  if (USE_MOCK) return 'mock-run'
  const fd = new FormData()
  fd.append('file', file)
  Object.entries(inputs).forEach(([k, v]) => fd.append(k, v ?? ''))
  const res = await fetch(`${BASE}/api/runs`, { method: 'POST', body: fd })
  if (!res.ok) {
    let msg = `Upload failed (${res.status})`
    try {
      const body = await res.json()
      msg = body.detail ?? msg
    } catch {
      /* keep default message */
    }
    throw new Error(msg)
  }
  const body = (await res.json()) as { run_id: string }
  return body.run_id
}

export function subscribe(runId: string, onEvent: (e: ProgressEvent) => void): () => void {
  if (USE_MOCK) return simulate(onEvent)
  const es = new EventSource(`${BASE}/api/runs/${runId}/events`)
  let finished = false
  es.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data) as ProgressEvent
      onEvent(ev)
      if (ev.phase === 'done' || ev.phase === 'error') {
        finished = true
        es.close()
      }
    } catch {
      /* ignore malformed frames */
    }
  }
  es.onerror = () => {
    if (finished) return
    // EventSource auto-reconnects; only surface an error if the stream is closed for good.
    if (es.readyState === EventSource.CLOSED) {
      onEvent({ phase: 'error', status: 'failed', detail: 'Lost connection to the server.', progress: 0 })
    }
  }
  return () => es.close()
}

export async function getResult(runId: string, inputs?: LocationInputs): Promise<Result> {
  if (USE_MOCK) {
    const r = structuredClone(mockResult) as unknown as Result
    if (inputs) {
      r.meta = {
        ...r.meta,
        country: inputs.country,
        region: inputs.region || null,
        city: inputs.city || null,
        timezone: inputs.timezone,
        policy_type: inputs.policy_type,
        institution_type: inputs.institution_type,
      }
    }
    return r
  }
  const res = await fetch(`${BASE}/api/runs/${runId}/result`)
  if (!res.ok) throw new Error(`Could not load the report (${res.status})`)
  return (await res.json()) as Result
}

export async function applyFixes(result: Result, fixes: FixSelection[]): Promise<Revision> {
  if (USE_MOCK) return applyFixesLocal(result, fixes)
  const res = await fetch(`${BASE}/api/runs/${result.run_id}/apply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fixes }),
  })
  if (!res.ok) {
    let msg = `Could not apply fixes (${res.status})`
    try {
      msg = (await res.json()).detail ?? msg
    } catch {
      /* keep default */
    }
    throw new Error(msg)
  }
  const rev = (await res.json()) as Revision
  return { ...rev, docx_url: `${BASE}${rev.docx_url}`, txt_url: `${BASE}${rev.txt_url}` }
}

function simulate(onEvent: (e: ProgressEvent) => void): () => void {
  const script: ProgressEvent[] = [
    { phase: 'parsing', status: 'started', detail: 'Reading sample_aml_policy.txt', progress: 0.03 },
    { phase: 'parsing', status: 'completed', detail: 'Found 15 clauses', progress: 0.1 },
    { phase: 'searching', status: 'started', detail: 'Resolving jurisdiction chain', progress: 0.13 },
    { phase: 'searching', status: 'progress', detail: 'Registry covers all topics, skipping web search', progress: 0.22 },
    { phase: 'searching', status: 'progress', detail: 'Building regulatory context', progress: 0.34 },
    { phase: 'analysing', status: 'started', detail: 'Reviewing group 1 of 4', progress: 0.42 },
    { phase: 'analysing', status: 'progress', detail: 'Reviewing group 2 of 4', progress: 0.5 },
    { phase: 'analysing', status: 'progress', detail: 'Reviewing group 3 of 4', progress: 0.57 },
    { phase: 'analysing', status: 'progress', detail: 'Coverage check: 14 obligations', progress: 0.66 },
    { phase: 'verifying', status: 'started', detail: 'Checking citations', progress: 0.74 },
    { phase: 'verifying', status: 'progress', detail: 'Entailment batch 1 of 1', progress: 0.82 },
    { phase: 'suggesting', status: 'started', detail: 'Drafting rewrites 1 of 2', progress: 0.88 },
    { phase: 'suggesting', status: 'progress', detail: 'Drafting rewrites 2 of 2', progress: 0.95 },
    { phase: 'done', status: 'completed', detail: 'Report ready', progress: 1 },
  ]
  const timers = script.map((ev, i) => window.setTimeout(() => onEvent(ev), 450 + i * 520))
  return () => timers.forEach((t) => window.clearTimeout(t))
}
