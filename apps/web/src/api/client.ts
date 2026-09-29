import type {
  Approval,
  Connector,
  Digest,
  ExceptionItem,
  InvoiceDetail,
  InvoiceSummary,
  ListResponse,
  Session,
  Vendor,
  VendorHistory,
} from './types'
import type { components } from './openapi.generated'

const apiBase = import.meta.env.VITE_API_BASE_URL || ''

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(init.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch {
    throw new ApiError('The service could not be reached. Check the local API and try again.', 0, 'DISCONNECTED')
  }

  const contentType = response.headers.get('content-type') || ''
  const body: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '')

  if (!response.ok) {
    const payload = typeof body === 'object' && body !== null ? body as Record<string, unknown> : {}
    const detail = payload.detail
    const validationMessage = Array.isArray(detail)
      ? detail.map((item) => typeof item === 'object' && item !== null && 'msg' in item ? String(item.msg) : '').filter(Boolean).join('; ')
      : ''
    const message = typeof detail === 'string'
      ? detail
      : validationMessage
        ? validationMessage
      : typeof payload.message === 'string'
        ? payload.message
        : response.status === 403
          ? 'Your account does not have access to this action.'
          : response.status === 401
            ? 'Your session has expired. Sign in again.'
            : `The request failed (${response.status}).`
    throw new ApiError(message, response.status, typeof payload.code === 'string' ? payload.code : undefined)
  }
  return body as T
}

function post<T>(path: string, value?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: value === undefined ? undefined : JSON.stringify(value) })
}

export const api = {
  session: () => request<Session>('/api/session'),
  login: (username: string, password: string) => {
    const body: components['schemas']['LoginInput'] = { username, password }
    return post<Session>('/api/login', body)
  },
  logout: () => post<void>('/api/logout'),
  invoices: () => request<ListResponse<InvoiceSummary>>('/api/invoices'),
  invoice: (id: string) => request<InvoiceDetail>(`/api/invoices/${encodeURIComponent(id)}`),
  approvals: () => request<ListResponse<Approval>>('/api/approvals'),
  decideApproval: (id: string, decision: 'approve' | 'reject', proposal_version: number, note: string) => {
    const body: components['schemas']['DecisionInput'] = { decision, proposal_version, note }
    return post<Approval>(`/api/approvals/${encodeURIComponent(id)}/decide`, body)
  },
  exceptions: () => request<ListResponse<ExceptionItem>>('/api/exceptions'),
  resolveException: (id: string, resolution: 'accept' | 'reject' | 'request_revision', note: string) => {
    const body: components['schemas']['ResolveInput'] = { resolution, note }
    return post<ExceptionItem>(`/api/exceptions/${encodeURIComponent(id)}/resolve`, body)
  },
  connectors: () => request<ListResponse<Connector>>('/api/connectors/health'),
  vendors: () => request<ListResponse<Vendor>>('/api/vendors'),
  vendorHistory: (id: string) => request<VendorHistory>(`/api/vendors/${encodeURIComponent(id)}/history`),
  digest: () => request<Digest>('/api/digests/latest'),
  replay: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ event_id: string; status: string }>('/api/replay', { method: 'POST', body: form })
  },
}
