import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowUpRight, Check, ChevronRight, Clock3, FileText, Link2, ShieldCheck, X } from 'lucide-react'
import { api } from '../api/client'
import type { InvoiceDetail, Role, Session } from '../api/types'
import { date, dateTime, currentVersion, money, safeSourceUrl, statusText } from '../lib'
import { Badge, Empty, ErrorState, Field, Loading } from '../components/Shared'

type Tab = 'review' | 'evidence' | 'timeline'

function canAct(role: Role, required: string): boolean {
  return role === required
}

function ApprovalPanel({ invoice, session, requestedApprovalId }: { invoice: InvoiceDetail; session: Session; requestedApprovalId?: string }) {
  const queryClient = useQueryClient()
  const pending = (invoice.approvals || []).filter((approval) => approval.status === 'pending' || approval.status === 'awaiting_approval')
  const [selectedId, setSelectedId] = useState<string | null>(requestedApprovalId || null)
  const [note, setNote] = useState('')
  const [decision, setDecision] = useState<'approve' | 'reject'>('approve')
  const [feedback, setFeedback] = useState('')
  const selected = pending.find((approval) => approval.id === selectedId) || pending[0]
  const requiredRole = selected?.required_role || selected?.role || ''
  const version = currentVersion(invoice)
  const stale = selected && version !== undefined && String(selected.proposal_version) !== String(version)
  const allowed = !!selected && canAct(session.user.role, requiredRole) && !stale
  const mutation = useMutation({
    mutationFn: () => api.decideApproval(selected!.id, decision, selected!.proposal_version, note.trim()),
    onSuccess: async () => {
      setFeedback(decision === 'approve' ? 'Approval recorded against this exact version.' : 'Rejection recorded.')
      setNote('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['invoice', invoice.id] }),
        queryClient.invalidateQueries({ queryKey: ['invoices'] }),
        queryClient.invalidateQueries({ queryKey: ['approvals'] }),
        queryClient.invalidateQueries({ queryKey: ['exceptions'] }),
        queryClient.invalidateQueries({ queryKey: ['digest'] }),
      ])
    },
  })

  if (!pending.length) return <div className="approval-empty"><ShieldCheck size={20} aria-hidden="true" /><div><strong>{feedback || 'No pending decision'}</strong><span>Completed decisions appear in the timeline. New approvals are created only after validation.</span></div></div>

  return <div className="approval-panel">
    <div className="card-heading"><div><span className="eyebrow">CONTROLLED DECISION</span><h3>Approval request</h3></div><Badge value="pending" /></div>
    {pending.length > 1 && <div className="approval-choices" role="group" aria-label="Approval stage">
      {pending.map((item) => <button key={item.id} className={item.id === selected?.id ? 'choice active' : 'choice'} type="button" onClick={() => { setSelectedId(item.id); setFeedback(''); mutation.reset() }}>{statusText(item.required_role || item.role)}<ChevronRight size={14} /></button>)}
    </div>}
    {selected && <>
      <div className="approval-facts">
        <Field label="Exact amount" value={money(selected.amount ?? invoice.amount, selected.currency || invoice.currency)} />
        <Field label="Proposal version" value={`v${selected.proposal_version}`} mono />
        <Field label="Required role" value={statusText(requiredRole)} />
        <Field label="Expires" value={dateTime(selected.expires_at)} />
      </div>
      {stale && <p className="inline-warning"><AlertTriangle size={16} />The extraction changed after this proposal. A fresh approval is required.</p>}
      {!stale && !canAct(session.user.role, requiredRole) && <p className="inline-warning"><ShieldCheck size={16} />This stage requires a {statusText(requiredRole).toLowerCase()} account. Sign in with the correct role to decide.</p>}
      {allowed && <form onSubmit={(event) => { event.preventDefault(); setFeedback(''); mutation.mutate() }}>
        <fieldset className="decision-fieldset"><legend>Decision</legend>
          <label className={decision === 'approve' ? 'decision-option selected' : 'decision-option'}><input type="radio" name={`decision-${selected.id}`} value="approve" checked={decision === 'approve'} onChange={() => setDecision('approve')} /><Check size={16} aria-hidden="true" />Approve draft proposal</label>
          <label className={decision === 'reject' ? 'decision-option selected reject' : 'decision-option'}><input type="radio" name={`decision-${selected.id}`} value="reject" checked={decision === 'reject'} onChange={() => setDecision('reject')} /><X size={16} aria-hidden="true" />Reject</label>
        </fieldset>
        <label className="form-label" htmlFor="approval-note">Decision note {decision === 'reject' ? '(required)' : '(optional)'}</label>
        <textarea id="approval-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add context for the audit trail" rows={3} maxLength={1000} required={decision === 'reject'} />
        {mutation.isError && <p className="form-error" role="alert">{mutation.error.message}</p>}
        {feedback && <p className="form-success" role="status">{feedback}</p>}
        <button className={`button ${decision === 'reject' ? 'button-danger' : 'button-primary'}`} type="submit" disabled={mutation.isPending || (decision === 'reject' && !note.trim())}>{mutation.isPending ? 'Recording decision…' : decision === 'approve' ? 'Approve exact version' : 'Reject proposal'}</button>
      </form>}
    </>}
  </div>
}

function DocumentPane({ invoice, page }: { invoice: InvoiceDetail; page?: number }) {
  const sourceUrl = safeSourceUrl(invoice.source_url)
  const previewUrl = sourceUrl ? new URL(sourceUrl) : null
  previewUrl?.searchParams.set('preview_page', String(page || 1))
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  return <section className="document-pane" aria-label="Source document">
    <div className="document-toolbar"><div><FileText size={17} aria-hidden="true" /><strong>Source document</strong><span>Page {page || 1}</span></div>{sourceUrl && <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="text-link">Open source <ArrowUpRight size={15} aria-hidden="true" /></a>}</div>
    {previewUrl && failedUrl !== previewUrl.href ? <img key={previewUrl.href} alt={`Source invoice ${invoice.invoice_number}, page ${page || 1}`} src={previewUrl.href} className="document-frame" onError={() => setFailedUrl(previewUrl.href)} /> :
      <div className="document-unavailable"><FileText size={32} aria-hidden="true" /><strong>Preview unavailable</strong><span>The source link may have expired or the selected page is unavailable. Refresh the invoice or open the original attachment.</span></div>}
  </section>
}

function MatchPanel({ invoice }: { invoice: InvoiceDetail }) {
  const lines = invoice.line_items || invoice.lines || []
  const po = invoice.purchase_order
  const extracted = invoice.versions?.[0]?.extraction
  const poBySku = new Map(po?.lines?.filter((line) => line.sku).map((line) => [line.sku, line]) || [])
  const receivedBySku = new Map<string, number>()
  for (const receipt of invoice.receipts || []) {
    for (const line of receipt.lines || []) {
      if (line.sku) receivedBySku.set(line.sku, (receivedBySku.get(line.sku) || 0) + Number(line.received_quantity ?? line.quantity ?? 0))
    }
  }
  const poTotal = po?.total ?? po?.amount ?? (po?.lines?.length && po.lines.every((line) => Number.isFinite(Number(line.total ?? Number(line.quantity) * Number(line.unit_price))))
    ? po.lines.reduce((sum, line) => sum + Number(line.total ?? Number(line.quantity) * Number(line.unit_price)), 0)
    : undefined)
  return <div className="detail-stack">
    <div className="panel-card"><div className="card-heading"><div><span className="eyebrow">VALIDATED DATA</span><h3>Invoice details</h3></div><Badge value={invoice.status} /></div>
      <div className="field-grid"><Field label="Invoice number" value={invoice.invoice_number} mono /><Field label="Invoice date" value={date(invoice.invoice_date || extracted?.invoice_date)} /><Field label="Due date" value={date(invoice.due_date || extracted?.due_date)} /><Field label="Received" value={date(invoice.received_at)} /><Field label="Subtotal" value={money(invoice.subtotal ?? extracted?.subtotal, invoice.currency)} /><Field label="Tax" value={money(invoice.tax_amount ?? extracted?.tax, invoice.currency)} /></div>
      <div className="total-row"><span>Invoice total</span><strong>{money(invoice.amount, invoice.currency)}</strong></div>
    </div>
    <div className="panel-card"><div className="card-heading"><div><span className="eyebrow">THREE-WAY MATCH</span><h3>Purchase order & receipt</h3></div>{po ? <Badge value="connected">PO found</Badge> : <Badge value="needs_review">No PO</Badge>}</div>
      {po ? <><div className="field-grid"><Field label="PO number" value={po.number || po.po_number || invoice.po_number} mono /><Field label="PO total" value={money(poTotal, po.currency || invoice.currency)} /><Field label="PO currency" value={po.currency || '—'} /><Field label="Receipts" value={String(invoice.receipts?.length || 0)} /></div>
        <div className="comparison-wrap"><table className="comparison-table"><caption>Invoice lines compared with matching PO and receipt lines</caption><thead><tr><th>Line</th><th>Invoice qty</th><th>PO qty</th><th>Received qty</th><th>Invoice price</th><th>PO price</th></tr></thead><tbody>{lines.length ? lines.map((line, index) => {
          const poLine = line.sku ? poBySku.get(line.sku) : undefined
          return <tr key={line.id || `${line.sku || 'line'}-${index}`}><td>{line.description}{line.sku && <small className="mono line-sku">{line.sku}</small>}</td><td>{line.quantity}</td><td>{poLine?.quantity ?? '—'}</td><td>{line.sku ? receivedBySku.get(line.sku) ?? '—' : '—'}</td><td>{money(line.unit_price, invoice.currency)}</td><td>{money(poLine?.unit_price, po.currency || invoice.currency)}</td></tr>
        }) : <tr><td colSpan={6}>No extracted lines available yet.</td></tr>}</tbody></table></div>
      </> : <p className="muted-copy">No matching purchase order is attached to this invoice. Review the findings before a decision.</p>}
    </div>
    {(invoice.findings?.length || 0) > 0 && <div className="panel-card"><div className="card-heading"><div><span className="eyebrow">EXCEPTIONS</span><h3>Validation findings</h3></div><span className="count-chip">{invoice.findings?.length}</span></div><div className="finding-list">{invoice.findings?.map((finding) => <div className="finding" key={finding.id}><AlertTriangle size={18} aria-hidden="true" /><div><strong>{finding.summary || statusText(finding.code || finding.kind || 'Finding')}</strong><span>{finding.message || statusText(finding.code || finding.kind || 'Validation finding')}</span></div><Badge value={finding.resolved ? 'resolved' : finding.blocking ? 'blocking' : finding.status || finding.severity || 'warning'} /></div>)}</div></div>}
  </div>
}

function EvidencePanel({ invoice, onPage }: { invoice: InvoiceDetail; onPage: (page: number) => void }) {
  const evidence = invoice.versions?.flatMap((version) => version.evidence || []) || []
  const findingEvidence = invoice.findings?.flatMap((finding) => finding.evidence || []) || []
  const items = [...evidence, ...findingEvidence]
  return <section className="panel-card"><div className="card-heading"><div><span className="eyebrow">SOURCE TRACE</span><h3>Evidence & versions</h3></div><span className="count-chip">{items.length} references</span></div>
    {invoice.versions?.length ? <div className="version-strip">{invoice.versions.map((version, index) => <div className="version-item" key={version.id || index}><span>v{version.extraction_version ?? version.version}</span><strong>{statusText(version.status || (index === 0 ? 'current' : 'superseded'))}</strong><small>{dateTime(version.created_at)}</small></div>)}</div> : <p className="muted-copy">Version history has not been recorded yet.</p>}
    {items.length ? <div className="evidence-list">{items.map((item, index) => <div className="evidence-item" key={`${item.page}-${item.field}-${index}`}><div><span className="eyebrow">PAGE {item.page}</span><strong>{item.label || (item.field ? statusText(item.field) : 'Source evidence')}</strong><p>{item.quote || item.snippet || 'Open the source page to inspect the document.'}</p></div><button type="button" className="button button-secondary button-small" onClick={() => onPage(item.page)}><Link2 size={15} aria-hidden="true" />View page</button></div>)}</div> : <Empty title="No page references yet" description="Source-page evidence will appear after extraction completes." />}
  </section>
}

function TimelinePanel({ invoice }: { invoice: InvoiceDetail }) {
  const events = invoice.timeline || []
  return <section className="panel-card"><div className="card-heading"><div><span className="eyebrow">AUDIT TRAIL</span><h3>Posting timeline</h3></div><span className="count-chip">{events.length} events</span></div>
    {(invoice.posting_operation || invoice.accounting_id) && <div className="posting-reference"><span>Accounting record</span>{invoice.posting_operation && <><strong className="mono">{invoice.posting_operation.id}</strong><Badge value={invoice.posting_operation.status} /></>}{(invoice.accounting_id || invoice.posting_operation?.accounting_id) && <span className="mono">Draft ID: {invoice.accounting_id || invoice.posting_operation?.accounting_id}</span>}</div>}
    {events.length ? <ol className="timeline">{events.map((event, index) => <li key={event.id || index}><span className="timeline-marker"><Clock3 size={14} aria-hidden="true" /></span><div><div className="timeline-title"><strong>{event.title || statusText(event.event || event.type || 'Event')}</strong>{event.status && <Badge value={event.status} />}</div><p>{event.detail || (event.actor ? `By ${event.actor}` : 'Recorded by workflow')}</p><time>{dateTime(event.at || event.created_at)}</time></div></li>)}</ol> : <Empty title="No recorded events" description="The workflow timeline will populate as actual steps complete." />}
  </section>
}

export default function InvoiceDrawer({ id, onClose, session, approvalId, initialTab = 'review' }: { id: string; onClose: () => void; session: Session; approvalId?: string; initialTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab)
  const [page, setPage] = useState<number>()
  const closeRef = useRef<HTMLButtonElement>(null)
  const drawerRef = useRef<HTMLElement>(null)
  const onCloseRef = useRef(onClose)
  const query = useQuery({ queryKey: ['invoice', id], queryFn: () => api.invoice(id), refetchInterval: (current) => ['received', 'extracting', 'validating', 'approved', 'posting', 'uncertain'].includes(current.state.data?.status || '') ? 20_000 : false })

  useEffect(() => { onCloseRef.current = onClose }, [onClose])

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current()
      if (event.key !== 'Tab') return
      const focusable = [...(drawerRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), iframe') || [])]
      const first = focusable[0]
      const last = focusable.at(-1)
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => { document.body.style.overflow = previousOverflow; window.removeEventListener('keydown', onKey) }
  }, [])

  const invoice = query.data
  return <div className="drawer-layer"><div className="drawer-backdrop" onClick={onClose} aria-hidden="true" /><aside ref={drawerRef} className="invoice-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
    <header className="drawer-header"><div className="drawer-kicker"><span className="eyebrow">INVOICE REVIEW</span><span className="header-divider">/</span><span className="mono">{invoice?.invoice_number || id}</span></div><button ref={closeRef} className="icon-button close-button" type="button" aria-label="Close invoice details" onClick={onClose}><X size={20} aria-hidden="true" /></button>
      <div className="drawer-title-row"><div><h2 id="drawer-title">{invoice?.vendor_name || 'Loading invoice'}</h2><p>Review source evidence, purchase order, decisions and posting events.</p></div>{invoice && <Badge value={invoice.status} />}</div>
      <nav className="tab-nav" aria-label="Invoice detail sections">{([['review', 'Review & match'], ['evidence', 'Evidence'], ['timeline', 'Timeline']] as const).map(([value, label]) => <button key={value} type="button" role="tab" aria-selected={tab === value} className={tab === value ? 'tab active' : 'tab'} onClick={() => setTab(value)}>{label}</button>)}</nav>
    </header>
    <div className="drawer-content">{query.isPending ? <Loading label="Loading invoice details…" /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : invoice ? <div className="drawer-layout">
      <DocumentPane invoice={invoice} page={page} />
      <div className="drawer-details">{tab === 'review' && <><MatchPanel invoice={invoice} /><ApprovalPanel invoice={invoice} session={session} requestedApprovalId={approvalId} /></>}{tab === 'evidence' && <EvidencePanel invoice={invoice} onPage={(newPage) => { setPage(newPage); document.querySelector('.document-pane')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }} />}{tab === 'timeline' && <TimelinePanel invoice={invoice} />}</div>
    </div> : null}</div>
  </aside></div>
}
