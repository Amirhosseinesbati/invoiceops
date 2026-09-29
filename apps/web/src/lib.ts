import type { InvoiceDetail, InvoiceSummary } from './api/types'

export function money(value: number | string | null | undefined, currency = 'USD'): string {
  const amount = typeof value === 'string' ? Number(value) : value
  if (amount === undefined || amount === null || !Number.isFinite(amount)) return '—'
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(amount)
  } catch {
    return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(amount)} ${currency}`
  }
}

export function date(value: string | null | undefined, options?: Intl.DateTimeFormatOptions): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return new Intl.DateTimeFormat('en-US', options || { month: 'short', day: 'numeric', year: 'numeric' }).format(parsed)
}

export function dateTime(value: string | null | undefined): string {
  return date(value, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function statusText(status?: string): string {
  return (status || 'Unknown').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function statusTone(status: string): 'green' | 'amber' | 'red' | 'blue' | 'slate' {
  if (['draft_created', 'completed', 'approved', 'healthy', 'connected', 'active', 'resolved'].includes(status)) return 'green'
  if (['needs_review', 'awaiting_approval', 'pending', 'uncertain', 'degraded', 'simulated'].includes(status)) return 'amber'
  if (['failed', 'rejected', 'disconnected', 'error', 'unavailable', 'blocking'].includes(status)) return 'red'
  if (['extracting', 'validating', 'posting', 'received'].includes(status)) return 'blue'
  return 'slate'
}

export function isOpen(invoice: InvoiceSummary): boolean {
  return !['draft_created', 'completed', 'rejected'].includes(invoice.status)
}

export function currentVersion(invoice: InvoiceDetail): number | string | undefined {
  return invoice.current_version ?? invoice.extraction_version ?? invoice.versions?.[0]?.extraction_version ?? invoice.versions?.[0]?.version
}

export function safeSourceUrl(value: string | null | undefined, page?: number): string | null {
  if (!value) return null
  try {
    const url = new URL(value, window.location.origin)
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/')) return null
    if (page && Number.isInteger(page) && page > 0) url.hash = `page=${page}`
    return url.toString()
  } catch {
    return null
  }
}
