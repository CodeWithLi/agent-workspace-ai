<template>
  <el-dialog
    :model-value="modelValue"
    class="trace-comparison-dialog"
    width="min(1040px, calc(100vw - 28px))"
    :close-on-click-modal="false"
    :destroy-on-close="false"
    @close="emit('close')"
  >
    <template #header>
      <div class="comparison-dialog-title">
        <span>多 Agent 运行分析</span>
        <h2>运行基线对比</h2>
      </div>
    </template>

    <div class="comparison-picker" aria-label="运行对比选择">
      <label>
        <span>基线运行</span>
        <el-select v-model="baselineModel" filterable placeholder="选择基线运行" aria-label="选择基线运行">
          <el-option
            v-for="run in finishedRuns"
            :key="run.workflow_id"
            :label="runOptionLabel(run)"
            :value="run.workflow_id"
            :disabled="run.workflow_id === candidateId"
          />
        </el-select>
      </label>
      <el-button
        class="swap-runs"
        :icon="Sort"
        circle
        :disabled="!baselineId || !candidateId"
        aria-label="交换基线和候选运行"
        title="交换基线和候选运行"
        @click="swapRuns"
      />
      <label>
        <span>候选运行</span>
        <el-select v-model="candidateModel" filterable placeholder="选择候选运行" aria-label="选择候选运行">
          <el-option
            v-for="run in candidateRuns"
            :key="run.workflow_id"
            :label="runOptionLabel(run)"
            :value="run.workflow_id"
          />
        </el-select>
      </label>
      <el-button
        class="start-comparison"
        type="primary"
        :icon="DataAnalysis"
        :loading="loading"
        :disabled="!canCompare"
        @click="emit('compare')"
      >开始对比</el-button>
    </div>

    <el-alert
      class="comparison-scope-alert"
      type="info"
      :closable="false"
      show-icon
      title="效率结论不替代内容质量评测"
      description="结果只比较运行状态、耗时、Token 和预估成本；应结合 Agent 评测门禁判断交付质量。"
    />

    <div v-if="loading" class="comparison-loading" aria-label="正在比较运行"><el-skeleton :rows="9" animated /></div>
    <div v-else-if="error" class="comparison-error" role="alert">
      <div><strong>运行对比失败</strong><span>{{ error }}</span></div>
      <el-button :disabled="!canCompare" @click="emit('compare')">重新对比</el-button>
    </div>
    <el-empty
      v-else-if="!comparison"
      :description="finishedRuns.length < 2 ? '当前筛选范围内没有可比较的已结束运行' : '选择同一项目的基线和候选运行'"
      :image-size="70"
    />

    <div v-else class="comparison-result">
      <section class="comparison-summary" :class="`verdict-${comparison.summary.verdict.toLowerCase()}`" aria-labelledby="comparison-summary-title">
        <div class="comparison-run-side">
          <span>基线 #{{ comparison.baseline.workflow_id }}</span>
          <strong>{{ statusLabel(comparison.baseline.status) }}</strong>
          <small>{{ comparison.baseline.project_name }} · {{ formatDateTime(comparison.baseline.created_at) }}</small>
        </div>
        <el-icon class="comparison-arrow" aria-hidden="true"><Right /></el-icon>
        <div class="comparison-run-side">
          <span>候选 #{{ comparison.candidate.workflow_id }}</span>
          <strong>{{ statusLabel(comparison.candidate.status) }}</strong>
          <small>{{ comparison.candidate.project_name }} · {{ formatDateTime(comparison.candidate.created_at) }}</small>
        </div>
        <div class="comparison-verdict">
          <span id="comparison-summary-title">效率结论</span>
          <strong>{{ verdictLabel(comparison.summary.verdict) }}</strong>
          <small>改善 {{ comparison.summary.improvement_count }} 项 · 退化 {{ comparison.summary.regression_count }} 项</small>
        </div>
      </section>

      <section class="comparison-section" aria-labelledby="metric-comparison-title">
        <div class="comparison-section-head">
          <div><h3 id="metric-comparison-title">关键指标</h3><p>变化方向采用 5% 容差，并过滤微小绝对波动。</p></div>
          <el-tag :type="directionTagType(comparison.summary.outcome_direction)" effect="plain">运行结果 {{ directionLabel(comparison.summary.outcome_direction) }}</el-tag>
        </div>
        <div class="comparison-metric-grid">
          <article v-for="metric in comparison.metrics" :key="metric.key" class="comparison-metric">
            <div><span>{{ metric.label }}</span><el-tag size="small" :type="directionTagType(metric.direction)" effect="plain">{{ directionLabel(metric.direction) }}</el-tag></div>
            <strong>{{ formatMetric(metric.candidate_value, metric.unit) }}</strong>
            <small>基线 {{ formatMetric(metric.baseline_value, metric.unit) }} · {{ formatMetricDelta(metric) }}</small>
          </article>
        </div>
      </section>

      <section class="comparison-section" aria-labelledby="agent-comparison-title">
        <div class="comparison-section-head">
          <div><h3 id="agent-comparison-title">Agent 变化</h3><p>模型、调用、Token、成本和平均延迟按角色对齐。</p></div>
          <span>{{ comparison.summary.changed_agent_count }} 个 Agent 有变化</span>
        </div>
        <el-table :data="comparison.agents" class="comparison-table desktop-comparison-table" table-layout="fixed">
          <el-table-column label="Agent" min-width="170">
            <template #default="{ row }"><div class="comparison-entity"><strong>{{ row.agent_name }}</strong><small>{{ roleLabel(row.agent_role) }}</small></div></template>
          </el-table-column>
          <el-table-column label="模型变化" min-width="220">
            <template #default="{ row }"><div class="model-change"><span>{{ joinValues(row.baseline_models) }}</span><el-icon><Right /></el-icon><strong>{{ joinValues(row.candidate_models) }}</strong></div></template>
          </el-table-column>
          <el-table-column label="调用" width="92" align="right"><template #default="{ row }">{{ row.baseline_calls }} → {{ row.candidate_calls }}</template></el-table-column>
          <el-table-column label="Token Δ" width="104" align="right"><template #default="{ row }"><span :class="deltaClass(row.token_delta, true)">{{ formatSignedNumber(row.token_delta) }}</span></template></el-table-column>
          <el-table-column label="成本 Δ" width="112" align="right"><template #default="{ row }"><span :class="deltaClass(row.cost_delta_micros, true)">{{ formatSignedCost(row.cost_delta_micros) }}</span></template></el-table-column>
          <el-table-column label="平均延迟 Δ" width="126" align="right"><template #default="{ row }"><span :class="directionClass(row.latency_direction)">{{ formatSignedDuration(row.latency_delta_ms) }}</span></template></el-table-column>
          <el-table-column label="状态" width="94"><template #default="{ row }"><el-tag :type="changeTagType(row.change_type)" effect="plain">{{ changeTypeLabel(row.change_type) }}</el-tag></template></el-table-column>
        </el-table>
        <div class="mobile-comparison-list">
          <article v-for="agent in comparison.agents" :key="agent.key" class="comparison-mobile-card">
            <div class="comparison-mobile-head"><div class="comparison-entity"><strong>{{ agent.agent_name }}</strong><small>{{ roleLabel(agent.agent_role) }}</small></div><el-tag :type="changeTagType(agent.change_type)" effect="plain">{{ changeTypeLabel(agent.change_type) }}</el-tag></div>
            <p>{{ joinValues(agent.baseline_models) }} → {{ joinValues(agent.candidate_models) }}</p>
            <dl><div><dt>调用</dt><dd>{{ agent.baseline_calls }} → {{ agent.candidate_calls }}</dd></div><div><dt>Token Δ</dt><dd :class="deltaClass(agent.token_delta, true)">{{ formatSignedNumber(agent.token_delta) }}</dd></div><div><dt>延迟 Δ</dt><dd :class="directionClass(agent.latency_direction)">{{ formatSignedDuration(agent.latency_delta_ms) }}</dd></div></dl>
          </article>
        </div>
      </section>

      <section class="comparison-section" aria-labelledby="span-comparison-title">
        <div class="comparison-section-head">
          <div><h3 id="span-comparison-title">节点与分支变化</h3><p>重复尝试按节点或 Agent 角色合并，避免同一分支拆散比较。</p></div>
          <span>{{ comparison.summary.changed_span_count }} 个阶段有变化</span>
        </div>
        <el-table :data="comparison.spans" class="comparison-table desktop-comparison-table" table-layout="fixed">
          <el-table-column label="阶段" min-width="190"><template #default="{ row }"><div class="comparison-entity"><strong>{{ row.label }}</strong><small>{{ kindLabel(row.kind) }} · {{ row.node }}</small></div></template></el-table-column>
          <el-table-column label="执行次数" width="104" align="right"><template #default="{ row }">{{ row.baseline_executions }} → {{ row.candidate_executions }}</template></el-table-column>
          <el-table-column label="基线耗时" width="112" align="right"><template #default="{ row }">{{ formatDuration(row.baseline_duration_ms) }}</template></el-table-column>
          <el-table-column label="候选耗时" width="112" align="right"><template #default="{ row }"><strong>{{ formatDuration(row.candidate_duration_ms) }}</strong></template></el-table-column>
          <el-table-column label="耗时 Δ" width="118" align="right"><template #default="{ row }"><span :class="directionClass(row.duration_direction)">{{ formatSignedDuration(row.duration_delta_ms) }}</span></template></el-table-column>
          <el-table-column label="Token Δ" width="104" align="right"><template #default="{ row }"><span :class="deltaClass(row.token_delta, true)">{{ formatSignedNumber(row.token_delta) }}</span></template></el-table-column>
          <el-table-column label="状态" width="94"><template #default="{ row }"><el-tag :type="changeTagType(row.change_type)" effect="plain">{{ changeTypeLabel(row.change_type) }}</el-tag></template></el-table-column>
        </el-table>
        <div class="mobile-comparison-list">
          <article v-for="span in comparison.spans" :key="span.key" class="comparison-mobile-card">
            <div class="comparison-mobile-head"><div class="comparison-entity"><strong>{{ span.label }}</strong><small>{{ kindLabel(span.kind) }} · {{ span.node }}</small></div><el-tag :type="changeTagType(span.change_type)" effect="plain">{{ changeTypeLabel(span.change_type) }}</el-tag></div>
            <dl><div><dt>耗时</dt><dd>{{ formatDuration(span.baseline_duration_ms) }} → {{ formatDuration(span.candidate_duration_ms) }}</dd></div><div><dt>耗时 Δ</dt><dd :class="directionClass(span.duration_direction)">{{ formatSignedDuration(span.duration_delta_ms) }}</dd></div><div><dt>Token Δ</dt><dd :class="deltaClass(span.token_delta, true)">{{ formatSignedNumber(span.token_delta) }}</dd></div></dl>
          </article>
        </div>
      </section>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { DataAnalysis, Right, Sort } from '@element-plus/icons-vue'
import { computed } from 'vue'
import type {
  TraceComparison,
  TraceComparisonChangeType,
  TraceComparisonDirection,
  TraceComparisonMetric,
  TraceComparisonVerdict,
  TraceRun
} from '../api/types'

const props = defineProps<{
  modelValue: boolean
  runs: TraceRun[]
  baselineId: number | null
  candidateId: number | null
  comparison: TraceComparison | null
  loading: boolean
  error: string
}>()
const emit = defineEmits<{
  'update:baselineId': [value: number | null]
  'update:candidateId': [value: number | null]
  compare: []
  close: []
}>()

const baselineModel = computed({ get: () => props.baselineId, set: (value) => emit('update:baselineId', value) })
const candidateModel = computed({ get: () => props.candidateId, set: (value) => emit('update:candidateId', value) })
const finishedRuns = computed(() => props.runs.filter((run) => Boolean(run.finished_at)))
const selectedBaseline = computed(() => finishedRuns.value.find((run) => run.workflow_id === props.baselineId))
const candidateRuns = computed(() => finishedRuns.value.filter((run) => (
  run.workflow_id !== props.baselineId
  && (!selectedBaseline.value || run.project_id === selectedBaseline.value.project_id)
)))
const selectedCandidate = computed(() => candidateRuns.value.find((run) => run.workflow_id === props.candidateId))
const canCompare = computed(() => Boolean(selectedBaseline.value && selectedCandidate.value && !props.loading))

const statusLabels: Record<string, string> = {
  COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消', COMPENSATION_FAILED: '补偿失败'
}
const roleLabels: Record<string, string> = {
  product_manager: 'AI 产品经理', project_manager: 'AI 项目经理', architect: 'AI 架构师',
  test_engineer: 'AI 测试工程师', meeting_summarizer: 'AI 会议纪要员',
  knowledge_admin: 'AI 知识库管理员', notification_secretary: 'AI 通知秘书',
  operations_analyst: 'AI 运营分析师'
}

function swapRuns() {
  const baseline = props.baselineId
  emit('update:baselineId', props.candidateId)
  emit('update:candidateId', baseline)
}
function runOptionLabel(run: TraceRun) { return `#${run.workflow_id} · ${run.project_name} · ${statusLabel(run.status)} · ${formatDateTime(run.created_at)}` }
function statusLabel(status: string) { return statusLabels[status] || status }
function roleLabel(role: string) { return roleLabels[role] || role || '未归属 Agent' }
function kindLabel(kind: string) { return ({ queue: '排队', node: '节点', branch: '并行分支', wait: '人工等待' } as Record<string, string>)[kind] || kind }
function joinValues(values: string[]) { return values.length ? values.join('、') : '无' }
function formatDateTime(value: string) { return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) }
function formatNumber(value: number) { return new Intl.NumberFormat('zh-CN').format(value) }
function formatDuration(ms: number) {
  if (ms < 1000) return `${Math.max(0, ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} 秒`
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)} 分 ${Math.floor((ms % 60_000) / 1000)} 秒`
  return `${Math.floor(ms / 3_600_000)} 时 ${Math.floor((ms % 3_600_000) / 60_000)} 分`
}
function formatCost(micros: number) { const amount = micros / 1_000_000; return `$${amount.toFixed(amount >= 1 ? 2 : 4)}` }
function formatMetric(value: number, unit: TraceComparisonMetric['unit']) {
  if (unit === 'duration') return formatDuration(value)
  if (unit === 'cost') return formatCost(value)
  return formatNumber(value)
}
function formatMetricDelta(metric: TraceComparisonMetric) {
  const value = metric.unit === 'duration'
    ? formatSignedDuration(metric.delta)
    : metric.unit === 'cost'
      ? formatSignedCost(metric.delta)
      : formatSignedNumber(metric.delta)
  return metric.delta_percent === null || metric.delta_percent === undefined
    ? `Δ ${value}`
    : `Δ ${value} (${metric.delta_percent > 0 ? '+' : ''}${metric.delta_percent.toFixed(1)}%)`
}
function formatSignedNumber(value: number) { return `${value > 0 ? '+' : value < 0 ? '-' : ''}${formatNumber(Math.abs(value))}` }
function formatSignedDuration(value: number) { return `${value > 0 ? '+' : value < 0 ? '-' : ''}${formatDuration(Math.abs(value))}` }
function formatSignedCost(value: number) { return `${value > 0 ? '+' : value < 0 ? '-' : ''}${formatCost(Math.abs(value))}` }
function verdictLabel(verdict: TraceComparisonVerdict) { return ({ IMPROVED: '效率改善', REGRESSED: '效率退化', MIXED: '改善与退化并存', UNCHANGED: '基本稳定' } as Record<string, string>)[verdict] }
function directionLabel(direction: TraceComparisonDirection) { return ({ IMPROVED: '改善', REGRESSED: '退化', CHANGED: '有变化', UNCHANGED: '稳定' } as Record<string, string>)[direction] }
function changeTypeLabel(type: TraceComparisonChangeType) { return ({ ADDED: '新增', REMOVED: '移除', MODIFIED: '已变化', UNCHANGED: '稳定' } as Record<string, string>)[type] }
function directionTagType(direction: TraceComparisonDirection): 'success' | 'danger' | 'warning' | 'info' { if (direction === 'IMPROVED') return 'success'; if (direction === 'REGRESSED') return 'danger'; if (direction === 'CHANGED') return 'warning'; return 'info' }
function changeTagType(type: TraceComparisonChangeType): 'success' | 'danger' | 'warning' | 'info' { if (type === 'ADDED') return 'success'; if (type === 'REMOVED') return 'danger'; if (type === 'MODIFIED') return 'warning'; return 'info' }
function directionClass(direction: TraceComparisonDirection) { return { 'delta-improved': direction === 'IMPROVED', 'delta-regressed': direction === 'REGRESSED', 'delta-changed': direction === 'CHANGED' } }
function deltaClass(value: number, lowerIsBetter: boolean) { return { 'delta-improved': lowerIsBetter ? value < 0 : false, 'delta-regressed': lowerIsBetter ? value > 0 : value > 0, 'delta-neutral': value === 0 } }
</script>

<style scoped>
.comparison-dialog-title span { color: var(--color-muted-text); font-size: 11px; }.comparison-dialog-title h2 { margin: 3px 0 0; font-size: 20px; }
.comparison-picker { display: grid; grid-template-columns: minmax(0, 1fr) 44px minmax(0, 1fr) auto; align-items: end; gap: 10px; padding: 2px 0 16px; }
.comparison-picker label { display: grid; min-width: 0; gap: 6px; color: var(--color-secondary-text); font-size: 12px; font-weight: 650; }.comparison-picker .el-select { width: 100%; }.swap-runs { width: 40px; min-width: 40px; height: 40px; }.start-comparison { min-width: 112px; }
.comparison-scope-alert { margin-bottom: 18px; }.comparison-loading { padding: 18px 0; }.comparison-error { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px; border: 1px solid #fecaca; border-radius: 8px; background: #fef2f2; }.comparison-error strong, .comparison-error span { display: block; }.comparison-error span { margin-top: 3px; color: var(--color-secondary-text); font-size: 12px; }
.comparison-result { min-width: 0; }.comparison-summary { display: grid; grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr) minmax(190px, .8fr); align-items: center; gap: 12px; padding: 15px; border: 1px solid var(--color-border); border-left: 4px solid var(--color-muted-text); border-radius: 8px; background: var(--color-surface); }.comparison-summary.verdict-improved { border-left-color: var(--color-success); }.comparison-summary.verdict-regressed { border-left-color: var(--color-danger); }.comparison-summary.verdict-mixed { border-left-color: var(--color-warning); }.comparison-run-side, .comparison-verdict { min-width: 0; }.comparison-run-side span, .comparison-run-side strong, .comparison-run-side small, .comparison-verdict span, .comparison-verdict strong, .comparison-verdict small { display: block; }.comparison-run-side span, .comparison-verdict span { color: var(--color-muted-text); font-size: 11px; }.comparison-run-side strong, .comparison-verdict strong { margin-top: 4px; font-size: 16px; }.comparison-run-side small, .comparison-verdict small { margin-top: 3px; overflow: hidden; color: var(--color-secondary-text); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.comparison-arrow { color: var(--color-muted-text); }.comparison-verdict { padding-left: 14px; border-left: 1px solid var(--color-border); }
.comparison-section { min-width: 0; margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--color-border); }.comparison-section-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 12px; }.comparison-section-head h3 { margin: 0 0 3px; font-size: 16px; }.comparison-section-head p, .comparison-section-head > span { margin: 0; color: var(--color-muted-text); font-size: 11px; }.comparison-metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }.comparison-metric { min-width: 0; padding: 12px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); }.comparison-metric > div { display: flex; align-items: center; justify-content: space-between; gap: 6px; }.comparison-metric > div > span { color: var(--color-muted-text); font-size: 11px; }.comparison-metric > strong, .comparison-metric > small { display: block; }.comparison-metric > strong { margin-top: 9px; overflow: hidden; font-size: 18px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }.comparison-metric > small { margin-top: 5px; overflow: hidden; color: var(--color-secondary-text); font-size: 10px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.comparison-table { width: 100%; border: 1px solid var(--color-border); border-radius: 8px; }.comparison-entity { min-width: 0; }.comparison-entity strong, .comparison-entity small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.comparison-entity small { margin-top: 2px; color: var(--color-muted-text); font-size: 10px; }.model-change { display: grid; min-width: 0; grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr); align-items: center; gap: 4px; font-size: 11px; }.model-change span, .model-change strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.model-change span { color: var(--color-muted-text); }.model-change .el-icon { color: var(--color-muted-text); }.delta-improved { color: var(--color-success); font-weight: 700; }.delta-regressed { color: var(--color-danger); font-weight: 700; }.delta-changed { color: var(--color-warning); font-weight: 700; }.delta-neutral { color: var(--color-secondary-text); }.mobile-comparison-list { display: none; }
:global(.trace-comparison-dialog .el-dialog__body) { max-height: calc(100vh - 150px); overflow-x: hidden; overflow-y: auto; padding-top: 6px; }

@media (max-width: 900px) { .comparison-picker { grid-template-columns: minmax(0, 1fr) 44px minmax(0, 1fr); }.start-comparison { grid-column: 1 / -1; min-height: 44px; }.comparison-summary { grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr); }.comparison-verdict { grid-column: 1 / -1; padding: 12px 0 0; border-top: 1px solid var(--color-border); border-left: 0; }.comparison-metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.desktop-comparison-table { display: none; }.mobile-comparison-list { display: grid; gap: 8px; }.comparison-mobile-card { min-width: 0; padding: 12px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); }.comparison-mobile-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }.comparison-mobile-card > p { overflow: hidden; margin: 8px 0 0; color: var(--color-secondary-text); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.comparison-mobile-card dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 10px 0 0; padding-top: 9px; border-top: 1px solid var(--color-border); }.comparison-mobile-card dt { color: var(--color-muted-text); font-size: 9px; }.comparison-mobile-card dd { margin: 3px 0 0; overflow: hidden; font-size: 11px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; } }
@media (max-width: 640px) { :global(.trace-comparison-dialog.el-dialog) { width: 100% !important; min-height: 100dvh; margin: 0 !important; border-radius: 0; }.comparison-dialog-title h2 { font-size: 18px; }.comparison-picker { grid-template-columns: minmax(0, 1fr) 44px; }.comparison-picker label:first-child { grid-column: 1; grid-row: 1; }.swap-runs { grid-column: 2; grid-row: 1; width: 44px; min-width: 44px; height: 44px; }.comparison-picker label:nth-of-type(2) { grid-column: 1 / -1; grid-row: 2; }.start-comparison { grid-row: 3; }.comparison-summary { grid-template-columns: minmax(0, 1fr) 18px minmax(0, 1fr); padding: 12px; }.comparison-run-side strong { font-size: 14px; }.comparison-metric-grid { gap: 7px; }.comparison-metric { padding: 10px; }.comparison-metric > strong { overflow: visible; font-size: 16px; white-space: normal; }.comparison-metric > small { white-space: normal; }.comparison-section-head { align-items: flex-start; flex-direction: column; }.comparison-mobile-card dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }:global(.trace-comparison-dialog .el-dialog__headerbtn) { width: 44px; height: 44px; }:global(.trace-comparison-dialog .el-dialog__body) { max-height: calc(100dvh - 70px); padding: 4px 14px 24px; } }
</style>
