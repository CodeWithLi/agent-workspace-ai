<template>
  <el-dialog
    :model-value="modelValue"
    class="workflow-launch-dialog"
    width="min(760px, calc(100vw - 24px))"
    :close-on-click-modal="false"
    :close-on-press-escape="!launching"
    :show-close="!launching"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="workflow-launch-title">
        <span>Multi-Agent</span>
        <h2>启动工作流</h2>
      </div>
    </template>

    <div class="workflow-launch-body">
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="工作目标" required>
          <el-input
            v-model="goal"
            type="textarea"
            :rows="4"
            maxlength="20000"
            show-word-limit
            resize="vertical"
            :disabled="launching"
            placeholder="例如：为企业知识平台设计可追溯检索、灰度发布和验收方案"
            aria-label="多 Agent 工作目标"
          />
        </el-form-item>
      </el-form>

      <section class="team-preflight" aria-label="工作流团队预检" aria-live="polite">
        <header class="team-preflight-head">
          <div>
            <span>团队预检</span>
            <strong>{{ preflightStatus }}</strong>
          </div>
          <el-tag v-if="preflight" :type="preflight.ready ? 'success' : 'danger'" effect="plain">
            {{ preflight.eligible_count }}/{{ preflight.specialists.length }} 可用
          </el-tag>
        </header>

        <el-skeleton v-if="preflightLoading" class="preflight-loading" :rows="4" animated />
        <div v-else-if="preflightError" class="preflight-error" role="alert">
          <div><strong>预检失败</strong><span>{{ preflightError }}</span></div>
          <el-button :disabled="!normalizedGoal || launching" @click="runPreflight">重新检查</el-button>
        </div>
        <template v-else-if="preflight">
          <el-alert
            v-if="preflight.blockers.length"
            type="error"
            :closable="false"
            show-icon
            title="团队尚未就绪"
            :description="preflight.blockers.join(' ')"
          />
          <div class="preflight-requirements">
            <strong>目标能力</strong>
            <span v-if="preflight.required_capabilities.length">
              {{ preflight.required_capabilities.map(specialistCapabilityLabel).join('、') }}
            </span>
            <span v-else>通用交付能力</span>
          </div>
          <div class="preflight-history-summary">
            <strong>同项目历史</strong>
            <span v-if="preflight.team_performance_profile.branch_sample_count">
              {{ preflight.team_performance_profile.workflow_count }} 次终态运行 ·
              {{ preflight.team_performance_profile.branch_sample_count }} 份当前配置样本 ·
              {{ preflight.team_performance_profile.sufficient_role_count }}/{{ preflight.team_performance_profile.roles.length }} 个角色可参与可靠性调整
            </span>
            <span v-else>尚无可用分支样本，本次规划不会应用历史可靠性调整</span>
            <small v-if="preflight.team_performance_profile.excluded_branch_sample_count">
              已排除 {{ preflight.team_performance_profile.excluded_branch_sample_count }} 份旧版 Prompt、模型或运行配置样本
            </small>
          </div>
          <ul class="preflight-specialists" aria-label="专业 Agent 资格">
            <li
              v-for="profile in preflight.specialists"
              :key="profile.role"
              :class="{ unavailable: !profile.eligible }"
            >
              <el-icon aria-hidden="true">
                <CircleCheck v-if="profile.eligible" />
                <CircleClose v-else />
              </el-icon>
              <div class="preflight-specialist-copy">
                <header>
                  <div><strong>{{ profile.name }}</strong><small>{{ specialistRoleLabel(profile.role) }}</small></div>
                  <el-tag size="small" :type="profile.eligible ? 'success' : 'info'" effect="plain">
                    {{ profile.eligible ? '可参与规划' : '当前不可用' }}
                  </el-tag>
                </header>
                <p v-if="profile.eligible">{{ profile.capabilities.map(specialistCapabilityLabel).join('、') }}</p>
                <p v-else role="status">{{ profile.unavailable_reasons.join('、') }}</p>
                <details v-if="profile.eligible">
                  <summary>运行配置与历史证据</summary>
                  <dl>
                    <div><dt>启用工具</dt><dd>{{ profile.enabled_tools.map(specialistToolLabel).join('、') || '无' }}</dd></div>
                    <div><dt>并发额度</dt><dd>{{ profile.concurrency_limit }}</dd></div>
                    <div><dt>知识访问</dt><dd>{{ profile.knowledge_access ? '已启用' : '未启用' }}</dd></div>
                    <template v-if="performanceForRole(profile.role)">
                      <div>
                        <dt>历史样本</dt>
                        <dd>
                          {{ performanceForRole(profile.role)?.sample_count }} 份 ·
                          已排除 {{ performanceForRole(profile.role)?.excluded_sample_count || 0 }} 份旧配置 ·
                          {{ evidenceLevelLabel(performanceForRole(profile.role)?.evidence_level) }}
                        </dd>
                      </div>
                      <div>
                        <dt>可靠性</dt>
                        <dd>{{ reliabilityLabel(profile.role) }}</dd>
                      </div>
                      <div>
                        <dt>分支耗时</dt>
                        <dd>{{ formatDuration(performanceForRole(profile.role)?.median_latency_ms) }}</dd>
                      </div>
                      <div>
                        <dt>平均成本</dt>
                        <dd>{{ formatCost(performanceForRole(profile.role)?.average_cost_micros) }}</dd>
                      </div>
                    </template>
                  </dl>
                </details>
              </div>
            </li>
          </ul>
        </template>
        <div v-else class="preflight-idle" role="status">等待工作目标</div>
      </section>
    </div>

    <template #footer>
      <div class="workflow-launch-actions">
        <el-button :disabled="launching" @click="emit('update:modelValue', false)">取消</el-button>
        <el-button
          type="primary"
          :icon="VideoPlay"
          :loading="launching"
          :disabled="!canLaunch"
          @click="submit"
        >启动并进入计划审批</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { CircleCheck, CircleClose, VideoPlay } from '@element-plus/icons-vue'
import { api, getApiErrorMessage } from '../api/client'
import type { PerformanceEvidenceLevel, WorkflowPreflight } from '../api/types'
import {
  specialistCapabilityLabel,
  specialistRoleLabel,
  specialistToolLabel
} from '../utils/specialists'

const props = defineProps<{
  modelValue: boolean
  projectId: number
  initialGoal: string
  launching: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  launch: [goal: string]
}>()

const goal = ref('')
const checkedGoal = ref('')
const preflight = ref<WorkflowPreflight | null>(null)
const preflightLoading = ref(false)
const preflightError = ref('')
let preflightTimer: ReturnType<typeof setTimeout> | null = null
let preflightSequence = 0

const normalizedGoal = computed(() => goal.value.trim())
const canLaunch = computed(() => Boolean(
  preflight.value?.ready
  && checkedGoal.value === normalizedGoal.value
  && !preflightLoading.value
  && !props.launching
))
const preflightStatus = computed(() => {
  if (preflightLoading.value) return '正在检查'
  if (preflightError.value) return '检查失败'
  if (!preflight.value) return '等待目标'
  return preflight.value.ready ? '可以启动' : '存在阻塞'
})

function performanceForRole(role: string) {
  return preflight.value?.team_performance_profile.roles.find((item) => item.role === role)
}

function evidenceLevelLabel(level?: PerformanceEvidenceLevel) {
  return {
    INSUFFICIENT: '样本不足',
    LOW: '低证据',
    MEDIUM: '中证据',
    HIGH: '高证据'
  }[level || 'INSUFFICIENT']
}

function reliabilityLabel(role: string) {
  const evidence = performanceForRole(role)
  if (!evidence || evidence.evidence_level === 'INSUFFICIENT') return '样本不足，不影响规划'
  return `${Math.round(evidence.reliability_score * 100)}% · 重试 ${Math.round(evidence.retry_rate * 100)}% · 修订 ${Math.round(evidence.revision_rate * 100)}% · 质检退回 ${Math.round((evidence.quality_failure_rate || 0) * 100)}%`
}

function formatDuration(value?: number | null) {
  if (value === null || value === undefined) return '暂无完整观测'
  if (value < 1000) return `${value} ms`
  if (value < 60_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} 秒`
  return `${(value / 60_000).toFixed(1)} 分钟`
}

function formatCost(value?: number | null) {
  if (value === null || value === undefined) return '暂无完整观测'
  const amount = value / 1_000_000
  return `$${amount.toFixed(amount >= 1 ? 2 : 4)}`
}

function cancelScheduledPreflight() {
  if (preflightTimer) clearTimeout(preflightTimer)
  preflightTimer = null
}

function schedulePreflight(delay = 350) {
  cancelScheduledPreflight()
  checkedGoal.value = ''
  preflight.value = null
  preflightError.value = ''
  if (!props.modelValue || !normalizedGoal.value) {
    preflightLoading.value = false
    return
  }
  preflightLoading.value = true
  preflightTimer = setTimeout(() => {
    preflightTimer = null
    void runPreflight()
  }, delay)
}

async function runPreflight() {
  const submittedGoal = normalizedGoal.value
  if (!props.modelValue || !submittedGoal) return
  const sequence = ++preflightSequence
  preflightLoading.value = true
  preflightError.value = ''
  try {
    const { data } = await api.post<WorkflowPreflight>('/workflow/preflight', {
      project_id: props.projectId,
      user_input: submittedGoal
    }, { suppressErrorToast: true })
    if (sequence !== preflightSequence || submittedGoal !== normalizedGoal.value) return
    preflight.value = data
    checkedGoal.value = submittedGoal
  } catch (error) {
    if (sequence !== preflightSequence) return
    preflight.value = null
    checkedGoal.value = ''
    preflightError.value = getApiErrorMessage(error)
  } finally {
    if (sequence === preflightSequence) preflightLoading.value = false
  }
}

function submit() {
  if (!canLaunch.value) return
  emit('launch', normalizedGoal.value)
}

watch(() => props.modelValue, (open) => {
  if (!open) {
    cancelScheduledPreflight()
    preflightSequence += 1
    preflightLoading.value = false
    return
  }
  goal.value = props.initialGoal.trim()
  schedulePreflight(0)
})

watch(goal, () => {
  if (props.modelValue) schedulePreflight()
})

onBeforeUnmount(() => {
  cancelScheduledPreflight()
  preflightSequence += 1
})
</script>

<style scoped>
.workflow-launch-title {
  display: grid;
  gap: 2px;
}

.workflow-launch-title span {
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.workflow-launch-title h2 {
  margin: 0;
  font-size: 19px;
  letter-spacing: 0;
}

.workflow-launch-body {
  display: grid;
  gap: 14px;
}

.workflow-launch-body :deep(.el-form-item) {
  margin-bottom: 0;
}

.team-preflight {
  min-height: 250px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
}

.team-preflight-head {
  display: flex;
  min-height: 54px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--color-border);
  background: #f6f8fa;
}

.team-preflight-head > div {
  display: grid;
  gap: 2px;
}

.team-preflight-head span {
  color: var(--color-muted-text);
  font-size: 11px;
}

.team-preflight-head strong {
  font-size: 14px;
}

.preflight-loading {
  padding: 16px;
}

.preflight-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
}

.preflight-error > div {
  display: grid;
  gap: 3px;
}

.preflight-error span {
  color: var(--color-secondary-text);
  font-size: 12px;
}

.team-preflight :deep(.el-alert) {
  border-radius: 0;
}

.preflight-requirements {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-secondary-text);
  font-size: 12px;
  line-height: 1.5;
}

.preflight-history-summary {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-background);
  color: var(--color-secondary-text);
  font-size: 12px;
  line-height: 1.5;
}

.preflight-history-summary strong {
  color: var(--color-foreground);
}

.preflight-history-summary small {
  grid-column: 2;
  color: var(--color-muted-text);
  font-size: 11px;
}

.preflight-requirements strong {
  color: var(--color-primary);
}

.preflight-specialists {
  margin: 0;
  padding: 0;
  list-style: none;
}

.preflight-specialists > li {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 9px;
  padding: 11px 12px;
  border-bottom: 1px solid var(--color-border);
}

.preflight-specialists > li:last-child {
  border-bottom: 0;
}

.preflight-specialists > li > .el-icon {
  margin-top: 2px;
  color: var(--color-success);
  font-size: 16px;
}

.preflight-specialists > li.unavailable > .el-icon {
  color: var(--color-muted-text);
}

.preflight-specialist-copy {
  min-width: 0;
}

.preflight-specialist-copy > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.preflight-specialist-copy > header > div {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
}

.preflight-specialist-copy strong {
  font-size: 13px;
}

.preflight-specialist-copy small,
.preflight-specialist-copy p {
  color: var(--color-muted-text);
  font-size: 11px;
  line-height: 1.5;
}

.preflight-specialist-copy p {
  margin: 3px 0 0;
  overflow-wrap: anywhere;
}

.preflight-specialist-copy details {
  margin-top: 3px;
}

.preflight-specialist-copy summary {
  min-height: 40px;
  box-sizing: border-box;
  padding: 11px 0;
  color: var(--color-primary);
  cursor: pointer;
  font-size: 11px;
  font-weight: 650;
}

.preflight-specialist-copy summary:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.preflight-specialist-copy dl {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-bottom: 3px;
}

.preflight-specialist-copy dl > div {
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  gap: 8px;
  font-size: 11px;
  line-height: 1.5;
}

.preflight-specialist-copy dt {
  color: var(--color-muted-text);
  font-weight: 650;
}

.preflight-specialist-copy dd {
  margin: 0;
  color: var(--color-secondary-text);
  overflow-wrap: anywhere;
}

.preflight-idle {
  padding: 24px 16px;
  color: var(--color-muted-text);
  text-align: center;
}

.workflow-launch-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 640px) {
  .team-preflight-head,
  .preflight-error,
  .preflight-specialist-copy > header {
    align-items: flex-start;
    flex-direction: column;
  }

  .preflight-requirements,
  .preflight-history-summary,
  .preflight-specialist-copy dl > div {
    grid-template-columns: 1fr;
    gap: 2px;
  }

  .preflight-history-summary small {
    grid-column: 1;
  }

  .preflight-specialist-copy summary {
    min-height: 44px;
    padding-block: 13px;
  }

  .workflow-launch-actions {
    display: grid;
    grid-template-columns: 1fr;
  }

  .workflow-launch-actions .el-button {
    width: 100%;
    min-height: 44px;
    margin-left: 0;
  }
}
</style>
