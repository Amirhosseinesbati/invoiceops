import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, FileCheck2, FileSearch, Filter, History, RefreshCw, Search, ShieldCheck, SlidersHorizontal, UploadCloud, WalletCards, X } from 'lucide-react'
import { api } from '../api/client'
import type { ExceptionItem, InvoiceSummary, Role, Vendor } from '../api/types'
import { date, dateTime, isOpen, money, statusText } from '../lib'
import { Badge, Empty, ErrorState, Field, Loading, SectionHeading } from '../components/Shared'

export type OpenInvoice = (id: string, approvalId?: string, tab?: 'review' | 'evidence' | 'timeline') => void

const queueFilters = [
  { id: 'all', label: 'All invoices' },
  { id: 'action', label: 'Needs action' },
  { id: 'processing', label: 'Processing' },
  { id: 'done', label: 'Completed' },
] as const

const EMPTY_INVOICES: InvoiceSummary[] = []

function filterInvoice(invoice: InvoiceSummary, filter: string): boolean {
  if (filter === 'action') return ['needs_review', 'awaiting_approval', 'failed', 'uncertain'].includes(invoice.status)
  if (filter === 'processing') return ['received', 'extracting', 'validating', 'approved', 'posting'].includes(invoice.status)
  if (filter === 'done') return ['draft_created', 'completed', 'rejected'].includes(invoice.status)
  return true
}

export function QueueView({ openInvoice, role }: { openInvoice: OpenInvoice; role: Role }) {
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [showReplay, setShowReplay] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const query = useQuery({ queryKey: ['invoices'], queryFn: api.invoices, refetchInterval: 20_000 })
  const replay = useMutation({ mutationFn: (document: File) => api.replay(document), onSuccess: () => { query.refetch() } })
  const invoices = query.data?.items || EMPTY_INVOICES
  const filtered = useMemo(() => invoices.filter((invoice) => filterInvoice(invoice, filter) && `${invoice.vendor_name} ${invoice.invoice_number} ${invoice.po_number || ''}`.toLowerCase().includes(search.toLowerCase())).sort((a, b) => b.age_days - a.age_days), [invoices, filter, search])
  const actionCount = invoices.filter((invoice) => filterInvoice(invoice, 'action')).length
  const completedCount = invoices.filter((invoice) => filterInvoice(invoice, 'done')).length
  const agingCount = invoices.filter((invoice) => isOpen(invoice) && invoice.age_days >= 7).length

  return <div className="view"><SectionHeading eyebrow="OPERATIONS / INVOICE QUEUE" title="Finance inbox" description="A clear view of every invoice from intake to draft bill." action={<><button className="button button-secondary" type="button" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw size={16} className={query.isFetching ? 'spin' : ''} aria-hidden="true" />Refresh</button><button className="button button-primary" type="button" onClick={() => { setShowReplay(!showReplay); replay.reset() }} disabled={role === 'viewer'} title={role === 'viewer' ? 'Operator access required for intake' : undefined} aria-label={role === 'viewer' ? 'Replay unavailable: operator access required' : 'Replay invoice'}><UploadCloud size={16} aria-hidden="true" />Replay invoice</button></>} />
    {showReplay && <section className="replay-panel" aria-label="Replay a local invoice"><div className="replay-panel-head"><div><span className="eyebrow">LOCAL INTAKE</span><h2>Submit an invoice to the workflow</h2><p>PDF, PNG or JPEG · maximum 8 MB. The response confirms submission; processing continues asynchronously in n8n.</p></div><button type="button" className="icon-button" onClick={() => setShowReplay(false)} aria-label="Close replay form"><X size={17} /></button></div><form onSubmit={(event) => { event.preventDefault(); if (file) replay.mutate(file) }}><label className="form-label" htmlFor="replay-file">Source document</label><input id="replay-file" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" required onChange={(event) => { setFile(event.target.files?.[0] || null); replay.reset() }} /><button type="submit" className="button button-primary" disabled={!file || replay.isPending || (file?.size || 0) > 8_000_000}>{replay.isPending ? 'Submitting…' : 'Submit to intake'}</button></form>{file && file.size > 8_000_000 && <p className="form-error" role="alert">The selected file exceeds 8 MB.</p>}{replay.isError && <p className="form-error" role="alert">{replay.error.message}</p>}{replay.isSuccess && <p className="form-success" role="status">Submitted event <span className="mono">{replay.data.event_id}</span>. Refresh the queue to follow processing.</p>}</section>}
    {query.isPending ? <Loading /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <>
      <div className="overview-grid">
        <div className="overview-card"><div className="overview-icon navy"><WalletCards size={21} aria-hidden="true" /></div><span>Invoices in workspace</span><strong>{invoices.length}</strong><small>Current records</small></div>
        <div className="overview-card"><div className="overview-icon amber"><AlertTriangle size={21} aria-hidden="true" /></div><span>Needs action</span><strong>{actionCount}</strong><small>Review, approval or recovery</small></div>
        <div className="overview-card"><div className="overview-icon slate"><Clock3 size={21} aria-hidden="true" /></div><span>Aging 7+ days</span><strong>{agingCount}</strong><small>Open invoices only</small></div>
        <div className="overview-card"><div className="overview-icon green"><FileCheck2 size={21} aria-hidden="true" /></div><span>Closed decisions</span><strong>{completedCount}</strong><small>Drafts and rejections</small></div>
      </div>
      <section className="surface-table"><div className="table-toolbar"><div><span className="eyebrow">WORKSPACE INBOX</span><h2>Invoice queue <span>{filtered.length}</span></h2></div><div className="table-tools"><label className="search-box"><Search size={17} aria-hidden="true" /><span className="sr-only">Search invoices</span><input type="search" value={search} placeholder="Search vendor, invoice or PO" onChange={(event) => setSearch(event.target.value)} /></label><div className="filter-icon" title="Filter by workflow status"><SlidersHorizontal size={17} aria-hidden="true" /></div></div></div>
        <div className="filter-tabs" role="group" aria-label="Filter invoices">{queueFilters.map((option) => <button className={filter === option.id ? 'filter-tab active' : 'filter-tab'} type="button" key={option.id} onClick={() => setFilter(option.id)}>{option.label}{option.id === 'action' && actionCount > 0 && <span>{actionCount}</span>}</button>)}</div>
        {filtered.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Invoice</th><th>Vendor</th><th>Amount</th><th>PO match</th><th>Status</th><th>Age</th><th><span className="sr-only">Open</span></th></tr></thead><tbody>{filtered.map((invoice) => <tr key={invoice.id}><td data-label="Invoice"><button type="button" className="table-main-link mono" onClick={() => openInvoice(invoice.id)}>{invoice.invoice_number}</button><small>Received {date(invoice.received_at)}</small></td><td data-label="Vendor"><strong>{invoice.vendor_name}</strong><small>{invoice.findings_count > 0 ? `${invoice.findings_count} finding${invoice.findings_count === 1 ? '' : 's'}` : 'No findings'}</small></td><td data-label="Amount" className="amount-cell">{money(invoice.amount, invoice.currency)}</td><td data-label="PO match" className="mono muted-value">{invoice.po_number || 'Unmatched'}</td><td data-label="Status"><Badge value={invoice.status} /></td><td data-label="Age"><span className={invoice.age_days >= 7 && isOpen(invoice) ? 'age-warn' : 'age-value'}>{invoice.age_days}d</span></td><td><button type="button" className="row-arrow" aria-label={`Open ${invoice.invoice_number}`} onClick={() => openInvoice(invoice.id)}><ArrowRight size={17} aria-hidden="true" /></button></td></tr>)}</tbody></table></div> : <Empty title={search || filter !== 'all' ? 'No invoices match this view' : 'No invoices received yet'} description={search || filter !== 'all' ? 'Try a different search or status filter.' : 'Replay a demo intake event or connect a source to populate the inbox.'} />}
      </section>
    </>}
  </div>
}

export function ApprovalsView({ openInvoice }: { openInvoice: OpenInvoice }) {
  const query = useQuery({ queryKey: ['approvals'], queryFn: api.approvals, refetchInterval: 20_000 })
  const items = query.data?.items || []
  const pending = items.filter((item) => ['pending', 'awaiting_approval'].includes(item.status))
  const completed = items.filter((item) => !['pending', 'awaiting_approval'].includes(item.status))
  return <div className="view"><SectionHeading eyebrow="OPERATIONS / APPROVALS" title="Approval inbox" description="Decisions are bound to the exact proposal version and amount." action={<button className="button button-secondary" type="button" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw size={16} className={query.isFetching ? 'spin' : ''} aria-hidden="true" />Refresh</button>} />
    {query.isPending ? <Loading /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <><div className="notice-strip"><ShieldCheck size={19} aria-hidden="true" /><div><strong>Version-controlled approval</strong><span>If extraction or validation changes, the prior request cannot approve a new draft.</span></div><span className="notice-count">{pending.length} pending</span></div>
      <div className="subsection-title"><h2>Pending decisions</h2><span>{pending.length} requests</span></div>
      {pending.length ? <div className="approval-grid">{pending.map((item) => <article className="approval-card" key={item.id}><div className="approval-card-top"><div className="approval-mark"><ShieldCheck size={20} aria-hidden="true" /></div><Badge value={item.status} /></div><span className="eyebrow">{statusText(item.role)} REVIEW</span><h3>{item.vendor_name || 'Invoice'}</h3><p className="mono">{item.invoice_number || item.invoice_id}</p><div className="approval-amount">{money(item.amount, item.currency)}</div><div className="approval-card-meta"><Field label="Proposal" value={`v${item.proposal_version}`} mono /><Field label="Expires" value={date(item.expires_at)} /></div><button type="button" className="button button-primary full-width" onClick={() => openInvoice(item.invoice_id, item.id)}>Review exact version <ArrowRight size={16} aria-hidden="true" /></button></article>)}</div> : <Empty title="No approvals waiting" description="Validated invoices appear here when the approval policy creates a request." />}
      {completed.length > 0 && <><div className="subsection-title"><h2>Recent decisions</h2><span>{completed.length} recorded</span></div><div className="list-surface">{completed.slice(0, 20).map((item) => <div className="list-row" key={item.id}><div className="list-icon"><CheckCircle2 size={19} aria-hidden="true" /></div><div className="list-row-main"><strong>{item.vendor_name || item.invoice_number || item.invoice_id}</strong><span>v{item.proposal_version} · {statusText(item.role)} · {money(item.amount, item.currency)}</span></div><Badge value={item.status} /><button type="button" className="row-arrow" aria-label={`Review ${item.invoice_number || item.invoice_id}`} onClick={() => openInvoice(item.invoice_id, item.id, 'timeline')}><ArrowRight size={17} /></button></div>)}</div></>}
    </>}
  </div>
}

export function ExceptionsView({ openInvoice, role }: { openInvoice: OpenInvoice; role: Role }) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['exceptions'], queryFn: api.exceptions, refetchInterval: 20_000 })
  const items = query.data?.items || []
  const open = items.filter((item) => item.status === 'open')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [resolution, setResolution] = useState<'accept' | 'reject' | 'request_revision'>('accept')
  const [note, setNote] = useState('')
  const [feedback, setFeedback] = useState('')
  const selected = open.find((item) => item.id === selectedId) || open[0]
  const acceptRestricted = !!selected && ['DUPLICATE_IDENTITY', 'CORRUPTED_DOCUMENT', 'UNSUPPORTED_CURRENCY', 'UNCERTAIN_VENDOR', 'EXTRACTION_REVIEW'].includes(selected.kind)
  const mutation = useMutation({
    mutationFn: ({ item, choice, text }: { item: ExceptionItem; choice: 'accept' | 'reject' | 'request_revision'; text: string }) => api.resolveException(item.id, choice, text),
    onSuccess: async () => {
      setFeedback('Resolution recorded. The workflow will use the updated business state.')
      setNote('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['exceptions'] }),
        queryClient.invalidateQueries({ queryKey: ['invoices'] }),
        queryClient.invalidateQueries({ queryKey: ['approvals'] }),
      ])
    },
  })
  return <div className="view"><SectionHeading eyebrow="OPERATIONS / EXCEPTIONS" title="Exception resolution" description="Investigate blocking findings before an invoice can move to approval." action={<button className="button button-secondary" type="button" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw size={16} className={query.isFetching ? 'spin' : ''} aria-hidden="true" />Refresh</button>} />
    {query.isPending ? <Loading /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <><div className="exception-summary"><div className="exception-summary-icon"><AlertTriangle size={22} aria-hidden="true" /></div><div><strong>{open.length} open exceptions</strong><span>Resolve mismatches with an explicit note. Accepted items return to validation and approval routing.</span></div></div>
      {open.length ? <div className="split-workspace"><div className="exception-list" aria-label="Open exceptions">{open.map((item) => <button type="button" key={item.id} onClick={() => { setSelectedId(item.id); setFeedback(''); mutation.reset() }} className={selected?.id === item.id ? 'exception-list-item selected' : 'exception-list-item'}><span className="eyebrow">{statusText(item.kind)}</span><strong>{item.summary}</strong><small>Invoice {item.invoice_id} · {date(item.created_at)}</small><Badge value={item.status} /></button>)}</div>
        {selected && <section className="exception-detail" aria-labelledby="exception-detail-title"><div className="card-heading"><div><span className="eyebrow">CASE / {selected.id}</span><h2 id="exception-detail-title">{selected.summary}</h2></div><Badge value={selected.status} /></div><div className="exception-detail-fields"><Field label="Exception type" value={statusText(selected.kind)} /><Field label="Raised" value={dateTime(selected.created_at)} /><Field label="Invoice" value={selected.invoice_id} mono /></div>{selected.details && <div className="exception-description"><strong>Validation detail</strong><p>{typeof selected.details === 'string' ? selected.details : JSON.stringify(selected.details, null, 2)}</p></div>}
          <button type="button" className="text-link" onClick={() => openInvoice(selected.invoice_id, undefined, 'evidence')}>Inspect invoice evidence <ArrowRight size={15} aria-hidden="true" /></button>
          {role === 'viewer' ? <p className="inline-warning"><ShieldCheck size={16} aria-hidden="true" />Viewer access cannot resolve exceptions. Sign in as an operator or manager.</p> : <form className="resolution-form" onSubmit={(event) => { event.preventDefault(); if (selected && note.trim().length >= 8 && !(acceptRestricted && resolution === 'accept')) { setFeedback(''); mutation.mutate({ item: selected, choice: resolution, text: note.trim() }) } }}>
            <h3>Record a resolution</h3><p>Each decision is saved to the audit trail. The server rechecks current state.</p>
            <label htmlFor="resolution-choice" className="form-label">Action</label>
            <select id="resolution-choice" value={resolution} onChange={(event) => setResolution(event.target.value as typeof resolution)}><option value="accept" disabled={acceptRestricted}>Accept after review</option><option value="request_revision">Request revised invoice</option><option value="reject">Reject invoice</option></select>
            {acceptRestricted && <p className="inline-warning"><AlertTriangle size={16} aria-hidden="true" />This exception requires a corrected document or vendor mapping before acceptance.</p>}
            <label htmlFor="resolution-note" className="form-label">Reason and evidence (at least 8 characters)</label>
            <textarea id="resolution-note" rows={4} maxLength={1000} minLength={8} required value={note} onChange={(event) => setNote(event.target.value)} placeholder="What did you verify, and why is this resolution appropriate?" />
            {mutation.isError && <p className="form-error" role="alert">{mutation.error.message}</p>}{feedback && <p className="form-success" role="status">{feedback}</p>}
            <button type="submit" className="button button-primary" disabled={mutation.isPending || note.trim().length < 8 || (acceptRestricted && resolution === 'accept')}>{mutation.isPending ? 'Saving resolution…' : 'Save resolution'}</button>
          </form>}
        </section>}</div> : <Empty title="No open exceptions" description="Document, identity and PO mismatch findings will appear here when raised." />}
    </>}
  </div>
}

export function PostingsView({ openInvoice }: { openInvoice: OpenInvoice }) {
  const query = useQuery({ queryKey: ['invoices'], queryFn: api.invoices, refetchInterval: 20_000 })
  const invoices = query.data?.items || []
  const relevant = invoices.filter((invoice) => ['approved', 'posting', 'draft_created', 'uncertain', 'failed'].includes(invoice.status)).sort((a, b) => b.received_at.localeCompare(a.received_at))
  const drafts = relevant.filter((invoice) => invoice.status === 'draft_created').length
  const unresolved = relevant.filter((invoice) => ['uncertain', 'failed'].includes(invoice.status)).length
  return <div className="view"><SectionHeading eyebrow="OPERATIONS / POSTING" title="Posting timeline" description="Follow approved invoices through draft creation and reconciliation." action={<button className="button button-secondary" type="button" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw size={16} className={query.isFetching ? 'spin' : ''} aria-hidden="true" />Refresh</button>} />
    {query.isPending ? <Loading /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <><div className="posting-stats"><div><span>Drafts created</span><strong>{drafts}</strong></div><div><span>Requires reconciliation</span><strong>{unresolved}</strong></div><div><span>Posting pipeline</span><strong>{relevant.length}</strong></div></div><div className="list-surface posting-list">{relevant.length ? relevant.map((invoice) => <div className="list-row" key={invoice.id}><div className={`list-icon ${invoice.status === 'draft_created' ? 'success' : invoice.status === 'uncertain' || invoice.status === 'failed' ? 'warning' : ''}`}><History size={19} aria-hidden="true" /></div><div className="list-row-main"><strong>{invoice.vendor_name} <span className="mono muted-value">· {invoice.invoice_number}</span></strong><span>{money(invoice.amount, invoice.currency)} · Received {date(invoice.received_at)}</span></div><Badge value={invoice.status} /><button className="row-arrow" type="button" aria-label={`Open posting timeline for ${invoice.invoice_number}`} onClick={() => openInvoice(invoice.id, undefined, 'timeline')}><ArrowRight size={17} /></button></div>) : <Empty title="No posting activity yet" description="Approved invoices and accounting outcomes will appear here as workflow events occur." />}</div></>}
  </div>
}

export function VendorsView({ openInvoice }: { openInvoice: OpenInvoice }) {
  const query = useQuery({ queryKey: ['vendors'], queryFn: api.vendors, refetchInterval: 30_000 })
  const vendors = query.data?.items || []
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = vendors.find((vendor) => vendor.id === selectedId) || vendors[0]
  const history = useQuery({ queryKey: ['vendor-history', selected?.id], queryFn: () => api.vendorHistory(selected!.id), enabled: !!selected?.id })
  return <div className="view"><SectionHeading eyebrow="REFERENCE / SUPPLIERS" title="Vendor history" description="Track invoice patterns and prior outcomes by supplier." action={<button className="button button-secondary" type="button" onClick={() => { query.refetch(); history.refetch() }} disabled={query.isFetching}><RefreshCw size={16} className={query.isFetching ? 'spin' : ''} aria-hidden="true" />Refresh</button>} />
    {query.isPending ? <Loading /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : vendors.length ? <div className="split-workspace vendors-workspace"><div className="vendor-list" aria-label="Vendors">{vendors.map((vendor: Vendor) => <button key={vendor.id} className={selected?.id === vendor.id ? 'vendor-list-item selected' : 'vendor-list-item'} type="button" onClick={() => setSelectedId(vendor.id)}><span className="vendor-avatar">{vendor.name.slice(0, 2).toUpperCase()}</span><span><strong>{vendor.name}</strong><small>{vendor.invoice_count ?? '—'} invoices · {vendor.open_count ?? '—'} open</small></span><ArrowRight size={16} aria-hidden="true" /></button>)}</div><section className="vendor-detail"><div className="card-heading"><div><span className="eyebrow">SUPPLIER HISTORY</span><h2>{selected?.name}</h2></div><span className="count-chip">{history.data?.invoices.length ?? '—'} invoices</span></div>{history.isPending ? <Loading label="Loading vendor history…" /> : history.isError ? <ErrorState error={history.error} onRetry={() => history.refetch()} compact /> : history.data?.invoices.length ? <div className="vendor-history-list">{history.data.invoices.map((invoice) => <div className="vendor-history-row" key={invoice.id}><div><button type="button" className="table-main-link mono" onClick={() => openInvoice(invoice.id)}>{invoice.invoice_number}</button><span>{date(invoice.received_at)} · {invoice.po_number || 'No PO'}</span></div><strong>{money(invoice.amount, invoice.currency)}</strong><Badge value={invoice.status} /></div>)}</div> : <Empty title="No invoice history" description="This vendor has no invoices in the current workspace." />}</section></div> : <Empty title="No vendors available" description="Vendor records appear here after the demo seed or connected intake is configured." />}
  </div>
}

export function ConnectorsView() {
  const query = useQuery({ queryKey: ['connectors'], queryFn: api.connectors, refetchInterval: 30_000 })
  const digest = useQuery({ queryKey: ['digest'], queryFn: api.digest, retry: false, refetchInterval: 30_000 })
  const connectors = query.data?.items || []
  return <div className="view"><SectionHeading eyebrow="SYSTEM / INTEGRATIONS" title="Connector health" description="Live status from the services that move invoices through the workflow." action={<button className="button button-secondary" type="button" onClick={() => { query.refetch(); digest.refetch() }} disabled={query.isFetching}><RefreshCw size={16} className={query.isFetching ? 'spin' : ''} aria-hidden="true" />Check now</button>} />
    {query.isPending ? <Loading label="Checking connectors…" /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : <><div className="connector-grid">{connectors.length ? connectors.map((connector) => <article className="connector-card" key={connector.name}><div className="connector-top"><span className="connector-icon"><FileSearch size={20} aria-hidden="true" /></span><Badge value={connector.status} /></div><h2>{connector.name}</h2><div className="connector-mode">{statusText(connector.mode)} adapter</div><p>{connector.message || 'No additional provider detail returned.'}</p><div className="connector-footer">Last checked <strong>{dateTime(connector.last_checked_at)}</strong></div></article>) : <Empty title="No connectors registered" description="Configure the local simulators or live adapters to see health information." />}</div>
      <section className="digest-panel"><div className="card-heading"><div><span className="eyebrow">WORKFLOW STATUS</span><h2>Latest digest</h2></div><Filter size={19} aria-hidden="true" /></div>{digest.isPending ? <p className="muted-copy">Loading stored digest…</p> : digest.isError ? <div className="digest-error"><span>{digest.error.message}</span><button type="button" className="text-link" onClick={() => digest.refetch()}>Retry <RefreshCw size={14} /></button></div> : digest.data ? <><p className="muted-copy">{digest.data.created_at ? `Generated ${dateTime(digest.data.created_at)} from stored invoice status.` : 'No digest run is available yet.'}</p>{Object.keys(digest.data.counts || {}).length > 0 && <div className="digest-counts">{Object.entries(digest.data.counts || {}).map(([label, value]) => <div key={label}><span>{statusText(label)}</span><strong>{value}</strong></div>)}</div>}</> : <p className="muted-copy">No digest run is available yet.</p>}</section>
    </>}
  </div>
}
