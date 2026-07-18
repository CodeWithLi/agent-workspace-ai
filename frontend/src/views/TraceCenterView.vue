<template>
  <section class="trace-page" aria-labelledby="trace-page-title">
    <header class="trace-head">
      <div>
        <span class="trace-eyebrow">多 Agent 可观测性</span>
        <h1 id="trace-page-title">Agent 运行追踪</h1>
        <p>查看工作流吞吐、模型消耗、节点瓶颈和单次运行时间线。</p>
      </div>
      <div class="trace-toolbar" aria-label="追踪筛选">
        <el-radio-group v-model="days" class="window-switch" aria-label="统计时间范围">
          <el-radio-button v-for="option in dayOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </el-radio-button>
        </el-radio-group>
        <el-select v-model="projectId" class="project-filter" clearable placeholder="全部项目" aria-label="按项目筛选">
          <el-option
            v-for="project in overview?.projects || []"
            :key="project.project_id"
            :label="project.project_name"
            :value="project.project_id"
          />
        </el-select>
        <el-select v-model="statusFilter" class="status-filter" clearable placeholder="全部状态" aria-label="按运行状态筛选">
          <el-option
            v-for="option in statusOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-button
          class="compare-command"
          :icon="DataAnalysis"
          :disabled="!hasComparableRuns"
          :title="hasComparableRuns ? '对比两次已结束运行' : '当前筛选范围内至少需要两次同项目已结束运行'"
          @click="openComparison"
        >对比运行</el-button>
        <el-button
          class="refresh-command"
          :icon="Refresh"
          circle
          :loading="loading || healthLoading"
          aria-label="刷新运行追踪"
          title="刷新运行追踪"
          @click="refreshAll"
        />
      </div>
    </header>

    <div v-if="overviewError && !overview" class="trace-error" role="alert">
      <div>
        <strong>运行追踪加载失败</strong>
        <span>{{ overviewError }}</span>
      </div>
      <el-button @click="loadOverview">重新加载</el-button>
    </div>

    <div v-if="loading && !overview" class="trace-loading" aria-label="正在加载运行追踪">
      <el-skeleton :rows="8" animated />
    </div>

    <template v-else-if="overview">
      <el-alert
        v-if="overviewError"
        class="refresh-alert"
        type="error"
        :closable="false"
        show-icon
        title="刷新失败，当前显示上次加载的数据"
        :description="overviewError"
      />
      <el-alert
        v-if="overview.window.analysis_truncated"
        class="sample-alert"
        type="warning"
        :closable="false"
        show-icon
        title="分析样本已截断"
        description="总运行数、状态、Token 与成本为完整数据库聚合；P95、Agent 分布和节点瓶颈基于最近样本。"
      />

      <section class="metric-section" aria-labelledby="trace-metrics-title">
        <h2 id="trace-metrics-title" class="sr-only">运行关键指标</h2>
        <div class="metric-grid">
          <article class="metric-card">
            <span>工作流运行</span>
            <strong>{{ formatNumber(overview.metrics.total_runs) }}</strong>
            <small>{{ formatNumber(overview.metrics.active_runs) }} 个正在处理</small>
          </article>
          <article class="metric-card">
            <span>成功率</span>
            <strong>{{ overview.metrics.success_rate.toFixed(1) }}%</strong>
            <small>{{ formatNumber(overview.metrics.completed_runs) }} 成功 · {{ formatNumber(overview.metrics.failed_runs) }} 失败</small>
          </article>
          <article class="metric-card">
            <span>P95 端到端时延</span>
            <strong>{{ formatDuration(overview.metrics.p95_duration_ms) }}</strong>
            <small>平均 {{ formatDuration(overview.metrics.average_duration_ms) }}</small>
          </article>
          <article class="metric-card">
            <span>Token 消耗</span>
            <strong :title="formatNumber(overview.metrics.total_tokens)">{{ formatCompact(overview.metrics.total_tokens) }}</strong>
            <small>{{ formatNumber(overview.metrics.total_llm_calls) }} 次模型调用</small>
          </article>
          <article class="metric-card">
            <span>预估模型成本</span>
            <strong>{{ formatCost(overview.metrics.total_cost_micros) }}</strong>
            <small>按提供商用量记录估算</small>
          </article>
        </div>
        <div class="status-strip" aria-label="运行状态分布">
          <span v-for="item in visibleStatuses" :key="item.status">
            <i :class="`status-dot status-${item.status.toLowerCase()}`" aria-hidden="true" />
            {{ statusLabel(item.status) }}
            <strong>{{ formatNumber(item.count) }}</strong>
          </span>
        </div>
      </section>

      <TraceHealthPanel
        :health="health"
        :loading="healthLoading"
        :error="healthError"
        :can-manage-settings="auth.user?.role === 'admin'"
        @retry="loadHealth"
        @open-run="openTrace"
        @open-settings="router.push('/settings')"
      />

      <section class="trace-section trend-section" aria-labelledby="trace-trend-title">
        <div class="section-head">
          <div>
            <h2 id="trace-trend-title">运行与消耗趋势</h2>
            <p>{{ formatDate(overview.window.start_at) }} 至 {{ formatDate(overview.window.end_at) }}</p>
          </div>
          <div class="chart-legend" aria-label="趋势汇总">
            <span><i class="legend-completed" />完成 {{ formatNumber(trendTotals.completed) }}</span>
            <span><i class="legend-failed" />失败 {{ formatNumber(trendTotals.failed) }}</span>
            <span><i class="legend-token" />Token {{ formatCompact(trendTotals.tokens) }}</span>
          </div>
        </div>
        <div
          ref="chartElement"
          class="trend-chart"
          role="img"
          :aria-label="trendAriaLabel"
        />
      </section>

      <section class="trace-section" aria-labelledby="agent-performance-title">
        <div class="section-head">
          <div>
            <h2 id="agent-performance-title">Agent 性能</h2>
            <p>模型调用、Token、成本和延迟按 Agent 汇总。</p>
          </div>
          <span class="section-count">{{ overview.agents.length }} 个 Agent</span>
        </div>
        <el-empty v-if="!overview.agents.length" description="当前筛选范围内没有模型调用" :image-size="64" />
        <template v-else>
          <el-table :data="overview.agents" class="trace-table desktop-table" table-layout="fixed">
            <el-table-column label="Agent" min-width="190">
              <template #default="{ row }">
                <div class="entity-cell">
                  <span class="agent-mark">{{ row.agent_name.slice(0, 1) }}</span>
                  <div><strong>{{ row.agent_name }}</strong><small>{{ roleLabel(row.agent_role) }}</small></div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="模型" min-width="170">
              <template #default="{ row }">
                <strong class="model-name">{{ row.models.join('、') || '未记录' }}</strong>
                <small class="provider-name">{{ row.providers.join('、') || '未记录' }}</small>
              </template>
            </el-table-column>
            <el-table-column prop="workflow_count" label="工作流" width="82" align="right" />
            <el-table-column prop="call_count" label="调用" width="72" align="right" />
            <el-table-column label="Token" width="104" align="right">
              <template #default="{ row }"><span class="number-cell">{{ formatCompact(row.total_tokens) }}</span></template>
            </el-table-column>
            <el-table-column label="成本" width="104" align="right">
              <template #default="{ row }"><span class="number-cell">{{ formatCost(row.total_cost_micros) }}</span></template>
            </el-table-column>
            <el-table-column label="平均延迟" width="108" align="right">
              <template #default="{ row }"><span class="number-cell">{{ formatDuration(row.average_latency_ms) }}</span></template>
            </el-table-column>
            <el-table-column label="P95 延迟" width="108" align="right">
              <template #default="{ row }"><strong class="number-cell">{{ formatDuration(row.p95_latency_ms) }}</strong></template>
            </el-table-column>
          </el-table>
          <div class="mobile-card-list" aria-label="Agent 性能列表">
            <article v-for="agent in overview.agents" :key="agent.agent_id ?? agent.agent_name" class="mobile-data-card">
              <div class="mobile-card-head">
                <div class="entity-cell">
                  <span class="agent-mark">{{ agent.agent_name.slice(0, 1) }}</span>
                  <div><strong>{{ agent.agent_name }}</strong><small>{{ roleLabel(agent.agent_role) }}</small></div>
                </div>
                <strong>{{ formatDuration(agent.p95_latency_ms) }}</strong>
              </div>
              <p>{{ agent.providers.join('、') || '未记录' }} · {{ agent.models.join('、') || '未记录模型' }}</p>
              <dl>
                <div><dt>调用</dt><dd>{{ formatNumber(agent.call_count) }}</dd></div>
                <div><dt>Token</dt><dd>{{ formatCompact(agent.total_tokens) }}</dd></div>
                <div><dt>成本</dt><dd>{{ formatCost(agent.total_cost_micros) }}</dd></div>
              </dl>
            </article>
          </div>
        </template>
      </section>

      <section class="trace-section" aria-labelledby="bottleneck-title">
        <div class="section-head">
          <div>
            <h2 id="bottleneck-title">节点瓶颈</h2>
            <p>按完成节点的 P95 耗时排序，并显示计算时间占比。</p>
          </div>
        </div>
        <el-empty v-if="!overview.bottlenecks.length" description="暂无可分析的已完成节点" :image-size="64" />
        <template v-else>
          <el-table :data="overview.bottlenecks" class="trace-table desktop-table" table-layout="fixed">
            <el-table-column label="节点 / 分支" min-width="220">
              <template #default="{ row }">
                <div class="node-cell"><strong>{{ row.label }}</strong><small>{{ kindLabel(row.kind) }} · {{ row.node }}</small></div>
              </template>
            </el-table-column>
            <el-table-column prop="execution_count" label="执行" width="76" align="right" />
            <el-table-column label="平均耗时" width="112" align="right">
              <template #default="{ row }"><span class="number-cell">{{ formatDuration(row.average_duration_ms) }}</span></template>
            </el-table-column>
            <el-table-column label="P95" width="112" align="right">
              <template #default="{ row }"><strong class="number-cell">{{ formatDuration(row.p95_duration_ms) }}</strong></template>
            </el-table-column>
            <el-table-column label="最大耗时" width="112" align="right">
              <template #default="{ row }"><span class="number-cell">{{ formatDuration(row.max_duration_ms) }}</span></template>
            </el-table-column>
            <el-table-column label="计算占比" min-width="170">
              <template #default="{ row }">
                <div class="share-cell"><el-progress :percentage="row.compute_share_percent" :stroke-width="6" :show-text="false" /><strong>{{ row.compute_share_percent.toFixed(1) }}%</strong></div>
              </template>
            </el-table-column>
          </el-table>
          <div class="mobile-card-list" aria-label="节点瓶颈列表">
            <article v-for="node in overview.bottlenecks" :key="node.key" class="mobile-data-card">
              <div class="mobile-card-head"><div class="node-cell"><strong>{{ node.label }}</strong><small>{{ kindLabel(node.kind) }}</small></div><strong>{{ formatDuration(node.p95_duration_ms) }}</strong></div>
              <dl>
                <div><dt>执行</dt><dd>{{ node.execution_count }}</dd></div>
                <div><dt>平均</dt><dd>{{ formatDuration(node.average_duration_ms) }}</dd></div>
                <div><dt>占比</dt><dd>{{ node.compute_share_percent.toFixed(1) }}%</dd></div>
              </dl>
            </article>
          </div>
        </template>
      </section>

      <section class="trace-section" aria-labelledby="recent-runs-title">
        <div class="section-head">
          <div>
            <h2 id="recent-runs-title">最近运行</h2>
            <p>点击任意运行查看节点时间线、模型调用和事件日志。</p>
          </div>
          <span class="section-count">最多显示 100 条</span>
        </div>
        <el-empty v-if="!overview.recent_runs.length" description="当前筛选范围内暂无工作流运行" :image-size="64" />
        <template v-else>
          <el-table :data="overview.recent_runs" class="trace-table desktop-table" table-layout="fixed" row-key="workflow_id">
            <el-table-column label="运行" width="100">
              <template #default="{ row }"><button class="trace-link" @click="openTrace(row.workflow_id)">#{{ row.workflow_id }}</button></template>
            </el-table-column>
            <el-table-column label="项目 / 发起人" min-width="190">
              <template #default="{ row }"><div class="node-cell"><strong>{{ row.project_name }}</strong><small>{{ row.owner_name }}</small></div></template>
            </el-table-column>
            <el-table-column label="状态" width="126">
              <template #default="{ row }"><el-tag :type="statusTagType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="当前节点" min-width="138">
              <template #default="{ row }">{{ nodeLabel(row.current_node) }}</template>
            </el-table-column>
            <el-table-column label="总耗时" width="104" align="right">
              <template #default="{ row }"><span class="number-cell">{{ formatDuration(row.duration_ms) }}</span></template>
            </el-table-column>
            <el-table-column label="Token" width="96" align="right">
              <template #default="{ row }"><span class="number-cell">{{ formatCompact(row.total_tokens) }}</span></template>
            </el-table-column>
            <el-table-column label="创建时间" width="150">
              <template #default="{ row }"><span class="date-cell">{{ formatDateTime(row.created_at) }}</span></template>
            </el-table-column>
            <el-table-column label="操作" width="96" fixed="right">
              <template #default="{ row }"><el-button link type="primary" :icon="View" @click="openTrace(row.workflow_id)">查看</el-button></template>
            </el-table-column>
          </el-table>
          <div class="mobile-card-list" aria-label="最近运行列表">
            <article v-for="run in overview.recent_runs" :key="run.workflow_id" class="mobile-data-card run-card">
              <button class="run-card-button" @click="openTrace(run.workflow_id)">
                <span><strong :title="`#${run.workflow_id} · ${run.project_name}`">#{{ run.workflow_id }} · {{ run.project_name }}</strong><small>{{ run.owner_name }} · {{ formatDateTime(run.created_at) }}</small></span>
                <el-tag :type="statusTagType(run.status)" effect="plain">{{ statusLabel(run.status) }}</el-tag>
              </button>
              <dl>
                <div><dt>节点</dt><dd>{{ nodeLabel(run.current_node) }}</dd></div>
                <div><dt>耗时</dt><dd>{{ formatDuration(run.duration_ms) }}</dd></div>
                <div><dt>Token</dt><dd>{{ formatCompact(run.total_tokens) }}</dd></div>
              </dl>
            </article>
          </div>
        </template>
      </section>
    </template>

    <el-drawer
      :model-value="Boolean(selectedRunId)"
      class="trace-detail-drawer"
      size="min(920px, 100%)"
      :with-header="false"
      destroy-on-close
      @close="closeTrace"
    >
      <div class="drawer-head">
        <div>
          <span>工作流运行追踪</span>
          <div><h2 :title="detail ? `#${detail.run.workflow_id} · ${detail.run.project_name}` : undefined">{{ detail ? `#${detail.run.workflow_id} · ${detail.run.project_name}` : `#${selectedRunId || ''}` }}</h2><el-tag v-if="detail" :type="statusTagType(detail.run.status)" effect="plain">{{ statusLabel(detail.run.status) }}</el-tag></div>
        </div>
        <el-button :icon="Close" circle aria-label="关闭运行追踪" title="关闭" @click="closeTrace" />
      </div>

      <div v-if="detailLoading" class="drawer-loading" aria-label="正在加载运行详情"><el-skeleton :rows="10" animated /></div>
      <div v-else-if="detailError" class="trace-error" role="alert">
        <div><strong>运行详情加载失败</strong><span>{{ detailError }}</span></div>
        <el-button @click="selectedRunId && loadDetail(selectedRunId)">重试</el-button>
      </div>
      <div v-else-if="detail" class="trace-detail">
        <div class="detail-metrics" aria-label="运行耗时分解">
          <div><span>总耗时</span><strong>{{ formatDuration(detail.metrics.total_duration_ms) }}</strong></div>
          <div><span>排队</span><strong>{{ formatDuration(detail.metrics.queue_ms) }}</strong></div>
          <div><span>Agent 计算</span><strong>{{ formatDuration(detail.metrics.active_compute_ms) }}</strong></div>
          <div><span>人工等待</span><strong>{{ formatDuration(detail.metrics.human_wait_ms) }}</strong></div>
          <div><span>协调开销</span><strong>{{ formatDuration(detail.metrics.coordination_ms) }}</strong></div>
          <div><span>模型调用</span><strong>{{ formatNumber(detail.metrics.total_llm_calls) }}</strong></div>
        </div>

        <section class="detail-section" aria-labelledby="span-timeline-title">
          <div class="section-head"><div><h3 id="span-timeline-title">执行时间线</h3><p>分支按 Agent 角色归属模型用量，避免并行节点重复计费。</p></div></div>
          <el-empty v-if="!detail.spans.length" description="暂无可配对的执行阶段" :image-size="56" />
          <div v-else class="span-list">
            <article v-for="span in detail.spans" :key="span.span_id" class="span-row" :class="{ critical: span.span_id === detail.metrics.critical_span_id }">
              <div class="span-copy">
                <span class="span-kind" :class="`span-kind-${span.kind}`">{{ kindLabel(span.kind) }}</span>
                <div><strong>{{ span.label }}</strong><small>{{ span.agent_name || nodeLabel(span.node) }}<template v-if="span.attempt > 1"> · 第 {{ span.attempt }} 次</template></small></div>
              </div>
              <div class="span-track" aria-hidden="true"><i :class="`span-bar span-bar-${span.kind}`" :style="spanStyle(span)" /></div>
              <div class="span-numbers">
                <strong>{{ formatDuration(span.duration_ms) }}</strong>
                <small>{{ formatCompact(span.total_tokens) }} Token · {{ span.llm_call_count }} 调用</small>
              </div>
            </article>
          </div>
        </section>

        <section class="detail-section" aria-labelledby="model-calls-title">
          <div class="section-head"><div><h3 id="model-calls-title">模型调用</h3><p>{{ formatCompact(detail.metrics.total_tokens) }} Token · {{ formatCost(detail.metrics.total_cost_micros) }}</p></div></div>
          <el-empty v-if="!detail.model_calls.length" description="该运行没有模型用量记录" :image-size="56" />
          <template v-else>
            <el-table :data="detail.model_calls" class="trace-table desktop-table" table-layout="fixed">
              <el-table-column label="Agent" min-width="160"><template #default="{ row }"><div class="node-cell"><strong>{{ row.agent_name }}</strong><small>{{ roleLabel(row.agent_role) }}</small></div></template></el-table-column>
              <el-table-column label="提供商 / 模型" min-width="180"><template #default="{ row }"><div class="node-cell"><strong>{{ row.model }}</strong><small>{{ row.provider }} · {{ row.usage_source }}</small></div></template></el-table-column>
              <el-table-column label="Token" width="90" align="right"><template #default="{ row }"><span class="number-cell">{{ formatNumber(row.total_tokens) }}</span></template></el-table-column>
              <el-table-column label="成本" width="100" align="right"><template #default="{ row }"><span class="number-cell">{{ formatCost(row.estimated_cost_micros) }}</span></template></el-table-column>
              <el-table-column label="延迟" width="94" align="right"><template #default="{ row }"><strong class="number-cell">{{ formatDuration(row.latency_ms) }}</strong></template></el-table-column>
              <el-table-column label="时间" width="132"><template #default="{ row }"><span class="date-cell">{{ formatTime(row.created_at) }}</span></template></el-table-column>
            </el-table>
            <div class="mobile-card-list">
              <article v-for="call in detail.model_calls" :key="call.id" class="mobile-data-card">
                <div class="mobile-card-head"><div class="node-cell"><strong>{{ call.agent_name }}</strong><small>{{ call.provider }} · {{ call.model }}</small></div><strong>{{ formatDuration(call.latency_ms) }}</strong></div>
                <dl><div><dt>输入</dt><dd>{{ formatNumber(call.input_tokens) }}</dd></div><div><dt>输出</dt><dd>{{ formatNumber(call.output_tokens) }}</dd></div><div><dt>成本</dt><dd>{{ formatCost(call.estimated_cost_micros) }}</dd></div></dl>
              </article>
            </div>
          </template>
        </section>

        <section class="detail-section event-section" aria-labelledby="event-log-title">
          <div class="section-head"><div><h3 id="event-log-title">事件日志</h3><p>仅显示运行元数据，不包含 Prompt 或产物正文。</p></div><span class="section-count">{{ detail.events.length }} 条</span></div>
          <ol class="event-list">
            <li v-for="event in detail.events" :key="event.id">
              <time :datetime="event.created_at">{{ formatTime(event.created_at) }}</time>
              <span class="event-marker" aria-hidden="true" />
              <div><strong>{{ eventTypeLabel(event.event_type) }} · {{ nodeLabel(event.node) }}</strong><p>{{ event.message }}</p><code v-if="formatPayload(event.payload)">{{ formatPayload(event.payload) }}</code></div>
            </li>
          </ol>
        </section>
      </div>
    </el-drawer>

    <TraceComparisonDialog
      :model-value="comparisonDialogOpen"
      :runs="comparisonRunOptions"
      :baseline-id="compareBaselineId"
      :candidate-id="compareCandidateId"
      :comparison="comparison"
      :loading="comparisonLoading"
      :error="comparisonError"
      @update:baseline-id="compareBaselineId = $event"
      @update:candidate-id="compareCandidateId = $event"
      @compare="submitComparison"
      @close="closeComparison"
    />
  </section>
</template>

<script setup lang="ts">
import { Close, DataAnalysis, Refresh, View } from '@element-plus/icons-vue'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, getApiErrorMessage } from '../api/client'
import type { TraceComparison, TraceDetail, TraceHealth, TraceOverview, TraceRun, TraceSpan, WorkflowTraceStatus } from '../api/types'
import TraceComparisonDialog from '../components/TraceComparisonDialog.vue'
import TraceHealthPanel from '../components/TraceHealthPanel.vue'
import { renderTraceTrendChart, type TraceTrendChart } from '../lib/traceChart'
import { useAuthStore } from '../stores/auth'

const dayOptions = [
  { label: '24 小时', value: 1 },
  { label: '7 天', value: 7 },
  { label: '30 天', value: 30 }
]
const statusOptions: Array<{ label: string; value: WorkflowTraceStatus }> = [
  { label: '排队中', value: 'QUEUED' },
  { label: '运行中', value: 'RUNNING' },
  { label: '等待人工确认', value: 'PAUSED' },
  { label: '已完成', value: 'COMPLETED' },
  { label: '失败', value: 'FAILED' },
  { label: '补偿失败', value: 'COMPENSATION_FAILED' },
  { label: '已取消', value: 'CANCELLED' }
]
const statusLabels: Record<string, string> = {
  QUEUED: '排队中', RUNNING: '运行中', CANCELLING: '取消中', COMPENSATING: '补偿中',
  COMPENSATION_FAILED: '补偿失败', CANCELLED: '已取消', PAUSED: '等待人工确认',
  COMPLETED: '已完成', FAILED: '失败'
}
const nodeLabels: Record<string, string> = {
  queue: '排队', requirement: '需求分析', product: '产品方案', architect: '架构设计',
  planning: '动态规划', specialists: '专业分支', quality_gate: '质量门禁',
  quality_review: '人工修订', project_manager: '项目计划', tester: '测试方案',
  report: '项目报告', completed: '完成'
}
const roleLabels: Record<string, string> = {
  product_manager: 'AI 产品经理', project_manager: 'AI 项目经理', architect: 'AI 架构师',
  test_engineer: 'AI 测试工程师', meeting_summarizer: 'AI 会议纪要员',
  knowledge_admin: 'AI 知识库管理员', notification_secretary: 'AI 通知秘书',
  operations_analyst: 'AI 运营分析师'
}
const eventLabels: Record<string, string> = {
  QUEUED: '进入队列', STARTED: '开始运行', CONTINUED: '继续运行', NODE_STARTED: '节点开始',
  NODE_COMPLETED: '节点完成', BRANCH_STARTED: '分支开始', BRANCH_COMPLETED: '分支完成',
  PLAN_CREATED: '计划已生成', QUALITY_GATE_PASSED: '质量门禁通过',
  QUALITY_GATE_FAILED: '质量门禁未通过', REVISION_REQUESTED: '请求修订', PAUSED: '等待人工确认',
  CANCEL_REQUESTED: '请求取消', CANCELLED: '已取消', COMPLETED: '运行完成', FAILED: '运行失败'
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const days = ref(7)
const projectId = ref<number | ''>('')
const statusFilter = ref<WorkflowTraceStatus | ''>('')
const loading = ref(false)
const overviewError = ref('')
const overview = ref<TraceOverview | null>(null)
const health = ref<TraceHealth | null>(null)
const healthLoading = ref(false)
const healthError = ref('')
const chartElement = ref<HTMLDivElement | null>(null)
const detail = ref<TraceDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const comparisonDialogOpen = ref(false)
const compareBaselineId = ref<number | null>(null)
const compareCandidateId = ref<number | null>(null)
const comparison = ref<TraceComparison | null>(null)
const comparisonLoading = ref(false)
const comparisonError = ref('')
let overviewRequest = 0
let healthRequest = 0
let detailRequest = 0
let comparisonRequest = 0
let chart: TraceTrendChart | null = null
let chartObserver: ResizeObserver | null = null

const selectedRunId = computed(() => {
  const raw = Array.isArray(route.query.run) ? route.query.run[0] : route.query.run
  const value = Number(raw)
  return Number.isInteger(value) && value > 0 ? value : null
})
const comparisonQuery = computed(() => ({
  baselineId: positiveQueryId(route.query.baseline),
  candidateId: positiveQueryId(route.query.candidate)
}))
const comparisonRunOptions = computed(() => {
  const rows = new Map<number, TraceRun>()
  for (const run of overview.value?.recent_runs || []) rows.set(run.workflow_id, run)
  if (comparison.value) {
    rows.set(comparison.value.baseline.workflow_id, comparison.value.baseline)
    rows.set(comparison.value.candidate.workflow_id, comparison.value.candidate)
  }
  return [...rows.values()].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
})
const hasComparableRuns = computed(() => {
  const projectCounts = new Map<number, number>()
  for (const run of comparisonRunOptions.value) {
    if (!run.finished_at) continue
    const count = (projectCounts.get(run.project_id) || 0) + 1
    if (count >= 2) return true
    projectCounts.set(run.project_id, count)
  }
  return false
})
const visibleStatuses = computed(() => Object.entries(overview.value?.status_counts || {})
  .filter(([, count]) => count > 0)
  .map(([status, count]) => ({ status, count })))
const trendTotals = computed(() => (overview.value?.trend || []).reduce(
  (total, point) => ({
    completed: total.completed + point.completed,
    failed: total.failed + point.failed,
    tokens: total.tokens + point.total_tokens
  }),
  { completed: 0, failed: 0, tokens: 0 }
))
const trendAriaLabel = computed(() => {
  const metrics = overview.value?.metrics
  if (!metrics) return '运行与消耗趋势图'
  return `运行与消耗趋势图，共 ${metrics.total_runs} 次运行，完成 ${metrics.completed_runs} 次，失败 ${metrics.failed_runs} 次，消耗 ${metrics.total_tokens} Token`
})

async function loadOverview() {
  const requestId = ++overviewRequest
  loading.value = true
  overviewError.value = ''
  try {
    const { data } = await api.get<TraceOverview>('/traces/overview', {
      params: {
        days: days.value,
        project_id: projectId.value || undefined,
        status: statusFilter.value || undefined
      },
      suppressErrorToast: true
    })
    if (requestId !== overviewRequest) return
    overview.value = data
    await nextTick()
    renderChart()
  } catch (error) {
    if (requestId === overviewRequest) overviewError.value = getApiErrorMessage(error)
  } finally {
    if (requestId === overviewRequest) loading.value = false
  }
}

async function loadHealth() {
  const requestId = ++healthRequest
  healthLoading.value = true
  healthError.value = ''
  try {
    const { data } = await api.get<TraceHealth>('/traces/health', {
      params: {
        days: days.value,
        project_id: projectId.value || undefined
      },
      suppressErrorToast: true
    })
    if (requestId === healthRequest) health.value = data
  } catch (error) {
    if (requestId === healthRequest) healthError.value = getApiErrorMessage(error)
  } finally {
    if (requestId === healthRequest) healthLoading.value = false
  }
}

function refreshAll() {
  void loadOverview()
  void loadHealth()
}

function renderChart() {
  if (!chartElement.value || !overview.value) return
  chart = renderTraceTrendChart(chartElement.value, overview.value.trend)
  chartObserver?.disconnect()
  chartObserver = new ResizeObserver(() => chart?.resize())
  chartObserver.observe(chartElement.value)
}

async function loadDetail(workflowId: number) {
  const requestId = ++detailRequest
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  try {
    const { data } = await api.get<TraceDetail>(`/traces/${workflowId}`, { suppressErrorToast: true })
    if (requestId === detailRequest) detail.value = data
  } catch (error) {
    if (requestId === detailRequest) detailError.value = getApiErrorMessage(error)
  } finally {
    if (requestId === detailRequest) detailLoading.value = false
  }
}

async function loadComparison(baselineId: number, candidateId: number) {
  const requestId = ++comparisonRequest
  comparisonLoading.value = true
  comparisonError.value = ''
  comparison.value = null
  try {
    const { data } = await api.get<TraceComparison>('/traces/compare', {
      params: { baseline_id: baselineId, candidate_id: candidateId },
      suppressErrorToast: true
    })
    if (requestId === comparisonRequest) comparison.value = data
  } catch (error) {
    if (requestId === comparisonRequest) comparisonError.value = getApiErrorMessage(error)
  } finally {
    if (requestId === comparisonRequest) comparisonLoading.value = false
  }
}

function openTrace(workflowId: number) {
  comparisonDialogOpen.value = false
  void router.push({
    query: {
      ...route.query,
      run: String(workflowId),
      baseline: undefined,
      candidate: undefined
    }
  })
}

function closeTrace() {
  const query = { ...route.query }
  delete query.run
  void router.replace({ query })
}

function defaultComparisonPair() {
  const finished = comparisonRunOptions.value.filter((run) => Boolean(run.finished_at))
  for (const candidate of finished) {
    const baseline = finished.find((run) => (
      run.workflow_id !== candidate.workflow_id
      && run.project_id === candidate.project_id
      && Date.parse(run.created_at) <= Date.parse(candidate.created_at)
    ))
    if (baseline) return { baselineId: baseline.workflow_id, candidateId: candidate.workflow_id }
  }
  return null
}

function openComparison() {
  comparisonDialogOpen.value = true
  const pair = defaultComparisonPair()
  if ((!compareBaselineId.value || !compareCandidateId.value) && pair) {
    compareBaselineId.value = pair.baselineId
    compareCandidateId.value = pair.candidateId
  }
  if (route.query.run) {
    const query = { ...route.query }
    delete query.run
    void router.replace({ query })
  }
}

function submitComparison() {
  if (!compareBaselineId.value || !compareCandidateId.value) return
  const baselineId = compareBaselineId.value
  const candidateId = compareCandidateId.value
  if (
    comparisonQuery.value.baselineId === baselineId
    && comparisonQuery.value.candidateId === candidateId
  ) {
    void loadComparison(baselineId, candidateId)
    return
  }
  const query = {
    ...route.query,
    baseline: String(baselineId),
    candidate: String(candidateId),
    run: undefined
  }
  void router.push({ query })
}

function closeComparison() {
  comparisonDialogOpen.value = false
  comparisonRequest += 1
  comparisonLoading.value = false
  const query = { ...route.query }
  delete query.baseline
  delete query.candidate
  void router.replace({ query })
}

function positiveQueryId(value: unknown) {
  const raw = Array.isArray(value) ? value[0] : value
  const parsed = Number(raw)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

const numberFormatter = new Intl.NumberFormat('zh-CN')
function formatNumber(value: number) { return numberFormatter.format(value) }
function formatCompact(value: number) {
  if (Math.abs(value) < 10_000) return formatNumber(value)
  if (Math.abs(value) < 1_000_000) return `${(value / 1000).toFixed(value >= 100_000 ? 0 : 1)}k`
  return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}m`
}
function formatCost(micros: number) {
  const amount = micros / 1_000_000
  return `$${amount.toFixed(amount >= 1 ? 2 : 4)}`
}
function formatDuration(ms: number) {
  if (ms < 1000) return `${Math.max(0, ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} 秒`
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)} 分 ${Math.floor((ms % 60_000) / 1000)} 秒`
  return `${Math.floor(ms / 3_600_000)} 时 ${Math.floor((ms % 3_600_000) / 60_000)} 分`
}
function formatDate(value: string) { return new Date(value).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) }
function formatDateTime(value: string) { return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) }
function formatTime(value: string) { return new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) }
function statusLabel(status: string) { return statusLabels[status] || status }
function nodeLabel(node: string) { return nodeLabels[node] || node || '工作流' }
function roleLabel(role: string) { return roleLabels[role] || role || '未归属 Agent' }
function kindLabel(kind: string) { return ({ queue: '排队', node: '节点', branch: '并行分支', wait: '人工等待' } as Record<string, string>)[kind] || kind }
function eventTypeLabel(type: string) { return eventLabels[type] || type }
function statusTagType(status: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (status === 'COMPLETED') return 'success'
  if (['FAILED', 'COMPENSATION_FAILED'].includes(status)) return 'danger'
  if (['PAUSED', 'CANCELLING', 'COMPENSATING'].includes(status)) return 'warning'
  if (status === 'CANCELLED') return 'info'
  return 'primary'
}
function formatPayload(payload: Record<string, unknown>) {
  return Object.entries(payload).map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(', ') : String(value)}`).join(' · ')
}
function spanStyle(span: TraceSpan) {
  const total = Math.max(detail.value?.metrics.total_duration_ms || 0, 1)
  const origin = Date.parse(detail.value?.run.created_at || span.started_at)
  const elapsed = Math.max(0, Date.parse(span.started_at) - origin)
  const left = Math.min(100, elapsed / total * 100)
  const width = Math.min(100 - left, Math.max(0.8, span.duration_ms / total * 100))
  return { left: `${left}%`, width: `${width}%` }
}

watch([days, projectId], refreshAll, { immediate: true })
watch(statusFilter, loadOverview)
watch(selectedRunId, (workflowId) => {
  if (workflowId) void loadDetail(workflowId)
  else {
    detailRequest += 1
    detail.value = null
    detailError.value = ''
  }
}, { immediate: true })
watch(comparisonQuery, ({ baselineId, candidateId }) => {
  if (!baselineId || !candidateId) return
  compareBaselineId.value = baselineId
  compareCandidateId.value = candidateId
  comparisonDialogOpen.value = true
  void loadComparison(baselineId, candidateId)
}, { immediate: true })
watch(compareBaselineId, (baselineId) => {
  if (!baselineId || !compareCandidateId.value) return
  const baseline = comparisonRunOptions.value.find((run) => run.workflow_id === baselineId)
  const candidate = comparisonRunOptions.value.find((run) => run.workflow_id === compareCandidateId.value)
  if (baseline && candidate && baseline.project_id !== candidate.project_id) compareCandidateId.value = null
})
onBeforeUnmount(() => {
  healthRequest += 1
  comparisonRequest += 1
  chartObserver?.disconnect()
  chart?.dispose()
})
</script>

<style scoped>
.trace-page { width: 100%; max-width: 1480px; min-width: 0; margin: 0 auto; color: var(--color-foreground); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; padding: 0; border: 0; margin: -1px; clip: rect(0, 0, 0, 0); white-space: nowrap; }
.trace-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 22px; }
.trace-eyebrow { color: var(--color-primary); font-size: 12px; font-weight: 750; }
.trace-head h1 { margin: 4px 0 5px; font-size: 28px; line-height: 1.2; }
.trace-head p, .section-head p { margin: 0; color: var(--color-muted-text); font-size: 13px; }
.trace-toolbar { display: flex; align-items: center; justify-content: flex-end; gap: 8px; min-width: 0; }
.trace-toolbar > .el-select { width: 154px; }
.trace-toolbar > .el-button { width: 40px; min-width: 40px; height: 40px; }
.trace-toolbar > .compare-command { width: auto; min-width: 112px; }
.window-switch { flex: 0 0 auto; }
.trace-loading { padding: 30px 0; }
.trace-error { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 16px; border: 1px solid #fecaca; border-radius: 8px; background: #fef2f2; }
.trace-error div, .trace-error strong, .trace-error span { display: block; }
.trace-error span { margin-top: 3px; color: var(--color-secondary-text); font-size: 13px; }
.sample-alert, .refresh-alert { margin-bottom: 18px; }
.metric-section { margin-bottom: 10px; }
.metric-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.metric-card { display: block; min-width: 0; min-height: 112px; padding: 16px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); box-shadow: var(--shadow-sm); }
.metric-card span, .metric-card strong, .metric-card small { display: block; }
.metric-card span { color: var(--color-muted-text); font-size: 12px; }
.metric-card strong { margin-top: 9px; overflow: hidden; font-size: 25px; line-height: 1.15; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.metric-card small { margin-top: 7px; overflow: hidden; color: var(--color-secondary-text); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.status-strip { display: flex; flex-wrap: wrap; gap: 8px 22px; min-height: 42px; align-items: center; padding: 8px 2px; color: var(--color-secondary-text); font-size: 12px; }
.status-strip > span { display: inline-flex; align-items: center; gap: 6px; }
.status-strip strong { color: var(--color-foreground); font-variant-numeric: tabular-nums; }
.status-dot { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: #64748b; }
.status-completed { background: var(--color-success); }.status-failed, .status-compensation_failed { background: var(--color-danger); }.status-running, .status-queued { background: var(--color-primary); }.status-paused, .status-cancelling, .status-compensating { background: var(--color-warning); }
.trace-section { min-width: 0; padding: 24px 0; border-top: 1px solid var(--color-border); }
.section-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.section-head h2, .section-head h3 { margin: 0 0 4px; font-size: 17px; }
.section-head h3 { font-size: 16px; }
.section-count { color: var(--color-muted-text); font-size: 12px; white-space: nowrap; }
.trend-section { padding-bottom: 18px; }
.trend-chart { width: 100%; height: 286px; min-width: 0; }
.chart-legend { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px 16px; color: var(--color-secondary-text); font-size: 12px; }
.chart-legend span { display: inline-flex; align-items: center; gap: 6px; font-variant-numeric: tabular-nums; }
.chart-legend i { width: 15px; height: 4px; border-radius: 2px; }.legend-completed { background: #2563eb; }.legend-failed { background: #b91c1c; }.legend-token { height: 2px !important; background: #64748b; }
.trace-table { width: 100%; border: 1px solid var(--color-border); border-radius: 8px; }
.entity-cell { display: flex; min-width: 0; align-items: center; gap: 10px; }
.entity-cell div, .node-cell { min-width: 0; }
.entity-cell strong, .entity-cell small, .node-cell strong, .node-cell small, .model-name, .provider-name { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.entity-cell small, .node-cell small, .provider-name { margin-top: 2px; color: var(--color-muted-text); font-size: 11px; font-weight: 400; }
.agent-mark { display: inline-flex; width: 30px; height: 30px; flex: 0 0 30px; align-items: center; justify-content: center; border: 1px solid #bfdbfe; border-radius: 6px; background: var(--color-primary-soft); color: var(--color-primary); font-size: 12px; font-weight: 750; }
.model-name { color: var(--color-foreground); font-size: 12px; }
.number-cell, .date-cell { font-variant-numeric: tabular-nums; }.date-cell { color: var(--color-secondary-text); font-size: 12px; }
.share-cell { display: grid; grid-template-columns: minmax(70px, 1fr) 46px; align-items: center; gap: 10px; }.share-cell strong { text-align: right; font-size: 12px; font-variant-numeric: tabular-nums; }
.trace-link { min-width: 44px; min-height: 40px; padding: 0; border: 0; background: transparent; color: var(--color-primary); font: inherit; font-weight: 750; text-align: left; cursor: pointer; }.trace-link:hover { text-decoration: underline; }
.mobile-card-list { display: none; }
.drawer-head { position: sticky; z-index: 2; top: 0; display: flex; min-height: 76px; align-items: center; justify-content: space-between; gap: 16px; padding: 15px 20px; border-bottom: 1px solid var(--color-border); background: rgba(255, 255, 255, .98); }
.drawer-head > div, .drawer-head > div > div { min-width: 0; }.drawer-head > div { flex: 1 1 auto; }.drawer-head > div > span { color: var(--color-muted-text); font-size: 11px; }.drawer-head > div > div { display: flex; align-items: center; gap: 10px; }.drawer-head h2 { min-width: 0; max-width: 650px; flex: 1 1 auto; margin: 4px 0 0; overflow: hidden; font-size: 19px; text-overflow: ellipsis; white-space: nowrap; }.drawer-head .el-tag { flex: 0 0 auto; }
.drawer-head > .el-button { width: 40px; min-width: 40px; height: 40px; flex: 0 0 40px; }.drawer-loading, .trace-detail { padding: 20px; }
.detail-metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); overflow: hidden; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-border); gap: 1px; }
.detail-metrics > div { min-width: 0; padding: 12px; background: var(--color-surface); }.detail-metrics span, .detail-metrics strong { display: block; }.detail-metrics span { color: var(--color-muted-text); font-size: 11px; }.detail-metrics strong { margin-top: 4px; overflow: hidden; font-size: 15px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.detail-section { min-width: 0; margin-top: 28px; }.span-list { border-top: 1px solid var(--color-border); }
.span-row { display: grid; min-height: 68px; grid-template-columns: minmax(170px, .9fr) minmax(170px, 1.3fr) minmax(135px, .7fr); align-items: center; gap: 14px; border-bottom: 1px solid var(--color-border); }.span-row.critical { background: #fffbeb; }
.span-copy { display: grid; min-width: 0; grid-template-columns: 54px minmax(0, 1fr); align-items: center; gap: 9px; }.span-copy strong, .span-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.span-copy small { margin-top: 2px; color: var(--color-muted-text); font-size: 11px; }
.span-kind { display: inline-flex; min-height: 24px; align-items: center; justify-content: center; border: 1px solid var(--color-border); border-radius: 4px; color: var(--color-secondary-text); font-size: 10px; }.span-kind-branch { border-color: #bae6fd; background: #f0f9ff; color: #075985; }.span-kind-wait { border-color: #fde68a; background: #fffbeb; color: #92400e; }
.span-track { position: relative; height: 10px; overflow: hidden; border-radius: 5px; background: #eef0f3; }.span-bar { position: absolute; top: 0; height: 100%; min-width: 3px; border-radius: 5px; background: #64748b; }.span-bar-node { background: #2563eb; }.span-bar-branch { background: #0284c7; }.span-bar-wait { background: #b45309; }
.span-numbers { min-width: 0; text-align: right; }.span-numbers strong, .span-numbers small { display: block; }.span-numbers strong { font-variant-numeric: tabular-nums; }.span-numbers small { margin-top: 3px; overflow: hidden; color: var(--color-muted-text); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.event-list { margin: 0; padding: 0; list-style: none; }.event-list li { display: grid; min-height: 68px; grid-template-columns: 74px 14px minmax(0, 1fr); gap: 10px; }.event-list time { padding-top: 3px; color: var(--color-muted-text); font-size: 11px; font-variant-numeric: tabular-nums; }.event-marker { position: relative; width: 8px; height: 8px; margin-top: 6px; border: 2px solid var(--color-primary); border-radius: 50%; background: var(--color-surface); }.event-marker::after { position: absolute; top: 9px; left: 2px; width: 1px; height: 52px; background: var(--color-border); content: ''; }.event-list li:last-child .event-marker::after { display: none; }.event-list strong { font-size: 12px; }.event-list p { margin: 3px 0 5px; color: var(--color-secondary-text); font-size: 12px; }.event-list code { display: block; overflow-wrap: anywhere; color: var(--color-muted-text); font-family: inherit; font-size: 10px; }
:global(.trace-detail-drawer .el-drawer__body) { padding: 0; overflow-x: hidden; overflow-y: auto; }

@media (max-width: 1380px) { .trace-head { align-items: flex-start; flex-direction: column; }.trace-toolbar { width: 100%; justify-content: flex-start; } }
@media (max-width: 1180px) {
  .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.metric-card:nth-child(4), .metric-card:nth-child(5) { grid-column: span 1; }.detail-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 820px) {
  .trace-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto 44px; }.window-switch { grid-column: 1 / -1; }.trace-toolbar > .el-select { width: 100%; }.trace-toolbar > .el-button { width: 44px; height: 44px; }.trace-toolbar > .compare-command { width: auto; min-width: 112px; }.metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.metric-card:last-child { grid-column: 1 / -1; }.section-head { align-items: flex-start; }.desktop-table { display: none; }.mobile-card-list { display: grid; gap: 10px; }.mobile-data-card { min-width: 0; padding: 14px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); }.mobile-card-head { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 12px; }.mobile-card-head > strong { flex: 0 0 auto; font-variant-numeric: tabular-nums; }.mobile-data-card > p { overflow: hidden; margin: 9px 0; color: var(--color-muted-text); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.mobile-data-card dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 12px 0 0; padding-top: 10px; border-top: 1px solid var(--color-border); }.mobile-data-card dt { color: var(--color-muted-text); font-size: 10px; }.mobile-data-card dd { margin: 3px 0 0; overflow: hidden; font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }.run-card-button { display: flex; width: 100%; min-height: 44px; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 0; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }.run-card-button > span { min-width: 0; }.run-card-button strong, .run-card-button small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.run-card-button small { margin-top: 3px; color: var(--color-muted-text); font-size: 10px; }.span-row { grid-template-columns: minmax(0, 1fr) minmax(120px, .7fr); padding: 10px 0; }.span-track { grid-column: 1 / -1; grid-row: 2; }.detail-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 520px) {
  .trace-head { margin-bottom: 18px; }.trace-head h1 { font-size: 24px; }.trace-toolbar { grid-template-columns: minmax(0, 1fr) 44px; }.window-switch { display: flex; width: 100%; }.window-switch :deep(.el-radio-button) { flex: 1; }.window-switch :deep(.el-radio-button__inner) { width: 100%; min-height: 44px; padding: 12px 8px; }.trace-toolbar > .project-filter { grid-column: 1; grid-row: 2; }.trace-toolbar > .status-filter { grid-column: 1 / -1; grid-row: 3; }.trace-toolbar > .refresh-command { grid-column: 2; grid-row: 2; }.trace-toolbar > .compare-command { grid-column: 1 / -1; grid-row: 4; width: 100%; min-height: 44px; }.metric-grid { gap: 8px; }.metric-card { min-height: 104px; padding: 13px; }.metric-card strong { overflow: visible; font-size: 21px; white-space: normal; }.metric-card small { white-space: normal; }.status-strip { gap: 8px 14px; }.trace-section { padding: 20px 0; }.section-head { flex-direction: column; }.chart-legend { justify-content: flex-start; }.trend-chart { height: 250px; }.drawer-head { min-height: 70px; padding: 12px 14px; }.drawer-head h2 { max-width: none; font-size: 16px; }.drawer-head > .el-button { width: 44px; min-width: 44px; height: 44px; flex-basis: 44px; }.drawer-loading, .trace-detail { padding: 14px; }.detail-metrics > div { padding: 10px; }.span-row { grid-template-columns: minmax(0, 1fr) 110px; gap: 9px; }.span-copy { grid-template-columns: 46px minmax(0, 1fr); }.span-kind { font-size: 9px; }.span-numbers small { display: none; }.event-list li { grid-template-columns: 58px 12px minmax(0, 1fr); gap: 7px; }
}
@media (prefers-reduced-motion: reduce) { .span-bar { transition: none; } }
</style>
