import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Archive, ArrowRight, CircleHelp, FileCheck2, LayoutGrid, LogOut, PanelLeftClose, ShieldCheck, TriangleAlert, Truck, Wifi, WifiOff } from 'lucide-react'
import { api, ApiError } from './api/client'
import type { Session } from './api/types'
import { ApprovalsView, ConnectorsView, ExceptionsView, PostingsView, QueueView, VendorsView } from './features/Views'
import type { OpenInvoice } from './features/Views'
import InvoiceDrawer from './features/InvoiceDrawer'
import { ErrorState, Loading } from './components/Shared'

type View = 'queue' | 'approvals' | 'exceptions' | 'postings' | 'vendors' | 'connectors'
type Location = { view: View; invoiceId: string | null; approvalId?: string; tab?: 'review' | 'evidence' | 'timeline' }

const navigation = [
  { id: 'queue', label: 'Invoice queue', icon: LayoutGrid },
  { id: 'approvals', label: 'Approvals', icon: ShieldCheck },
  { id: 'exceptions', label: 'Exceptions', icon: TriangleAlert },
  { id: 'postings', label: 'Posting timeline', icon: Activity },
  { id: 'vendors', label: 'Vendor history', icon: Truck },
  { id: 'connectors', label: 'Connector health', icon: Wifi },
] as const

function readLocation(): Location {
  const params = new URLSearchParams(window.location.search)
  const requested = params.get('view')
  const view = navigation.some((item) => item.id === requested) ? requested as View : 'queue'
  const tab = params.get('tab')
  return {
    view,
    invoiceId: params.get('invoice'),
    approvalId: params.get('approval') || undefined,
    tab: tab === 'evidence' || tab === 'timeline' ? tab : 'review',
  }
}

function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const demoHint = import.meta.env.VITE_DEMO_ACCESS_HINT === 'true'
  const [username, setUsername] = useState(demoHint ? 'operator@example.com' : '')
  const [password, setPassword] = useState(demoHint ? 'demo-operator' : '')
  const mutation = useMutation({ mutationFn: () => api.login(username.trim(), password), onSuccess: onLogin })
  return <main className="login-page"><div className="login-brand-panel"><div className="brand large"><span className="brand-mark"><FileCheck2 size={24} aria-hidden="true" /></span><span>Invoice<span>Ops</span></span></div><div className="login-story"><span className="eyebrow">ACCOUNTS PAYABLE, UNDER CONTROL</span><h1>Every invoice has a clear next step.</h1><p>From intake and PO matching to versioned approval and draft posting, keep the entire path visible.</p><div className="story-path"><div><span>01</span><strong>Receive</strong><small>Authenticated intake</small></div><div><span>02</span><strong>Review</strong><small>Evidence & policy</small></div><div><span>03</span><strong>Post</strong><small>Draft + reconciliation</small></div></div></div><div className="login-panel-foot">InvoiceOps / Independent portfolio project</div></div>
    <div className="login-form-side"><div className="login-form-wrap"><div className="login-mobile-logo brand"><span className="brand-mark"><FileCheck2 size={20} /></span><span>Invoice<span>Ops</span></span></div><div className="login-eyebrow">SECURE WORKSPACE ACCESS</div><h2>Welcome back</h2><p>Sign in to your finance operations workspace.</p><form onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><label htmlFor="login-username">Email</label><input id="login-username" type="email" autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} /><label htmlFor="login-password">Password</label><input id="login-password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />{mutation.isError && <p className="form-error" role="alert">{mutation.error.message}</p>}<button type="submit" className="button button-primary full-width login-submit" disabled={mutation.isPending}>{mutation.isPending ? 'Signing in…' : <>Sign in <ArrowRight size={18} aria-hidden="true" /></>}</button></form>{demoHint && <div className="demo-login-note"><div className="demo-note-icon"><CircleHelp size={19} aria-hidden="true" /></div><div><strong>Local demo access</strong><span>Use the prefilled operator account. Manager: manager@example.com / demo-manager. Viewer: viewer@example.com / demo-viewer.</span></div></div>}</div></div>
  </main>
}

function Workspace({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const [location, setLocation] = useState(readLocation)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const approvals = useQuery({ queryKey: ['approvals'], queryFn: api.approvals, refetchInterval: 20_000 })
  const exceptions = useQuery({ queryKey: ['exceptions'], queryFn: api.exceptions, refetchInterval: 20_000 })
  const connectors = useQuery({ queryKey: ['connectors'], queryFn: api.connectors, refetchInterval: 30_000 })
  const pendingApprovals = approvals.data?.items.filter((item) => ['pending', 'awaiting_approval'].includes(item.status)).length
  const openExceptions = exceptions.data?.items.filter((item) => item.status === 'open').length
  const connectorBad = connectors.data?.items.filter((item) => !['healthy', 'connected', 'active', 'simulated'].includes(item.status)).length
  const statusLabel = connectors.isError ? 'API disconnected' : connectors.isPending ? 'Checking services' : connectorBad ? `${connectorBad} service${connectorBad === 1 ? '' : 's'} need attention` : 'Services connected'

  useEffect(() => {
    const pop = () => setLocation(readLocation())
    window.addEventListener('popstate', pop)
    return () => window.removeEventListener('popstate', pop)
  }, [])

  function navigate(view: View, invoiceId: string | null = null, approvalId?: string, tab?: 'review' | 'evidence' | 'timeline') {
    const params = new URLSearchParams()
    if (view !== 'queue') params.set('view', view)
    if (invoiceId) params.set('invoice', invoiceId)
    if (approvalId) params.set('approval', approvalId)
    if (tab && tab !== 'review') params.set('tab', tab)
    const next = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`
    window.history.pushState({}, '', next)
    setLocation({ view, invoiceId, approvalId, tab })
    if (!invoiceId) setMobileNavOpen(false)
  }

  const openInvoice: OpenInvoice = (id, approvalId, tab) => navigate(location.view, id, approvalId, tab)

  return <div className="app-shell"><aside className={`sidebar ${mobileNavOpen ? 'mobile-open' : ''}`}><div className="sidebar-brand"><span className="brand-mark"><FileCheck2 size={22} aria-hidden="true" /></span><span className="brand-name">Invoice<span>Ops</span></span></div><div className="workspace-switch"><span className="workspace-icon">{session.workspace.name.slice(0, 1).toUpperCase()}</span><span><strong>{session.workspace.name}</strong><small>{session.mode === 'DEMO' ? 'Demo workspace' : 'Connected workspace'}</small></span><PanelLeftClose size={15} aria-hidden="true" /></div>
      <nav className="sidebar-nav" aria-label="Main navigation"><div className="nav-label">WORKSPACE</div>{navigation.slice(0, 4).map((item) => <button type="button" key={item.id} className={location.view === item.id ? 'nav-item active' : 'nav-item'} aria-current={location.view === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}><item.icon size={18} aria-hidden="true" /><span>{item.label}</span>{item.id === 'approvals' && !!pendingApprovals && <span className="nav-count">{pendingApprovals}</span>}{item.id === 'exceptions' && !!openExceptions && <span className="nav-count warning">{openExceptions}</span>}</button>)}<div className="nav-label nav-label-spaced">REFERENCE</div>{navigation.slice(4).map((item) => <button type="button" key={item.id} className={location.view === item.id ? 'nav-item active' : 'nav-item'} aria-current={location.view === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}><item.icon size={18} aria-hidden="true" /><span>{item.label}</span></button>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-mode"><span className="mode-indicator" /><div><strong>{session.mode === 'DEMO' ? 'Demo environment' : 'Connected environment'}</strong><small>{session.mode === 'DEMO' ? 'Simulated provider responses' : 'Live adapters configured'}</small></div></div><div className="sidebar-user"><span className="user-avatar">{session.user.name.slice(0, 1).toUpperCase()}</span><div><strong>{session.user.name}</strong><small>{session.user.role}</small></div><button type="button" className="sidebar-logout" title="Sign out" aria-label="Sign out" onClick={onLogout}><LogOut size={17} aria-hidden="true" /></button></div></div>
    </aside><div className="main-shell"><header className="topbar"><div className="topbar-left"><button type="button" className="mobile-menu-button" aria-label={mobileNavOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={mobileNavOpen} onClick={() => setMobileNavOpen(!mobileNavOpen)}><LayoutGrid size={20} aria-hidden="true" /></button><span className="topbar-breadcrumb">Workspace <span>/</span> {navigation.find((item) => item.id === location.view)?.label}</span></div><div className="topbar-right"><span className={`connection-indicator ${connectors.isError || connectorBad ? 'attention' : ''}`}>{connectors.isError ? <WifiOff size={15} aria-hidden="true" /> : <Wifi size={15} aria-hidden="true" />}{statusLabel}</span><span className="topbar-separator" /><span className="topbar-user">{session.user.name}</span></div></header>
      {session.mode === 'DEMO' && <div className="demo-banner"><Archive size={16} aria-hidden="true" /><strong>Synthetic demo dataset</strong><span>All invoices, vendors, provider responses and accounting records are fictional.</span></div>}
      <main className="main-content" id="main-content">{location.view === 'queue' && <QueueView openInvoice={openInvoice} role={session.user.role} />}{location.view === 'approvals' && <ApprovalsView openInvoice={openInvoice} />}{location.view === 'exceptions' && <ExceptionsView openInvoice={openInvoice} role={session.user.role} />}{location.view === 'postings' && <PostingsView openInvoice={openInvoice} />}{location.view === 'vendors' && <VendorsView openInvoice={openInvoice} />}{location.view === 'connectors' && <ConnectorsView />}</main>
      <footer className="app-footer"><span>InvoiceOps · Finance operations workspace</span><span>{session.mode === 'DEMO' ? 'LOCAL DEMO' : 'CONNECTED'}</span></footer>
    </div>{location.invoiceId && <InvoiceDrawer key={`${location.invoiceId}-${location.tab || 'review'}`} id={location.invoiceId} approvalId={location.approvalId} initialTab={location.tab} session={session} onClose={() => navigate(location.view)} />}
  </div>
}

export default function App() {
  const queryClient = useQueryClient()
  const [sessionOverride, setSessionOverride] = useState<Session | null>(null)
  const [signedOut, setSignedOut] = useState(false)
  const sessionQuery = useQuery({ queryKey: ['session'], queryFn: api.session, retry: false, staleTime: 60_000, enabled: !signedOut })
  const logout = useMutation({ mutationFn: api.logout, onSuccess: () => { setSignedOut(true); setSessionOverride(null); queryClient.clear(); window.history.replaceState({}, '', window.location.pathname) } })
  const session = sessionOverride || sessionQuery.data

  if (signedOut || (sessionQuery.isError && sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401)) return <Login onLogin={(value) => { setSessionOverride(value); setSignedOut(false); queryClient.setQueryData(['session'], value) }} />
  if (sessionQuery.isPending && !session) return <div className="boot-state"><Loading label="Opening your workspace…" /></div>
  if (sessionQuery.isError && !session) return <div className="boot-state"><ErrorState error={sessionQuery.error} onRetry={() => sessionQuery.refetch()} /></div>
  if (!session) return <Login onLogin={(value) => { setSessionOverride(value); setSignedOut(false); queryClient.setQueryData(['session'], value) }} />
  return <Workspace session={session} onLogout={() => logout.mutate()} />
}
