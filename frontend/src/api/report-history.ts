/** 报告历史检索 / 来源核验 / 核数批次 / 快照留档 的接口封装。 */
import { request } from './client'
import type {
  AttributionRecord,
  BatchPlan,
  OutputSearchResult,
  ReconciliationBatch,
  ReportOutputItem,
  ReportSnapshot,
  ReportSource,
} from '@/data/types'

async function parse<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) throw new Error(`${fallback}（HTTP ${response.status}）`)
  return (await response.json()) as T
}

export type OutputSearchParams = {
  business_period?: string
  source?: string
  metric?: string
  keyword?: string
  as_of?: string
}

export async function searchReportOutputs(
  params: OutputSearchParams,
): Promise<OutputSearchResult> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value)
  })
  const response = await request(`/api/report-history?${query.toString()}`)
  return parse<OutputSearchResult>(response, '报告历史检索失败')
}

export async function getReportOutput(
  outputId: number,
  asOf?: string,
): Promise<ReportOutputItem> {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''
  const response = await request(`/api/report-history/${outputId}${query}`)
  return parse<ReportOutputItem>(response, '报告输出读取失败')
}

export async function listReportSources(): Promise<ReportSource[]> {
  const response = await request('/api/report-history/sources')
  const payload = await parse<{ items: ReportSource[] }>(response, '取数来源读取失败')
  return payload.items
}

export async function registerAttribution(
  outputId: number,
  values: {
    source_name: string
    source_key?: string | null
    status?: string
    evidence_ref?: string | null
    evidence_detail?: string | null
    display_only?: boolean
    registered_by?: string
    registered_at?: string | null
  },
): Promise<{ ok: boolean; message: string; output?: ReportOutputItem }> {
  const response = await request(`/api/report-history/${outputId}/attributions`, {
    method: 'POST',
    body: JSON.stringify(values),
  })
  return parse(response, '来源凭据登记失败')
}

export async function listAttributions(
  outputId: number,
): Promise<{ output_no: string; items: AttributionRecord[] }> {
  const response = await request(`/api/report-history/${outputId}/attributions`)
  return parse(response, '来源凭据流水读取失败')
}

export type DispatchValues = {
  business_period: string
  source?: string
  metric?: string
  verify_mode: 'filter_time' | 'dispatch_time'
  filtered_at?: string
  dispatched_by?: string
  note?: string
  dry_run?: boolean
}

export async function previewBatch(values: DispatchValues): Promise<BatchPlan> {
  const response = await request('/api/report-history/batches', {
    method: 'POST',
    body: JSON.stringify({ ...values, dry_run: true }),
  })
  return parse<BatchPlan>(response, '下发试算失败')
}

export async function dispatchBatch(
  values: DispatchValues,
): Promise<{ ok: boolean; message: string; batch?: ReconciliationBatch }> {
  const response = await request('/api/report-history/batches', {
    method: 'POST',
    body: JSON.stringify(values),
  })
  return parse(response, '核数批下发失败')
}

export async function listBatches(): Promise<ReconciliationBatch[]> {
  const response = await request('/api/report-history/batches')
  const payload = await parse<{ items: ReconciliationBatch[] }>(response, '核数批读取失败')
  return payload.items
}

export async function getBatch(batchId: number): Promise<ReconciliationBatch> {
  const response = await request(`/api/report-history/batches/${batchId}`)
  return parse<ReconciliationBatch>(response, '核数批读取失败')
}

export async function createReportSnapshot(values: {
  report_id: number
  output_id: number
  snapshot_name?: string
  as_of?: string
}): Promise<{ ok: boolean; message?: string; snapshot_id?: number; output_no?: string }> {
  const response = await request('/api/report-history/snapshots', {
    method: 'POST',
    body: JSON.stringify(values),
  })
  return parse(response, '报告快照生成失败')
}

export async function listReportSnapshots(reportId?: number): Promise<ReportSnapshot[]> {
  const query = reportId ? `?report_id=${reportId}` : ''
  const response = await request(`/api/report-history/snapshots${query}`)
  const payload = await parse<{ items: ReportSnapshot[] }>(response, '报告快照读取失败')
  return payload.items
}

export async function verifyReportSnapshot(snapshotId: number): Promise<{
  snapshot_id: number
  output_no: string
  output_id: number
  source: {
    source_key: string | null
    source_name: string | null
    source_status: string
    evidence_ref: string | null
    display_only: boolean
  }
  metric_data: { metric_name: string | null; current_value: number | null }[]
  frozen_at: string
  metric_data_matches_content: boolean
  complete: boolean
}> {
  const response = await request(`/api/report-history/snapshots/${snapshotId}/verify`)
  return parse(response, '快照核对失败')
}
