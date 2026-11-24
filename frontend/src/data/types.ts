/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

/** ===== 报告历史检索 / 来源核验 / 核数批次 / 快照留档 ===== */

export type MetricDatum = {
  metric_name: string | null
  metric_type?: string | null
  unit?: string
  current_value: number | null
  baseline?: number | null
  status?: string | null
}

export type ReportSource = {
  source_key: string
  source_name: string
  aliases: string[]
  source_type: string
  status: string
}

export type ReportOutputItem = {
  output_id: number
  output_no: string
  report_id: number
  report_name: string
  business_period: string
  generated_at: string
  source_key: string | null
  source_name: string | null
  display_name: string | null
  source_status: string
  status_label: string
  status_reason: string
  display_only: boolean
  evidence_ref: string | null
  evidence_registered_at: string | null
  metric_data: MetricDatum[]
  metric_names: (string | null)[]
  dispatchable: boolean
  verified_at: string
  attribution_count: number
  already_dispatched: boolean
  dispatched_batches: string[]
  needs_reconciliation: boolean
}

export type SearchContext = {
  verified_at: string
  source_query: string | null
  resolved_sources: ReportSource[]
  business_period: string | null
  metric: string | null
}

export type OutputSearchResult = {
  items: ReportOutputItem[]
  total: number
  page: number
  size: number
  context: SearchContext
}

export type AttributionRecord = {
  id: number
  output_id: number
  source_key: string
  source_name: string
  status: string
  evidence_ref: string | null
  evidence_detail: string | null
  display_only: boolean
  registered_by: string
  registered_at: string
}

export type BatchItem = {
  id: number
  output_id: number
  output_no: string
  report_id: number
  report_name: string
  business_period: string
  source_key: string | null
  source_name: string | null
  source_status: string | null
  evidence_ref: string | null
  evidence_registered_at: string | null
  evidence_late: boolean
  disposition: string
  metric_data: MetricDatum[]
  generated_at: string | null
  attribution_trace: {
    locked: boolean
    source_name?: string
    status?: string
    evidence_ref?: string
    evidence_detail?: string
    registered_by?: string
    registered_at?: string
    reason?: string
  }
}

export type BatchDeferral = {
  id: number
  output_id: number
  output_no: string
  source_name: string | null
  evidence_ref: string | null
  evidence_registered_at: string | null
  disposition: string
  reason: string
}

export type BatchPlan = {
  ok: boolean
  dry_run?: boolean
  message?: string
  scope_count?: number
  verify_as_of?: string
  roster: BatchItem[]
  deferrals: BatchDeferral[]
}

export type ReconciliationBatch = {
  id: number
  batch_no: string
  business_period: string
  source_key: string | null
  source_name: string
  verify_mode: string
  filtered_at: string
  as_of: string
  dispatched_by: string
  dispatched_at: string
  item_count: number
  note: string
  metric_scope: string[]
  items: BatchItem[]
  deferrals: BatchDeferral[]
  frozen: boolean
}

export type ReportSnapshot = {
  id: number
  snapshot_name: string
  report_id: number
  snapshot_content: Record<string, unknown>
  comparison_diff: unknown
  status: string
  output_id: number | null
  output_no: string | null
  business_period: string | null
  source_key: string | null
  source_name: string | null
  source_status: string | null
  evidence_ref: string | null
  source_as_of: string | null
  source_display_only: boolean
  metric_data: MetricDatum[]
  created_at: string
  search_summary?: {
    output_no: string | null
    source_name: string | null
    source_status: string | null
    business_period: string | null
    metric_count: number
    display_only: boolean
  }
}
