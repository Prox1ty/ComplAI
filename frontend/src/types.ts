// Mirror of backend/schemas.py (Result contract). Keep in sync.

export type GapType = 'CONTRADICTION' | 'INSUFFICIENT' | 'AMBIGUOUS' | 'MISSING' | 'OUTDATED'
export type Severity = 'high' | 'medium' | 'low'
export type VerificationStatus = 'verified' | 'partial' | 'unverified'
export type Phase = 'parsing' | 'searching' | 'analysing' | 'verifying' | 'suggesting' | 'done' | 'error'

export interface Meta {
  country: string
  region?: string | null
  city?: string | null
  timezone: string
  as_of: string
  policy_type: string
  institution_type: string
  generated_at: string
  jurisdiction_chain?: string[]
}

export interface Clause {
  id: string
  text: string
  start: number
  end: number
  section?: string | null
  label?: string | null
}

export interface Citation {
  doc_id: string
  chunk_id: string
  quote: string
  source_title: string
  source_url: string
  section?: string | null
}

export interface Finding {
  id: string
  clause_ids: string[]
  span: { start: number; end: number }
  gap_type: GapType
  severity: Severity
  title: string
  explanation: string
  citations: Citation[]
  suggestion: { text: string; rationale: string }
  verification: { status: VerificationStatus; note?: string | null }
  inference_notes: string[]
}

export interface GapRow {
  finding_id: string
  clause_ref: string
  gap_type: GapType
  severity: Severity
  issue: string
  source: string
  fix: string
}

export interface Result {
  run_id: string
  meta: Meta
  policy: { filename: string; full_text: string; clauses: Clause[] }
  findings: Finding[]
  gap_table: GapRow[]
  coverage: { obligations_total: number; met: number; partial: number; missing: number }
  sources: { doc_id: string; title: string; issuer?: string | null; url: string; jurisdiction: string }[]
  stats: {
    tokens_in: number
    tokens_out: number
    llm_calls: number
    duration_s: number
    web_searches?: number
    cache_hits?: number
    reduced_mode?: boolean
  }
}

export interface ProgressEvent {
  phase: Phase
  status: 'started' | 'progress' | 'completed' | 'failed'
  detail: string
  progress: number
}

export interface LocationInputs {
  country: string
  region: string
  city: string
  timezone: string
  policy_type: string
  institution_type: string
}

export const POLICY_TYPES = [
  'AML/KYC',
  'Credit risk',
  'Data privacy',
  'Operational risk',
  'Liquidity',
  'Consumer protection',
  'Other',
] as const

export const INSTITUTION_TYPES = ['Commercial bank', 'Digital bank', 'Credit union', 'Microfinance', 'Other'] as const

// Human in the loop: reviewer-approved fixes (mirror of backend Revision)
export interface FixSelection {
  finding_id: string
  text?: string | null
}

export interface AppliedChange {
  finding_id: string
  kind: 'replace' | 'insert'
  start: number
  end: number
  old_text: string
  new_text: string
}

export interface SkippedFix {
  finding_id?: string | null
  reason: string
  conflicts_with?: string | null
}

export interface Revision {
  run_id: string
  full_text: string
  changes: AppliedChange[]
  skipped: SkippedFix[]
  docx_url: string
  txt_url: string
  docx_from_original?: boolean
  unplaced?: string[]
}
