<template>
  <section class="trace-health-section" aria-labelledby="trace-health-title">
    <div class="health-section-head">
      <div>
        <h2 id="trace-health-title">SLO 与智能告警</h2>
        <p>当前时间与项目范围 · {{ health?.summary.sample_count ?? 0 }} 个终态样本</p>
      </div>
      <div class="health-head-actions">
        <el-tag v-if="health" :type="healthTagType" effect="plain">{{ healthStatusLabel }}</el-tag>
        <el-button v-if="canManageSettings" :icon="Setting" @click="emit('openSettings')">SLO 设置</el-button>
      </div>
    </div>

    <div v-if="error && !health" class="health-error" role="alert">
      <div><strong>服务等级状态加载失败</strong><span>{{ error }}</span></div>
      <el-button @click="emit('retry')">重新加载</el-button>
    </div>
    <el-alert
      v-else-if="error"
      class="health-refresh-alert"
      type="error"
      :closable="false"
      show-icon
      title="SLO 刷新失败，当前显示上次结果"
      :description="error"
    />
    <div v-if="loading && !health" class="health-loading" aria-label="正在计算服务等级状态">
      <el-skeleton :rows="5" animated />
    </div>

    <template v-else-if="health">
      <div class="health-metric-grid">
        <article class="health-state-card" :class="`health-${health.summary.status.toLowerCase()}`">
          <span>服务等级状态</span>
          <strong>{{ healthStatusLabel }}</strong>
          <small v-if="health.summary.status === 'INSUFFICIENT_DATA'">至少需要 {{ health.targets.minimum_sample_runs }} 个终态样本</small>
          <small v-else>{{ health.summary.compliant_metric_count }} 项达标 · {{ health.summary.breached_metric_count }} 项违约</small>
        </article>
        <article
          v-for="metric in health.metrics"
          :key="metric.key"
          class="health-metric-card"
          :class="{ 'metric-breached': !metric.compliant && health.summary.status !== 'INSUFFICIENT_DATA' }"
        >
          <div>
            <span>{{ metric.label }}</span>
            <el-tag size="small" :type="metricTagType(metric.compliant)" effect="plain">{{ metricStateLabel(metric.compliant) }}</el-tag>
          </div>
          <strong>{{ formatMetric(metric.actual, metric.unit) }}</strong>
          <small>{{ targetLabel(metric) }}</small>
        </article>
        <article class="error-budget-card">
          <div><span>错误预算剩余</span><strong>{{ health.summary.error_budget_remaining_percent.toFixed(1) }}%</strong></div>
          <el-progress :percentage="health.summary.error_budget_remaining_percent" :stroke-width="7" :show-text="false" />
          <small>允许 {{ formatDecimal(health.summary.error_budget_allowed_failures) }} 次 · 已消耗 {{ health.summary.error_budget_consumed_failures }} 次</small>
        </article>
      </div>

      <div class="anomaly-head">
        <div><h3>异常运行</h3><p>失败、SLO 超限及历史基线偏离。</p></div>
        <span>{{ health.anomalies.length }} 条</span>
      </div>
      <el-empty v-if="!health.anomalies.length" description="当前范围内未检测到异常运行" :image-size="64" />
      <template v-else>
        <el-table :data="health.anomalies" class="health-table health-desktop-table" table-layout="fixed" row-key="workflow_id">
          <el-table-column label="运行" width="90">
            <template #default="{ row }"><button class="health-run-link" @click="emit('openRun', row.workflow_id)">#{{ row.workflow_id }}</button></template>
          </el-table-column>
          <el-table-column label="项目" min-width="170">
            <template #default="{ row }"><strong class="project-name">{{ row.project_name }}</strong></template>
          </el-table-column>
          <el-table-column label="级别" width="92">
            <template #default="{ row }"><el-tag :type="row.severity === 'CRITICAL' ? 'danger' : 'warning'" effect="plain">{{ severityLabel(row.severity) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="异常信号" min-width="250">
            <template #default="{ row }"><div class="signal-list"><span v-for="signal in row.signals" :key="signal">{{ signal }}</span></div></template>
          </el-table-column>
          <el-table-column label="耗时" width="112" align="right">
            <template #default="{ row }"><span class="number-cell">{{ formatDuration(row.duration_ms) }}</span></template>
          </el-table-column>
          <el-table-column label="成本" width="104" align="right">
            <template #default="{ row }"><span class="number-cell">{{ formatCost(row.total_cost_micros) }}</span></template>
          </el-table-column>
          <el-table-column label="检测时间" width="150">
            <template #default="{ row }"><span class="date-cell">{{ formatDateTime(row.detected_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="88" fixed="right">
            <template #default="{ row }"><el-button link type="primary" :icon="View" @click="emit('openRun', row.workflow_id)">查看</el-button></template>
          </el-table-column>
        </el-table>
        <div class="health-mobile-list" aria-label="异常运行列表">
          <article v-for="item in health.anomalies" :key="item.workflow_id" class="health-mobile-card">
            <button class="health-mobile-trigger" @click="emit('openRun', item.workflow_id)">
              <span><strong>#{{ item.workflow_id }} · {{ item.project_name }}</strong><small>{{ formatDateTime(item.detected_at) }}</small></span>
              <el-tag :type="item.severity === 'CRITICAL' ? 'danger' : 'warning'" effect="plain">{{ severityLabel(item.severity) }}</el-tag>
            </button>
            <p>{{ item.signals.join(' · ') }}</p>
            <dl><div><dt>耗时</dt><dd>{{ formatDuration(item.duration_ms) }}</dd></div><div><dt>成本</dt><dd>{{ formatCost(item.total_cost_micros) }}</dd></div></dl>
          </article>
        </div>
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
import { Setting, View } from '@element-plus/icons-vue'
import { computed } from 'vue'
import type { TraceHealth, TraceSLOMetric } from '../api/types'

const props = defineProps<{
  health: TraceHealth | null
  loading: boolean
  error: string
  canManageSettings: boolean
}>()
const emit = defineEmits<{
  retry: []
  openRun: [workflowId: number]
  openSettings: []
}>()

const healthStatusLabel = computed(() => ({
  HEALTHY: '健康', AT_RISK: '存在风险', BREACHED: 'SLO 违约', INSUFFICIENT_DATA: '样本积累中'
}[props.health?.summary.status || 'INSUFFICIENT_DATA']))
const healthTagType = computed<'success' | 'warning' | 'danger' | 'info'>(() => ({
  HEALTHY: 'success', AT_RISK: 'warning', BREACHED: 'danger', INSUFFICIENT_DATA: 'info'
}[props.health?.summary.status || 'INSUFFICIENT_DATA'] as 'success' | 'warning' | 'danger' | 'info'))

function metricTagType(compliant: boolean): 'success' | 'danger' | 'info' {
  if (props.health?.summary.status === 'INSUFFICIENT_DATA') return 'info'
  return compliant ? 'success' : 'danger'
}
function metricStateLabel(compliant: boolean) {
  if (props.health?.summary.status === 'INSUFFICIENT_DATA') return '待观察'
  return compliant ? '达标' : '违约'
}
function formatDecimal(value: number) { return Number.isInteger(value) ? String(value) : value.toFixed(1) }
function formatCost(micros: number) { const amount = micros / 1_000_000; return `$${amount.toFixed(amount >= 1 ? 2 : 4)}` }
function formatDuration(ms: number) {
  if (ms < 1000) return `${Math.max(0, ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} 秒`
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)} 分 ${Math.floor((ms % 60_000) / 1000)} 秒`
  return `${Math.floor(ms / 3_600_000)} 时 ${Math.floor((ms % 3_600_000) / 60_000)} 分`
}
function formatMetric(value: number, unit: TraceSLOMetric['unit']) {
  if (unit === 'percent') return `${value.toFixed(1)}%`
  if (unit === 'duration') return formatDuration(value)
  return formatCost(value)
}
function targetLabel(metric: TraceSLOMetric) {
  const direction = metric.unit === 'percent' ? '≥' : '≤'
  return `目标 ${direction} ${formatMetric(metric.target, metric.unit)}`
}
function severityLabel(severity: string) { return severity === 'CRITICAL' ? '严重' : '警告' }
function formatDateTime(value: string) { return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) }
</script>

<style scoped>
.trace-health-section { min-width: 0; padding: 24px 0; border-top: 1px solid var(--color-border); }
.health-section-head, .anomaly-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.health-section-head h2, .anomaly-head h3 { margin: 0 0 4px; font-size: 17px; }.anomaly-head h3 { font-size: 16px; }
.health-section-head p, .anomaly-head p, .anomaly-head > span { margin: 0; color: var(--color-muted-text); font-size: 12px; }.anomaly-head > span { white-space: nowrap; }
.health-head-actions { display: flex; align-items: center; gap: 8px; }.health-head-actions .el-button { min-height: 40px; }
.health-loading { padding: 20px 0; }.health-refresh-alert { margin-bottom: 14px; }
.health-error { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px; border: 1px solid #fecaca; border-radius: 8px; background: #fef2f2; }.health-error strong, .health-error span { display: block; }.health-error span { margin-top: 3px; color: var(--color-secondary-text); font-size: 12px; }
.health-metric-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
.health-state-card, .health-metric-card, .error-budget-card { min-width: 0; min-height: 116px; padding: 13px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); }
.health-state-card { border-left: 4px solid var(--color-muted-text); }.health-state-card.health-healthy { border-left-color: var(--color-success); }.health-state-card.health-at_risk { border-left-color: var(--color-warning); }.health-state-card.health-breached { border-left-color: var(--color-danger); }.health-metric-card.metric-breached { border-color: #fecaca; }
.health-state-card span, .health-state-card strong, .health-state-card small, .health-metric-card > strong, .health-metric-card > small, .error-budget-card small { display: block; }.health-state-card span, .health-metric-card > div > span, .error-budget-card span { color: var(--color-muted-text); font-size: 11px; }.health-state-card strong { margin-top: 11px; font-size: 18px; }.health-state-card small, .health-metric-card > small, .error-budget-card small { margin-top: 6px; overflow: hidden; color: var(--color-secondary-text); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.health-metric-card > div, .error-budget-card > div { display: flex; align-items: center; justify-content: space-between; gap: 6px; }.health-metric-card > strong { margin-top: 12px; overflow: hidden; font-size: 18px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }.error-budget-card > div strong { font-size: 16px; font-variant-numeric: tabular-nums; }.error-budget-card .el-progress { margin-top: 19px; }
.anomaly-head { margin-top: 22px; }.health-table { width: 100%; border: 1px solid var(--color-border); border-radius: 8px; }.health-run-link { min-width: 44px; min-height: 40px; padding: 0; border: 0; background: transparent; color: var(--color-primary); font: inherit; font-weight: 750; text-align: left; cursor: pointer; }.health-run-link:hover { text-decoration: underline; }.project-name, .date-cell { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.signal-list { display: flex; min-width: 0; flex-wrap: wrap; gap: 4px; }.signal-list span { padding: 3px 6px; border: 1px solid #fde68a; border-radius: 4px; background: #fffbeb; color: #92400e; font-size: 10px; }.number-cell { font-variant-numeric: tabular-nums; }.date-cell { color: var(--color-secondary-text); font-size: 11px; }.health-mobile-list { display: none; }
@media (max-width: 1180px) { .health-metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.error-budget-card { grid-column: span 2; } }
@media (max-width: 820px) { .health-desktop-table { display: none; }.health-mobile-list { display: grid; gap: 8px; }.health-mobile-card { min-width: 0; padding: 12px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); }.health-mobile-trigger { display: flex; width: 100%; min-height: 44px; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 0; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }.health-mobile-trigger > span { min-width: 0; }.health-mobile-trigger strong, .health-mobile-trigger small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.health-mobile-trigger small { margin-top: 3px; color: var(--color-muted-text); font-size: 10px; }.health-mobile-card > p { margin: 9px 0; color: var(--color-secondary-text); font-size: 11px; }.health-mobile-card dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; padding-top: 9px; border-top: 1px solid var(--color-border); }.health-mobile-card dt { color: var(--color-muted-text); font-size: 9px; }.health-mobile-card dd { margin: 3px 0 0; font-size: 11px; font-variant-numeric: tabular-nums; } }
@media (max-width: 640px) { .health-section-head, .anomaly-head { align-items: flex-start; flex-direction: column; }.health-head-actions { width: 100%; justify-content: space-between; }.health-head-actions .el-button { min-height: 44px; }.health-metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.health-state-card, .error-budget-card { grid-column: 1 / -1; }.health-state-card, .health-metric-card, .error-budget-card { min-height: 108px; }.health-metric-card > strong { overflow: visible; font-size: 16px; white-space: normal; }.health-state-card small, .health-metric-card > small, .error-budget-card small { white-space: normal; } }
</style>
