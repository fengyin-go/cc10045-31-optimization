<template>
  <section class="page report-history" data-testid="report-history">
    <header class="page-head">
      <div>
        <h2>报告历史与核数</h2>
        <p class="page-desc">
          按业务期间和指标取数来源检索实际生成的报告输出，确认来源后下发核数，
          并从检索结果中选中的那一份输出留档。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="refresh" type="button" @click="refreshAll">刷新</button>
      </div>
    </header>

    <nav class="tabs" data-testid="tabs">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        class="tab"
        :class="{ active: activeTab === tab.key }"
        :data-testid="`tab-${tab.key}`"
        type="button"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </nav>

    <p v-if="errorMessage" class="error-text banner" data-testid="error">{{ errorMessage }}</p>
    <p v-if="notice" class="notice banner" data-testid="notice">{{ notice }}</p>

    <!-- ==================== 检索 ==================== -->
    <template v-if="activeTab === 'search'">
      <form class="filter-bar" data-testid="search-form" @submit.prevent="doSearch">
        <label class="filter-item">
          <span>业务期间</span>
          <input
            v-model="query.business_period"
            data-testid="filter-period"
            placeholder="如 2026-11"
          />
        </label>
        <label class="filter-item">
          <span>指标取数来源</span>
          <input
            v-model="query.source"
            data-testid="filter-source"
            placeholder="规范名或旧简称，如 北区渠道 / 北区"
          />
        </label>
        <label class="filter-item">
          <span>指标</span>
          <input v-model="query.metric" data-testid="filter-metric" placeholder="按指标名称检索" />
        </label>
        <button class="btn primary" data-testid="search" type="submit">检索报告输出</button>
        <button class="btn ghost" data-testid="search-reset" type="button" @click="resetSearch">
          重置
        </button>
      </form>

      <p v-if="result" class="verify-line" data-testid="verify-line">
        本次查验时点：<code>{{ result.context.verified_at }}</code>
        <span v-if="result.context.resolved_sources.length" data-testid="resolved-sources">
          ，来源解析为
          <strong v-for="src in result.context.resolved_sources" :key="src.source_key">
            {{ src.source_name }}（{{ src.source_key }}<template v-if="src.aliases.length">，旧简称：{{ src.aliases.join('、') }}</template>）
          </strong>
        </span>
        <span v-else>，未解析到登记来源</span>
      </p>

      <table class="data-table" data-testid="result-table">
        <thead>
          <tr>
            <th></th>
            <th>输出编号</th>
            <th>报告</th>
            <th>业务期间</th>
            <th>来源</th>
            <th>来源状态</th>
            <th>指标数据</th>
            <th>生成时间</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in result?.items ?? []"
            :key="item.output_id"
            :data-testid="`output-${item.output_no}`"
            :data-status="item.source_status"
            :class="{ selected: selected?.output_id === item.output_id }"
          >
            <td>
              <input
                type="radio"
                name="selected-output"
                :data-testid="`select-${item.output_no}`"
                :checked="selected?.output_id === item.output_id"
                @change="selectOutput(item)"
              />
            </td>
            <td><code>{{ item.output_no }}</code></td>
            <td>{{ item.report_name }}</td>
            <td>{{ item.business_period || '—' }}</td>
            <td>
              {{ item.source_name || '—' }}
              <small v-if="item.display_name && item.display_name !== item.source_name" class="reason">
                正文原名：{{ item.display_name }}
              </small>
            </td>
            <td>
              <span
                class="badge"
                :class="item.source_status === '已确认' ? 'ok' : item.source_status === '来源缺失' ? 'bad' : 'warn'"
                :data-testid="`status-${item.output_no}`"
              >
                {{ item.status_label }}
              </span>
              <small class="reason">{{ item.status_reason }}</small>
              <small v-if="item.display_only" class="reason">（正文只有显示名，未删除）</small>
              <small v-if="item.already_dispatched" class="reason" :data-testid="`dispatched-${item.output_no}`">
                已在 {{ item.dispatched_batches.join('、') }} 下发
              </small>
              <small v-else-if="item.needs_reconciliation" class="reason">待继续核对</small>
            </td>
            <td>
              <span v-for="(metric, index) in item.metric_data" :key="metricKey(metric, index)" class="metric-pill">
                {{ metric.metric_name }}={{ formatValue(metric.current_value) }}
              </span>
            </td>
            <td>{{ item.generated_at }}</td>
          </tr>
          <tr v-if="result && !result.items.length">
            <td colspan="8" class="empty-state">没有符合本次期间与来源条件的报告输出</td>
          </tr>
        </tbody>
      </table>

      <div v-if="selected" class="panel" data-testid="selection-panel">
        <h3>已选输出 {{ selected.output_no }}</h3>
        <p class="hint">
          标签：{{ selected.status_label }} · 来源：{{ selected.source_name || '—' }} ·
          凭据：{{ selected.evidence_ref || '无' }}
        </p>
        <div class="page-actions">
          <button
            class="btn primary"
            data-testid="archive-selected"
            type="button"
            @click="archiveSelected"
          >
            用选中输出留档
          </button>
          <button
            v-if="selected.dispatchable"
            class="btn"
            data-testid="dispatch-from-selection"
            type="button"
            @click="openDispatch(selected!)"
          >
            按本次查验下发核数
          </button>
          <button
            class="btn"
            data-testid="show-attributions"
            type="button"
            @click="showAttributions(selected.output_id)"
          >
            来源凭据流水
          </button>
        </div>
        <div v-if="attributions.length" class="attribution-list" data-testid="attribution-list">
          <h4>{{ attributions[0]?.output_id ? `输出 ${selected.output_no} 的来源凭据` : '' }}</h4>
          <ul>
            <li v-for="attr in attributions" :key="attr.id">
              {{ attr.registered_at }} ·
              {{ attr.source_name }}
              <span class="badge" :class="attr.status === '已确认' ? 'ok' : 'warn'">{{ attr.status }}</span>
              <span v-if="attr.display_only">（仅显示名）</span>
              <span v-if="attr.evidence_ref"> · 凭据 {{ attr.evidence_ref }}</span>
              <span v-if="attr.evidence_detail"> · {{ attr.evidence_detail }}</span>
              <span v-if="attr.registered_by"> · 登记人 {{ attr.registered_by }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- 登记来源凭据 -->
      <div v-if="selected" class="panel" data-testid="register-panel">
        <h3>为 {{ selected.output_no }} 补登来源凭据</h3>
        <p class="hint">
          显示名可以解析到规范来源，但只有带可验证凭据的“已确认”来源才能下发核数。
          补登不会改写已经发出的核数批。
        </p>
        <form class="filter-bar" @submit.prevent="submitAttribution()">
          <label class="filter-item">
            <span>来源（规范名/旧简称）</span>
            <input v-model="attrForm.source_name" data-testid="attr-source" required />
          </label>
          <label class="filter-item">
            <span>凭据编号</span>
            <input v-model="attrForm.evidence_ref" data-testid="attr-evidence" placeholder="如 EV-2026-11-0142" />
          </label>
          <label class="filter-item">
            <span>凭据说明</span>
            <input v-model="attrForm.evidence_detail" data-testid="attr-detail" />
          </label>
          <label class="filter-item">
            <span>登记人</span>
            <input v-model="attrForm.registered_by" data-testid="attr-by" />
          </label>
          <button class="btn primary" data-testid="attr-submit" type="submit" :disabled="busy">
            登记凭据
          </button>
          <button
            class="btn ghost"
            data-testid="attr-display-only"
            type="button"
            @click="submitAttribution(true)"
          >
            只登记显示名
          </button>
        </form>
      </div>
    </template>

    <!-- ==================== 核数批 ==================== -->
    <template v-else-if="activeTab === 'batches'">
      <table class="data-table" data-testid="batch-table">
        <thead>
          <tr>
            <th>批次号</th>
            <th>业务期间</th>
            <th>来源</th>
            <th>核验口径</th>
            <th>查验时点</th>
            <th>名单条数</th>
            <th>留待下次</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in batches" :key="batch.id" :data-testid="`batch-${batch.batch_no}`">
            <td><code>{{ batch.batch_no }}</code></td>
            <td>{{ batch.business_period }}</td>
            <td>{{ batch.source_name || '全部' }}</td>
            <td>{{ batch.verify_mode === 'filter_time' ? '按开始筛选时核验' : '下发前重新核验' }}</td>
            <td>{{ batch.as_of }}</td>
            <td>{{ batch.item_count }}</td>
            <td>{{ batch.deferrals }}</td>
            <td>
              <button class="link" data-testid="open-batch" type="button" @click="openBatch(batch.id)">
                重新打开当次名单
              </button>
            </td>
          </tr>
          <tr v-if="!batches.length">
            <td colspan="8" class="empty-state">还没有下发的核数批</td>
          </tr>
        </tbody>
      </table>

      <div v-if="activeBatch" class="panel" data-testid="batch-detail">
        <h3>核数批 {{ activeBatch.batch_no }}（名单已冻结）</h3>
        <p class="hint">
          期间 {{ activeBatch.business_period }} · 来源 {{ activeBatch.source_name || '全部' }} ·
          下发人 {{ activeBatch.dispatched_by || '—' }} · 下发时间 {{ activeBatch.dispatched_at }}
        </p>
        <h4>本批名单</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th>输出编号</th>
              <th>报告</th>
              <th>采用来源</th>
              <th>凭据</th>
              <th>去向说明</th>
              <th>该版指标数据</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in activeBatch.items"
              :key="item.id"
              :data-testid="`batch-item-${item.output_no}`"
            >
              <td><code>{{ item.output_no }}</code></td>
              <td>{{ item.report_name }}</td>
              <td>
                {{ item.source_name }}
                <span class="badge ok">{{ item.source_status }}</span>
              </td>
              <td>{{ item.evidence_ref || '—' }}</td>
              <td>{{ item.disposition }}</td>
              <td>
                <span v-for="(metric, index) in item.metric_data" :key="metricKey(metric, index)" class="metric-pill">
                  {{ metric.metric_name }}={{ formatValue(metric.current_value) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <template v-if="activeBatch.deferrals.length">
          <h4>留待下次核数</h4>
          <table class="data-table" data-testid="batch-deferrals">
            <thead>
              <tr><th>输出编号</th><th>来源</th><th>凭据</th><th>去向</th><th>说明</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in activeBatch.deferrals" :key="item.id">
                <td><code>{{ item.output_no }}</code></td>
                <td>{{ item.source_name }}</td>
                <td>{{ item.evidence_ref || '—' }}</td>
                <td>{{ item.disposition }}</td>
                <td>{{ item.reason }}</td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </template>

    <!-- ==================== 快照留档 ==================== -->
    <template v-else>
      <table class="data-table" data-testid="snapshot-table">
        <thead>
          <tr>
            <th>快照名称</th>
            <th>所属报告</th>
            <th>输出编号</th>
            <th>业务期间</th>
            <th>当时来源</th>
            <th>指标条数</th>
            <th>保存时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="snap in snapshots" :key="snap.id" :data-testid="`snapshot-${snap.id}`">
            <td>{{ snap.snapshot_name }}</td>
            <td>{{ snap.report_id }}</td>
            <td><code>{{ snap.output_no }}</code></td>
            <td>{{ snap.business_period || '—' }}</td>
            <td>
              {{ snap.source_name || '—' }}
              <span
                class="badge"
                :class="snap.source_status === '已确认' ? 'ok' : 'warn'"
              >{{ snap.source_status }}</span>
            </td>
            <td>{{ snap.metric_data.length }}</td>
            <td>{{ snap.created_at }}</td>
            <td>
              <button class="link" data-testid="verify-snapshot" type="button" @click="openSnapshot(snap.id)">
                核对快照内容
              </button>
            </td>
          </tr>
          <tr v-if="!snapshots.length">
            <td colspan="8" class="empty-state">还没有留档的报告快照</td>
          </tr>
        </tbody>
      </table>

      <div v-if="activeSnapshot" class="panel" data-testid="snapshot-detail">
        <h3>快照 {{ activeSnapshot.snapshot_name }}</h3>
        <dl class="snapshot-fields">
          <div><dt>输出编号</dt><dd><code>{{ activeSnapshot.output_no }}</code></dd></div>
          <div><dt>所属报告</dt><dd>{{ activeSnapshot.report_id }}</dd></div>
          <div><dt>业务期间</dt><dd>{{ activeSnapshot.business_period || '—' }}</dd></div>
          <div>
            <dt>当时来源</dt>
            <dd>
              {{ activeSnapshot.source_name || '—' }}
              <span class="badge" :class="activeSnapshot.source_status === '已确认' ? 'ok' : 'warn'">
                {{ activeSnapshot.source_status }}
              </span>
            </dd>
          </div>
          <div><dt>来源凭据</dt><dd>{{ activeSnapshot.evidence_ref || '无（仅显示名）' }}</dd></div>
          <div><dt>固化时点</dt><dd>{{ activeSnapshot.source_as_of }}</dd></div>
        </dl>
        <p v-if="snapshotCheck" class="hint" data-testid="snapshot-check">
          自查结果：
          <span class="badge" :class="snapshotCheck.complete ? 'ok' : 'bad'">
            {{ snapshotCheck.complete ? '输出编号、当时来源与该版指标数据齐全' : '留档信息不完整' }}
          </span>
          · 指标条数与正文一致：{{ snapshotCheck.metric_data_matches_content ? '是' : '否' }}
        </p>
        <h4>该版指标数据</h4>
        <table class="data-table">
          <thead><tr><th>指标</th><th>数值</th><th>单位</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="(metric, index) in activeSnapshot.metric_data" :key="metricKey(metric, index)">
              <td>{{ metric.metric_name }}</td>
              <td>{{ formatValue(metric.current_value) }}</td>
              <td>{{ metric.unit || '—' }}</td>
              <td>{{ metric.status || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- ==================== 下发核数确认 ==================== -->
    <div v-if="dispatchForm" class="modal-backdrop" data-testid="dispatch-modal">
      <div class="modal">
        <h3>下发核数批</h3>
        <p class="hint">
          筛选条件：期间 {{ dispatchForm.business_period }} · 来源 {{ dispatchForm.source || '全部' }}
          · 筛选时点 {{ dispatchForm.filtered_at }}
        </p>
        <label class="create-field">
          <span>核验口径</span>
          <select v-model="dispatchForm.verify_mode" data-testid="verify-mode">
            <option value="filter_time">按开始筛选时核验（固定筛选时点的来源状态）</option>
            <option value="dispatch_time">下发前重新核验（采用当前最新来源状态）</option>
          </select>
        </label>
        <label class="create-field">
          <span>经办人</span>
          <input v-model="dispatchForm.dispatched_by" data-testid="dispatch-by" />
        </label>
        <div class="page-actions">
          <button class="btn" data-testid="dispatch-preview" type="button" @click="previewDispatch">
            试算名单
          </button>
          <button class="btn primary" data-testid="dispatch-confirm" type="button" :disabled="busy" @click="confirmDispatch">
            确认下发
          </button>
          <button class="btn ghost" type="button" @click="dispatchForm = null">取消</button>
        </div>

        <div v-if="plan" class="plan" data-testid="dispatch-plan">
          <h4>试算结果</h4>
          <p>范围内输出 {{ plan.scope_count }} 条，其中可下发 {{ plan.roster.length }} 条。</p>
          <ul>
            <li v-for="item in plan.roster" :key="item.output_id">
              下发：<code>{{ item.output_no }}</code> · {{ item.source_name }} · {{ item.disposition }}
            </li>
            <li v-for="item in plan.deferrals" :key="item.output_id">
              留待：<code>{{ item.output_no }}</code> · {{ item.source_name }} · {{ item.reason }}
            </li>
          </ul>
          <p v-if="!plan.roster.length" class="error-text">
            本次查验没有带可验证凭据的输出，不能下发核数。
          </p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  createReportSnapshot,
  dispatchBatch,
  getBatch,
  listAttributions,
  listBatches,
  listReportSnapshots,
  previewBatch,
  registerAttribution,
  searchReportOutputs,
  verifyReportSnapshot,
} from '@/api/report-history'
import type {
  AttributionRecord,
  BatchPlan,
  OutputSearchResult,
  ReconciliationBatch,
  ReportOutputItem,
  ReportSnapshot,
} from '@/data/types'

const TABS = [
  { key: 'search', label: '报告输出检索' },
  { key: 'batches', label: '核数批' },
  { key: 'snapshots', label: '快照留档' },
] as const

const activeTab = ref<(typeof TABS)[number]['key']>('search')
const errorMessage = ref('')
const notice = ref('')
const busy = ref(false)

const query = reactive({ business_period: '', source: '', metric: '' })
const result = ref<OutputSearchResult | null>(null)
const selected = ref<ReportOutputItem | null>(null)
const attributions = ref<AttributionRecord[]>([])
const attrForm = reactive({
  source_name: '',
  evidence_ref: '',
  evidence_detail: '',
  registered_by: '',
})

const batches = ref<ReconciliationBatch[]>([])
const activeBatch = ref<ReconciliationBatch | null>(null)

const snapshots = ref<ReportSnapshot[]>([])
const activeSnapshot = ref<ReportSnapshot | null>(null)
const snapshotCheck = ref<Awaited<ReturnType<typeof verifyReportSnapshot>> | null>(null)

const dispatchForm = ref<{
  business_period: string
  source: string
  metric: string
  verify_mode: 'filter_time' | 'dispatch_time'
  filtered_at: string
  dispatched_by: string
} | null>(null)
const plan = ref<BatchPlan | null>(null)

function metricKey(metric: { metric_name: string | null }, index: number): string {
  return metric.metric_name ?? `metric-${index}`
}

function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return Number.isInteger(value) ? String(value) : value.toFixed(4)
}

async function doSearch() {
  errorMessage.value = ''
  notice.value = ''
  selected.value = null
  attributions.value = []
  try {
    result.value = await searchReportOutputs({
      business_period: query.business_period || undefined,
      source: query.source || undefined,
      metric: query.metric || undefined,
    })
    notice.value = `共 ${result.value.total} 条报告输出`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检索失败'
  }
}

function resetSearch() {
  query.business_period = ''
  query.source = ''
  query.metric = ''
  result.value = null
  selected.value = null
  attributions.value = []
  notice.value = ''
}

function selectOutput(item: ReportOutputItem) {
  selected.value = item
  attributions.value = []
  notice.value = ''
}

async function showAttributions(outputId: number) {
  errorMessage.value = ''
  try {
    const payload = await listAttributions(outputId)
    attributions.value = payload.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '凭据流水读取失败'
  }
}

async function submitAttribution(displayOnly = false) {
  if (!selected.value) return
  errorMessage.value = ''
  notice.value = ''
  busy.value = true
  try {
    const response = await registerAttribution(selected.value.output_id, {
      source_name: attrForm.source_name,
      status: displayOnly ? '有待翻查' : '已确认',
      evidence_ref: displayOnly ? null : attrForm.evidence_ref || null,
      evidence_detail: attrForm.evidence_detail || null,
      display_only: displayOnly,
      registered_by: attrForm.registered_by || '档案员',
    })
    if (!response.ok) throw new Error(response.message)
    notice.value = response.message
    if (response.output) {
      selected.value = response.output
      result.value = await searchReportOutputs({
        business_period: query.business_period || undefined,
        source: query.source || undefined,
        metric: query.metric || undefined,
      })
    }
    attrForm.evidence_ref = ''
    attrForm.evidence_detail = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '凭据登记失败'
  } finally {
    busy.value = false
  }
}

async function archiveSelected() {
  if (!selected.value) return
  errorMessage.value = ''
  notice.value = ''
  try {
    const response = await createReportSnapshot({
      report_id: selected.value.report_id,
      output_id: selected.value.output_id,
      snapshot_name: `${selected.value.business_period || ''} ${selected.value.report_name} ${selected.value.output_no} 留档`.trim(),
    })
    if (!response.ok) throw new Error(response.message || '留档失败')
    notice.value = `已按输出 ${response.output_no} 留档，快照编号 ${response.snapshot_id}`
    snapshots.value = await listReportSnapshots()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '留档失败'
  }
}

function openDispatch(item: ReportOutputItem) {
  const filteredAt = result.value?.context.verified_at ?? new Date().toISOString()
  plan.value = null
  dispatchForm.value = {
    business_period: item.business_period || query.business_period,
    source: result.value?.context.source_query || query.source,
    metric: query.metric,
    verify_mode: 'filter_time',
    filtered_at: filteredAt,
    dispatched_by: '财务',
  }
}

async function previewDispatch() {
  if (!dispatchForm.value) return
  errorMessage.value = ''
  try {
    plan.value = await previewBatch({
      business_period: dispatchForm.value.business_period,
      source: dispatchForm.value.source || undefined,
      metric: dispatchForm.value.metric || undefined,
      verify_mode: dispatchForm.value.verify_mode,
      filtered_at: dispatchForm.value.filtered_at,
      dispatched_by: dispatchForm.value.dispatched_by,
    })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试算失败'
  }
}

async function confirmDispatch() {
  if (!dispatchForm.value) return
  errorMessage.value = ''
  busy.value = true
  try {
    const response = await dispatchBatch({
      business_period: dispatchForm.value.business_period,
      source: dispatchForm.value.source || undefined,
      metric: dispatchForm.value.metric || undefined,
      verify_mode: dispatchForm.value.verify_mode,
      filtered_at: dispatchForm.value.filtered_at,
      dispatched_by: dispatchForm.value.dispatched_by,
    })
    if (!response.ok) throw new Error(response.message)
    notice.value = response.message
    dispatchForm.value = null
    plan.value = null
    batches.value = await listBatches()
    if (response.batch) activeBatch.value = await getBatch(response.batch.id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '下发失败'
  } finally {
    busy.value = false
  }
}

async function openBatch(batchId: number) {
  errorMessage.value = ''
  try {
    activeBatch.value = await getBatch(batchId)
    activeTab.value = 'batches'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '核数批读取失败'
  }
}

async function openSnapshot(snapshotId: number) {
  errorMessage.value = ''
  try {
    snapshotCheck.value = await verifyReportSnapshot(snapshotId)
    const all = await listReportSnapshots()
    snapshots.value = all
    activeSnapshot.value = all.find((item) => item.id === snapshotId) ?? null
    activeTab.value = 'snapshots'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照核对失败'
  }
}

async function refreshAll() {
  errorMessage.value = ''
  try {
    const [batchList, snapshotList] = await Promise.all([
      listBatches(),
      listReportSnapshots(),
    ])
    batches.value = batchList
    snapshots.value = snapshotList
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '刷新失败'
  }
}

onMounted(async () => {
  await refreshAll()
  await doSearch()
})
</script>

<style scoped>
.tabs { display: flex; gap: 6px; margin-bottom: 12px; }
.tab { border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 6px 14px; cursor: pointer; }
.tab.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.banner { padding: 8px 12px; border-radius: 6px; font-size: 13px; }
.notice { background: #eff6ff; color: #1e40af; }
.error-text.banner { background: #fef3f2; }
.verify-line { font-size: 12px; color: var(--muted); margin: 0 0 8px; }
.verify-line code { background: #eef2f7; padding: 1px 5px; border-radius: 4px; }
.badge { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; }
.badge.ok { background: #dcfce7; color: #166534; }
.badge.warn { background: #fef3c7; color: #92400e; }
.badge.bad { background: #fee2e2; color: #991b1b; }
.reason { display: block; color: var(--muted); font-size: 11px; margin-top: 2px; }
.metric-pill { display: inline-block; background: #f1f5f9; border-radius: 10px; padding: 1px 8px; margin: 1px 3px 1px 0; font-size: 11px; }
tr.selected { background: #eff6ff; }
.panel { margin-top: 14px; padding: 14px; background: #fff; border: 1px solid var(--border); border-radius: 8px; }
.panel h3 { margin: 0 0 6px; font-size: 15px; }
.panel h4 { margin: 14px 0 6px; font-size: 13px; }
.hint { color: var(--muted); font-size: 12px; margin: 4px 0 10px; }
.attribution-list ul { margin: 6px 0 0; padding-left: 18px; font-size: 12px; line-height: 1.9; }
.snapshot-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 0 0 8px; }
.snapshot-fields dt { font-size: 11px; color: var(--muted); }
.snapshot-fields dd { margin: 2px 0 0; font-size: 13px; }
.plan { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); font-size: 12px; }
.plan ul { margin: 6px 0 0; padding-left: 18px; line-height: 1.8; }
select { width: 100%; padding: 7px; border: 1px solid var(--border); border-radius: 6px; }
</style>
