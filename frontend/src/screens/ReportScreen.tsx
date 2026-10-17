import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Finding, Result, Revision } from '../types'
import { buildSegments, numberFindings } from '../lib/segments'
import { jurisdictionLabel } from '../lib/geo'
import PolicyView from '../components/PolicyView'
import FindingDetail from '../components/FindingDetail'
import GapTable, { ApplyButtons } from '../components/GapTable'
import RevisionPanel from '../components/RevisionPanel'
import Collapsible from '../components/Collapsible'
import FindingDrawer from '../components/FindingDrawer'
import { applyFixes } from '../lib/api'
import { PHONE_QUERY, useMediaQuery } from '../lib/useMediaQuery'

interface Props {
  result: Result
  onNew: () => void
}

interface Popup {
  key: string
  findings: Finding[]
  top: number
  left: number
  width: number
  pinned: boolean
}

const POPUP_W = 400

export default function ReportScreen({ result, onNew }: Props) {
  const { meta, policy, findings, coverage, stats } = result
  const segments = useMemo(() => buildSegments(policy.full_text, findings), [policy.full_text, findings])
  const numbers = useMemo(() => numberFindings(findings), [findings])
  const ordered = useMemo(
    () => [...findings].sort((a, b) => (numbers.get(a.id) ?? 0) - (numbers.get(b.id) ?? 0)),
    [findings, numbers],
  )
  const counts = useMemo(
    () => ({
      high: findings.filter((f) => f.severity === 'high').length,
      medium: findings.filter((f) => f.severity === 'medium').length,
      low: findings.filter((f) => f.severity === 'low').length,
    }),
    [findings],
  )
  const covered = coverage.obligations_total
    ? Math.round(((coverage.met + coverage.partial * 0.5) / coverage.obligations_total) * 100)
    : null

  const wrapRef = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<number>()
  const [popup, setPopup] = useState<Popup | null>(null)
  // Phone: tapping a passage opens a drawer from the right instead of an inline popup.
  const isPhone = useMediaQuery(PHONE_QUERY)
  const [drawer, setDrawer] = useState<{ key: string; findings: Finding[] } | null>(null)
  const closeDrawer = useCallback(() => setDrawer(null), [])

  // Collapsible sections; the report header (buttons, stats) always stays visible.
  const [sections, setSections] = useState({ analysis: true, gaps: true, revision: true })
  const toggleSection = (k: keyof typeof sections) => setSections((s) => ({ ...s, [k]: !s[k] }))
  const openSection = (k: keyof typeof sections) => setSections((s) => (s[k] ? s : { ...s, [k]: true }))

  // Human in the loop: the reviewer picks which fixes to accept and may edit them.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [revision, setRevision] = useState<Revision | null>(null)
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const fixable = useMemo(
    () => result.gap_table.filter((r) => (edits[r.finding_id] ?? r.fix).trim()).map((r) => r.finding_id),
    [result.gap_table, edits],
  )

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const toggleAll = (ids: string[], on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)))
      return next
    })
  const editFix = (id: string, text: string | null) =>
    setEdits((prev) => {
      const next = { ...prev }
      if (text === null) delete next[id]
      else next[id] = text
      return next
    })
  const apply = async (mode: 'all' | 'selected') => {
    const ids = mode === 'all' ? fixable : fixable.filter((id) => selected.has(id))
    if (mode === 'all') setSelected(new Set(ids))
    setApplying(true)
    setApplyError(null)
    try {
      const rev = await applyFixes(
        result,
        ids.map((id) => ({ finding_id: id, text: edits[id] ?? null })),
      )
      setRevision(rev)
      openSection('revision')
      window.setTimeout(() => document.getElementById('revision')?.scrollIntoView({ behavior: 'smooth' }), 80)
    } catch (e) {
      setApplyError((e as Error).message)
    } finally {
      setApplying(false)
    }
  }

  const cancelClose = () => window.clearTimeout(closeTimer.current)
  const scheduleClose = useCallback(() => {
    window.clearTimeout(closeTimer.current)
    closeTimer.current = window.setTimeout(() => setPopup((p) => (p && !p.pinned ? null : p)), 180)
  }, [])

  const open = useCallback(
    (key: string, fs: Finding[], el: HTMLElement, pin: boolean) => {
      if (isPhone) {
        // hover/focus also fire on tap; only an explicit tap (pin) opens the drawer
        if (pin) setDrawer({ key, findings: fs })
        return
      }
      window.clearTimeout(closeTimer.current)
      const wrap = wrapRef.current
      if (!wrap) return
      const w = wrap.getBoundingClientRect()
      const rects = el.getClientRects()
      const r = rects.length ? rects[rects.length - 1] : el.getBoundingClientRect()
      const width = Math.min(POPUP_W, w.width - 16)
      const left = Math.max(8, Math.min(r.left - w.left, w.width - width - 8))
      setPopup((p) => ({
        key,
        findings: fs,
        top: r.bottom - w.top + 8,
        left,
        width,
        pinned: pin ? true : Boolean(p?.key === key && p.pinned),
      }))
    },
    [isPhone],
  )

  // switching between phone and desktop layouts closes whichever view is open
  useEffect(() => {
    setPopup(null)
    setDrawer(null)
  }, [isPhone])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setPopup(null)
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement
      if (!t.closest('.popup') && !t.closest('.hl') && !t.closest('.missing-marker')) setPopup(null)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
      window.clearTimeout(closeTimer.current)
    }
  }, [])

  const flashTo = (fid: string) => {
    const wasOpen = sections.analysis
    openSection('analysis')
    window.setTimeout(
      () => {
        const el = wrapRef.current?.querySelector<HTMLElement>(`[data-fids~="${fid}"]`)
        if (!el) return
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        el.classList.remove('flash')
        void el.offsetWidth
        el.classList.add('flash')
        window.setTimeout(() => el.classList.remove('flash'), 1600)
      },
      wasOpen ? 0 : 360,
    ) // wait for the section to expand
  }

  return (
    <div className="report">
      <section className="report-head card">
        <div className="report-title">
          <div>
            <p className="eyebrow">Gap report · {policy.filename}</p>
            <h1>{jurisdictionLabel(meta)}</h1>
            <p className="muted">
              {meta.policy_type} · {meta.institution_type} · regulations as of <strong>{meta.as_of}</strong> (
              {meta.timezone})
            </p>
          </div>
          <div className="report-actions no-print">
            <button className="btn ghost" onClick={onNew}>
              New analysis
            </button>
            <button className="btn primary" onClick={() => window.print()}>
              Export PDF
            </button>
          </div>
        </div>
        <div className="stats">
          <div className="stat high">
            <strong>{counts.high}</strong>
            <span>High</span>
          </div>
          <div className="stat medium">
            <strong>{counts.medium}</strong>
            <span>Medium</span>
          </div>
          <div className="stat low">
            <strong>{counts.low}</strong>
            <span>Low</span>
          </div>
          <div className="stat coverage">
            <strong>{covered === null ? '—' : `${covered}%`}</strong>
            <span>
              Coverage · {coverage.met} met, {coverage.partial} partial, {coverage.missing} missing of{' '}
              {coverage.obligations_total} obligations
            </span>
          </div>
        </div>
        <p className="disclaimer">
          Decision support for compliance officers, not legal advice. Findings cite the regulatory text they rely on;
          confirm each against the source before acting.
        </p>
      </section>

      {findings.length === 0 && (
        <section className="card empty-state">
          <h2>No gaps found</h2>
          <p className="muted">
            Every substantive clause was checked against the retrieved regulations and no supported issue was found.
          </p>
        </section>
      )}

      <section className="card policy-card">
        <Collapsible
          title="Policy analysis"
          count={`${findings.length} finding${findings.length === 1 ? '' : 's'} in ${policy.clauses.length} clauses`}
          open={sections.analysis}
          onToggle={() => toggleSection('analysis')}
        >
          <div className="legend no-print">
            <span>
              <i className="lg lg-high" /> High
            </span>
            <span>
              <i className="lg lg-medium" /> Medium
            </span>
            <span>
              <i className="lg lg-low" /> Low
            </span>
            <span>
              <i className="lg lg-missing">+</i> Missing obligation
            </span>
            <span className="muted">
              {isPhone ? 'Tap highlighted text for details.' : 'Hover, focus or click highlighted text for details.'}
            </span>
          </div>
          <div className="policy-wrap" ref={wrapRef}>
            <PolicyView
              text={policy.full_text}
              segments={segments}
              numbers={numbers}
              openKey={(isPhone ? drawer?.key : popup?.key) ?? null}
              onOpen={open}
              onLeave={scheduleClose}
            />
            {popup && !isPhone && (
              <div
                className="popup no-print"
                role="dialog"
                style={{ top: popup.top, left: popup.left, width: popup.width }}
                onMouseEnter={cancelClose}
                onMouseLeave={scheduleClose}
                onFocus={cancelClose}
                onBlur={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node)) scheduleClose()
                }}
              >
                <button className="popup-close" aria-label="Close" onClick={() => setPopup(null)}>
                  ×
                </button>
                {popup.findings.map((f) => (
                  <FindingDetail key={f.id} finding={f} number={numbers.get(f.id)} />
                ))}
              </div>
            )}
          </div>
        </Collapsible>
      </section>

      <section className="card no-print gaps-card">
        <Collapsible
          title="Gap table"
          count={`${result.gap_table.length} gap${result.gap_table.length === 1 ? '' : 's'}`}
          open={sections.gaps}
          onToggle={() => toggleSection('gaps')}
          actions={
            <ApplyButtons
              selectedCount={fixable.filter((id) => selected.has(id)).length}
              fixableCount={fixable.length}
              applying={applying}
              onApply={apply}
            />
          }
        >
          <p className="muted small no-print hitl-note">
            You decide what changes: tick the fixes you accept, edit any wording, then apply. Nothing is applied
            automatically.
          </p>
          <GapTable
            rows={result.gap_table}
            numbers={numbers}
            onRowClick={flashTo}
            review={{
              selected,
              edits,
              onToggle: toggle,
              onToggleAll: toggleAll,
              onEdit: editFix,
              applying,
            }}
          />
        </Collapsible>
        {applyError && <p className="error-text">{applyError}</p>}
      </section>

      {revision && (
        <RevisionPanel
          revision={revision}
          numbers={numbers}
          filename={policy.filename}
          open={sections.revision}
          onToggle={() => toggleSection('revision')}
          onBack={() => {
            setRevision(null)
            openSection('gaps')
            window.setTimeout(
              () => document.querySelector('.gaps-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
              80,
            )
          }}
        />
      )}

      {isPhone && <FindingDrawer findings={drawer?.findings ?? null} numbers={numbers} onClose={closeDrawer} />}

      <section className="print-only print-findings">
        <h2>Findings</h2>
        {ordered.map((f) => (
          <FindingDetail key={f.id} finding={f} number={numbers.get(f.id)} print />
        ))}
        <h2>Gap table</h2>
        <GapTable rows={result.gap_table} numbers={numbers} onRowClick={() => undefined} printMode />
        <h2>Sources</h2>
        <ul className="sources">
          {result.sources.map((s) => (
            <li key={s.doc_id}>
              {s.title}
              {s.issuer ? `, ${s.issuer}` : ''} ({s.jurisdiction}) — {s.url}
            </li>
          ))}
        </ul>
      </section>

      <section className="card sources-card no-print">
        <h2>Sources</h2>
        <ul className="sources">
          {result.sources.map((s) => (
            <li key={s.doc_id}>
              <a href={s.url} target="_blank" rel="noreferrer">
                {s.title}
              </a>
              {s.issuer ? ` · ${s.issuer}` : ''} <span className="chip-mini">{s.jurisdiction}</span>
            </li>
          ))}
        </ul>
        <p className="muted small">
          {stats.llm_calls} model calls · {(stats.tokens_in + stats.tokens_out).toLocaleString()} tokens ·{' '}
          {stats.duration_s.toFixed(1)} s{stats.reduced_mode ? ' · reduced mode' : ''}
        </p>
      </section>
    </div>
  )
}
