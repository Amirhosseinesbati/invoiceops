export type Role = 'admin' | 'operator' | 'manager' | 'viewer'
export type Mode = 'DEMO' | 'CONNECTED'

export interface Session {
  user: { id: string; name: string; role: Role }
  workspace: { id: string; name: string }
  mode: Mode
}

export interface InvoiceSummary {
  id: string
  vendor_name: string
  invoice_number: string
  amount: number | string
  currency: string
  status: string
  age_days: number
  received_at: string
  po_number: string | null
  findings_count: number
  approval_progress: { approved: number; required: number } | null
  current_version?: number
}

export interface LineItem {
  id?: string
  sku?: string
  description: string
  quantity: number | string
  unit_price: number | string
  amount?: number | string
  total?: number | string
  po_line_id?: string | null
}

export interface Evidence {
  page: number
  snippet?: string
  quote?: string
  field?: string
  label?: string
  confidence?: number | null
}

export interface InvoiceVersion {
  id?: string
  version: number | string
  extraction_version?: number | string
  created_at?: string
  source_hash?: string
  status?: string
  amount?: number | string
  evidence?: Evidence[]
  extraction?: {
    invoice_date?: string
    due_date?: string
    subtotal?: number | string
    tax?: number | string
    total?: number | string
    line_items?: LineItem[]
  }
}

export interface Finding {
  id: string
  kind?: string
  code?: string
  severity?: string
  summary?: string
  message?: string
  status?: string
  blocking?: boolean
  resolved?: boolean
  evidence?: Evidence[]
}

export interface PurchaseOrder {
  id?: string
  number?: string
  po_number?: string
  amount?: number | string
  total?: number | string
  currency?: string
  status?: string
  lines?: LineItem[]
}

export interface Receipt {
  id?: string
  po_number?: string
  received_at?: string
  quantity?: number
  lines?: Array<{ sku?: string; description?: string; quantity?: number; received_quantity?: number; po_line_id?: string }>
}

export interface Approval {
  id: string
  invoice_id: string
  vendor_name?: string
  invoice_number?: string
  amount?: number | string
  currency?: string
  role?: string
  required_role?: string
  status: string
  proposal_version: number
  expires_at?: string | null
  decided_at?: string | null
  decision?: string | null
  decided_by?: string | null
}

export interface TimelineEvent {
  id?: string
  at?: string
  created_at?: string
  type?: string
  event?: string
  title?: string
  detail?: string
  status?: string
  actor?: string
}

export interface InvoiceDetail extends InvoiceSummary {
  vendor_id?: string
  versions?: InvoiceVersion[]
  lines?: LineItem[]
  line_items?: LineItem[]
  findings?: Finding[]
  approvals?: Approval[]
  purchase_order?: PurchaseOrder | null
  receipts?: Receipt[]
  timeline?: TimelineEvent[]
  source_url?: string | null
  due_date?: string | null
  invoice_date?: string | null
  tax_amount?: number | string | null
  subtotal?: number | string | null
  extraction_version?: number | string
  posting_operation?: { id: string; status: string; accounting_id?: string | null } | null
  accounting_id?: string | null
}

export interface ExceptionItem {
  id: string
  invoice_id: string
  kind: string
  summary: string
  status: string
  created_at: string
  details?: string | Record<string, unknown> | null
}

export interface Connector {
  name: string
  mode: string
  status: string
  last_checked_at?: string | null
  message?: string | null
}

export interface Vendor {
  id: string
  name: string
  invoice_count?: number
  open_count?: number
}

export interface VendorHistory {
  vendor: Vendor
  invoices: InvoiceSummary[]
}

export interface Digest {
  id?: string
  generated_at?: string
  created_at?: string
  pending?: number
  failed?: number
  completed?: number
  counts?: Record<string, number>
}

export interface ListResponse<T> {
  items: T[]
  total?: number
}
