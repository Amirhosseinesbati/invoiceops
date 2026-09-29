import type { ReactNode } from 'react'
import { AlertCircle, ArrowRight, Inbox, LoaderCircle, RefreshCw, WifiOff } from 'lucide-react'
import { ApiError } from '../api/client'
import { statusText, statusTone } from '../lib'

export function Badge({ value, children }: { value?: string; children?: ReactNode }) {
  const tone = statusTone(value || '')
  return <span className={`badge badge-${tone}`}><span className="badge-dot" />{children || statusText(value || 'Unknown')}</span>
}

export function IconButton({ label, children, onClick, disabled }: { label: string; children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return <button className="icon-button" type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled}>{children}</button>
}

export function SectionHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="section-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action && <div className="section-action">{action}</div>}</div>
}

export function Loading({ label = 'Loading current records…' }: { label?: string }) {
  return <div className="state-card" role="status"><LoaderCircle className="spin" size={26} aria-hidden="true" /><strong>{label}</strong><span>Fetching the latest workspace data.</span></div>
}

export function Empty({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="state-card"><div className="state-icon"><Inbox size={25} aria-hidden="true" /></div><strong>{title}</strong><span>{description}</span>{action}</div>
}

export function ErrorState({ error, onRetry, compact = false }: { error: unknown; onRetry: () => void; compact?: boolean }) {
  const disconnected = error instanceof ApiError && error.status === 0
  const forbidden = error instanceof ApiError && error.status === 403
  const message = error instanceof Error ? error.message : 'Something went wrong while loading this area.'
  return <div className={`state-card state-error ${compact ? 'state-compact' : ''}`} role="alert">
    <div className="state-icon">{disconnected ? <WifiOff size={24} aria-hidden="true" /> : <AlertCircle size={24} aria-hidden="true" />}</div>
    <strong>{disconnected ? 'Service disconnected' : forbidden ? 'Access restricted' : 'Unable to load this view'}</strong>
    <span>{message}</span>
    <button className="button button-secondary" type="button" onClick={onRetry}><RefreshCw size={16} aria-hidden="true" />Try again</button>
  </div>
}

export function TextLink({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button className="text-link" type="button" onClick={onClick}>{children}<ArrowRight size={15} aria-hidden="true" /></button>
}

export function Field({ label, value, mono = false }: { label: string; value: ReactNode; mono?: boolean }) {
  return <div className="field"><span>{label}</span><strong className={mono ? 'mono' : ''}>{value ?? '—'}</strong></div>
}
