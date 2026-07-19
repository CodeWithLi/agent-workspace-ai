<template>
  <section class="page prototype-studio-page">
    <div class="page-head studio-page-head">
      <div>
        <h1>AI 原型工作室</h1>
        <p>产品方案、可交互界面与多 Agent 评审版本。</p>
      </div>
      <div class="studio-head-actions">
        <el-select
          v-if="prototypes.length"
          v-model="selectedPrototypeId"
          class="prototype-switcher"
          aria-label="切换产品原型"
          @change="selectPrototype"
        >
          <el-option v-for="item in prototypes" :key="item.id" :label="`${item.title} · v${item.active_version}`" :value="item.id" />
        </el-select>
        <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openCreateDialog">新建原型</el-button>
      </div>
    </div>

    <section
      v-if="generationJob"
      class="generation-job-band"
      :class="`job-${generationJob.status.toLowerCase()}`"
      :aria-live="generationJob.status === 'FAILED' ? 'assertive' : 'polite'"
      :role="generationJob.status === 'FAILED' ? 'alert' : 'status'"
    >
      <div class="generation-job-head">
        <div class="generation-job-title">
          <span class="job-state-icon" aria-hidden="true">
            <el-icon v-if="generationActive" class="is-loading"><Loading /></el-icon>
            <el-icon v-else-if="generationJob.status === 'SUCCEEDED'"><CircleCheck /></el-icon>
            <el-icon v-else><WarningFilled /></el-icon>
          </span>
          <div>
            <strong>{{ generationHeadline }}</strong>
            <span>{{ generationJob.title }} · {{ generationStatusLabel(generationJob.status) }}</span>
          </div>
        </div>
        <div class="generation-job-actions">
          <el-tag :type="generationStatusTag(generationJob.status)" effect="light">{{ generationJob.progress_percent }}%</el-tag>
          <el-button
            v-if="generationActive && canControlGenerationJob"
            :icon="Close"
            :loading="cancellingGeneration"
            @click="cancelGeneration"
          >取消任务</el-button>
          <el-button
            v-if="generationJob.status === 'FAILED' && generationJob.retryable && canControlGenerationJob"
            type="primary"
            :icon="Refresh"
            :loading="retryingGeneration"
            @click="retryGeneration"
          >重试</el-button>
          <el-button v-if="generationTerminal" :icon="Close" @click="dismissGenerationJob">隐藏</el-button>
        </div>
      </div>

      <el-progress
        :percentage="generationJob.progress_percent"
        :status="generationProgressStatus"
        :stroke-width="8"
        :show-text="false"
      />

      <div class="generation-job-current">
        <div>
          <strong>{{ generationStageLabel(generationJob.stage, currentGenerationStage?.round) }}</strong>
          <span>{{ generationJob.error_message ? generationStatusDescription : (currentGenerationStage?.message || generationStatusDescription) }}</span>
        </div>
        <span>第 {{ generationJob.attempt_count || 1 }} / {{ generationJob.max_attempts }} 次尝试</span>
      </div>

      <div v-if="generationConnectionNotice" class="generation-connection-notice">
        <el-icon><Connection /></el-icon>
        <span>{{ generationConnectionNotice }}</span>
      </div>
      <p v-if="generationJob.error_message" class="generation-job-error">{{ generationJob.error_message }}</p>

      <details v-if="generationJob.stage_history.length" class="generation-stage-history">
        <summary>查看 Agent 执行记录（{{ generationJob.stage_history.length }}）</summary>
        <ol>
          <li v-for="(stage, index) in generationJob.stage_history" :key="`${stage.stage}-${stage.round || 0}-${index}`" :class="`stage-${stage.status.toLowerCase()}`">
            <span class="stage-marker" aria-hidden="true"><el-icon><CircleCheck v-if="stage.status === 'COMPLETED'" /><Loading v-else-if="stage.status === 'RUNNING'" /><CircleClose v-else-if="stage.status === 'FAILED'" /><Clock v-else /></el-icon></span>
            <div><strong>{{ generationStageLabel(stage.stage, stage.round) }}</strong><span>{{ stage.message || generationStageRoleLabel(stage.agent_role) }}</span></div>
            <small>{{ stage.finished_at ? formatDate(stage.finished_at) : stage.started_at ? formatDate(stage.started_at) : '' }}</small>
          </li>
        </ol>
      </details>
    </section>

    <div v-loading="loadingCatalog" class="studio-content">
      <div v-if="!loadingCatalog && !activePrototype" class="studio-empty">
        <el-empty :description="projects.length ? '还没有产品原型' : '请先创建一个项目'">
          <el-button v-if="projects.length && canCreate" type="primary" :icon="MagicStick" @click="openCreateDialog">生成第一个原型</el-button>
          <el-button v-else-if="!projects.length && canCreate" type="primary" :icon="FolderAdd" @click="router.push('/projects')">创建项目</el-button>
        </el-empty>
      </div>

      <template v-else-if="activePrototype">
        <header class="prototype-summary-band">
          <div class="prototype-heading">
            <div class="prototype-title-row">
              <h2>{{ activePrototype.title }}</h2>
              <el-tag type="warning" effect="light" size="small">AI 草案</el-tag>
              <span class="version-label">v{{ activePrototype.active_version }}</span>
            </div>
            <p>{{ activePrototype.summary }}</p>
            <div class="prototype-context">
              <span><el-icon><Folder /></el-icon>{{ activeProjectName }}</span>
              <span v-if="activeRequirementName"><el-icon><Document /></el-icon>{{ activeRequirementName }}</span>
              <span><el-icon><Clock /></el-icon>{{ formatDate(activePrototype.updated_at) }}</span>
            </div>
          </div>

          <div class="prototype-summary-actions">
            <el-segmented v-model="deviceMode" :options="deviceOptions" aria-label="原型预览设备" />
            <el-button v-if="canEdit" :icon="Refresh" :loading="regenerating" @click="openRegenerateDialog">重新生成</el-button>
            <el-button v-if="canEdit && activePrototype.status === 'APPROVED'" type="primary" :icon="Tickets" :loading="materializing" @click="materializePrototype">生成交付清单</el-button>
            <el-dropdown trigger="click" @command="handleMoreCommand">
              <el-button :icon="MoreFilled">更多</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="export" :icon="Download">导出 JSON</el-dropdown-item>
                  <el-dropdown-item v-if="canEdit" command="delete" :icon="Delete" divided>删除原型</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </header>

        <div v-loading="loadingDetail" class="studio-shell">
          <aside class="screen-navigator" aria-label="原型界面">
            <div class="panel-heading">
              <strong>界面</strong>
              <span>{{ activePrototype.current.specification.screens.length }}</span>
            </div>
            <div class="screen-list">
              <button
                v-for="(screen, index) in activePrototype.current.specification.screens"
                :key="screen.id"
                :class="{ active: screen.id === activeScreenId }"
                :aria-current="screen.id === activeScreenId ? 'page' : undefined"
                @click="navigateScreen(screen.id)"
              >
                <span>{{ index + 1 }}</span>
                <div><strong>{{ screen.name }}</strong><small>{{ screen.description || layoutLabel(screen.layout) }}</small></div>
                <el-icon><ArrowRight /></el-icon>
              </button>
            </div>
          </aside>

          <main class="preview-workbench">
            <div class="preview-toolbar">
              <div>
                <strong>{{ activeScreen?.name }}</strong>
                <span>{{ lastInteraction || activeScreen?.description || '可交互原型预览' }}</span>
              </div>
              <el-tooltip content="重置当前预览的输入与交互状态" placement="top">
                <el-button :icon="RefreshLeft" circle aria-label="重置原型交互" @click="resetCanvas" />
              </el-tooltip>
            </div>
            <div class="preview-stage" :class="`preview-${deviceMode}`">
              <div class="device-frame" :class="`device-${deviceMode}`">
                <div v-if="deviceMode === 'mobile'" class="mobile-frame-top" aria-hidden="true"><span /></div>
                <PrototypeCanvas
                  :key="canvasSession"
                  :spec="activePrototype.current.specification"
                  :screen-id="activeScreenId"
                  :device-mode="deviceMode"
                  :highlight-component-id="highlightedJourneyComponentId"
                  @navigate="navigateScreen"
                  @back="navigateBack"
                  @interaction="lastInteraction = $event"
                  @action="handlePrototypeAction"
                />
              </div>
            </div>
          </main>

          <aside class="prototype-inspector">
            <div class="inspector-status">
              <div>
                <small>评审状态</small>
                <strong>{{ statusLabel(activePrototype.status) }}</strong>
              </div>
              <el-select
                v-if="canEdit"
                :model-value="activePrototype.status"
                aria-label="更新原型评审状态"
                :loading="savingStatus"
                @change="updateStatus"
              >
                <el-option v-for="status in prototypeStatuses" :key="status" :label="statusLabel(status)" :value="status" />
              </el-select>
              <el-tag v-else :type="statusTagType(activePrototype.status)">{{ statusLabel(activePrototype.status) }}</el-tag>
            </div>

            <el-tabs v-model="inspectorTab" stretch>
              <el-tab-pane label="质量" name="quality">
                <div class="quality-summary">
                  <el-progress
                    type="dashboard"
                    :percentage="Math.round(activePrototype.current.quality.score)"
                    :color="qualityColor"
                    :width="104"
                    :stroke-width="9"
                  />
                  <div><strong>{{ activePrototype.current.quality.passed ? '通过自动门禁' : '需要继续修订' }}</strong><span>{{ activePrototype.current.quality.checks.filter((item) => item.passed).length }} / {{ activePrototype.current.quality.checks.length }} 项检查通过</span></div>
                </div>
                <ul class="quality-checks">
                  <li v-for="check in activePrototype.current.quality.checks" :key="check.name" :class="{ failed: !check.passed }">
                    <el-icon><CircleCheck v-if="check.passed" /><CircleClose v-else /></el-icon>
                    <div><strong>{{ qualityCheckLabel(check.name) }}</strong><span>{{ check.detail }}</span></div>
                  </li>
                </ul>
                <div v-if="activePrototype.current.quality.reviewer_summary" class="reviewer-summary">
                  <strong>测试 Agent 结论<span v-if="activePrototype.current.quality.reviewer_score !== undefined"> · {{ Math.round(activePrototype.current.quality.reviewer_score) }} 分</span></strong>
                  <p>{{ activePrototype.current.quality.reviewer_summary }}</p>
                </div>
              </el-tab-pane>

              <el-tab-pane :label="`评审 ${openReviewCount}`" name="reviews">
                <div v-if="canEdit && activePrototype.status !== 'ARCHIVED'" class="review-composer">
                  <el-select v-model="commentScreenId" aria-label="评审评论所属界面">
                    <el-option label="整个原型" value="" />
                    <el-option v-for="screen in activePrototype.current.specification.screens" :key="screen.id" :label="screen.name" :value="screen.id" />
                  </el-select>
                  <el-input v-model="commentDraft" type="textarea" :rows="3" maxlength="5000" show-word-limit placeholder="记录需要修订的流程、状态或验收问题" aria-label="原型评审评论" />
                  <el-button type="primary" :icon="ChatLineRound" :loading="postingComment" :disabled="!commentDraft.trim()" @click="addReviewComment">添加评论</el-button>
                </div>
                <div v-if="reviewComments.length" class="review-comment-list">
                  <article v-for="comment in reviewComments" :key="comment.id" :class="{ resolved: comment.status === 'RESOLVED' }">
                    <div class="review-comment-head">
                      <div><strong>{{ comment.user_name }}</strong><span>{{ comment.screen_id ? screenName(comment.screen_id) : '整个原型' }} · {{ formatDate(comment.created_at) }}</span></div>
                      <el-tag :type="comment.status === 'OPEN' ? 'warning' : 'success'" size="small">{{ comment.status === 'OPEN' ? '待处理' : '已解决' }}</el-tag>
                    </div>
                    <p>{{ comment.body }}</p>
                    <el-button v-if="canEdit && comment.status === 'OPEN'" link type="primary" :loading="resolvingCommentId === comment.id" @click="resolveReviewComment(comment.id)">标记已解决</el-button>
                  </article>
                </div>
                <el-empty v-else description="当前版本暂无评审评论" :image-size="56" />
              </el-tab-pane>

              <el-tab-pane :label="`路径 ${prototypeJourneys.length}`" name="journeys">
                <div v-if="prototypeJourneys.length && activeJourney" class="journey-panel">
                  <el-select
                    v-model="selectedJourneyId"
                    aria-label="选择原型体验路径"
                    @change="selectJourney"
                  >
                    <el-option
                      v-for="journey in prototypeJourneys"
                      :key="journey.id"
                      :label="journey.name"
                      :value="journey.id"
                    />
                  </el-select>

                  <section class="journey-summary" aria-label="体验路径进度">
                    <div>
                      <strong>{{ activeJourney.name }}</strong>
                      <span>{{ activeJourney.goal }}</span>
                    </div>
                    <el-progress :percentage="journeyProgress" :show-text="false" :stroke-width="6" />
                    <small>{{ journeyProgressLabel }}</small>
                  </section>

                  <ol class="journey-step-list" aria-label="体验路径步骤">
                    <li
                      v-for="(step, index) in activeJourney.steps"
                      :key="`${activeJourney.id}-${index}`"
                      :class="{
                        completed: index < journeyStepIndex,
                        current: journeyRunning && index === journeyStepIndex
                      }"
                      :aria-current="journeyRunning && index === journeyStepIndex ? 'step' : undefined"
                    >
                      <span class="journey-step-number">{{ index + 1 }}</span>
                      <div>
                        <strong>{{ screenName(step.screen_id) }} · {{ journeyComponentLabel(step) }}</strong>
                        <small>{{ step.instruction }}</small>
                      </div>
                      <el-icon v-if="index < journeyStepIndex"><CircleCheck /></el-icon>
                    </li>
                  </ol>

                  <div
                    v-if="journeyFeedback"
                    class="journey-feedback"
                    :class="`feedback-${journeyFeedbackTone}`"
                    :role="journeyFeedbackTone === 'error' ? 'alert' : 'status'"
                    aria-live="polite"
                  >{{ journeyFeedback }}</div>

                  <div class="journey-actions">
                    <el-button type="primary" :icon="VideoPlay" @click="startJourney">
                      {{ journeyRunning ? '重新开始' : completedJourneyId === activeJourney.id ? '再次体验' : '开始体验' }}
                    </el-button>
                    <el-button v-if="journeyRunning" :icon="Position" @click="locateJourneyStep">定位当前步骤</el-button>
                    <el-button v-if="journeyRunning" :icon="Close" @click="stopJourney">退出</el-button>
                  </div>
                </div>
                <el-empty v-else description="当前版本尚未定义可执行体验路径" :image-size="56" />
              </el-tab-pane>

              <el-tab-pane label="Agent" name="agents">
                <div class="agent-run-meta">
                  <span>{{ generationModeLabel(activePrototype.current.generation_mode) }}</span>
                  <span>{{ activePrototype.current.agent_trace.length }} 个协作步骤</span>
                  <span v-if="activePrototype.current.quality.repair_rounds">{{ activePrototype.current.quality.repair_rounds }} 轮自动返修</span>
                  <span v-if="activePrototype.current.quality.deterministic_repairs">{{ activePrototype.current.quality.deterministic_repairs }} 次结构修复</span>
                  <span v-if="activePrototype.current.quality.review_contract_repairs">{{ activePrototype.current.quality.review_contract_repairs }} 次评审校正</span>
                </div>
                <el-collapse accordion class="agent-trace-list">
                  <el-collapse-item v-for="(trace, index) in activePrototype.current.agent_trace" :key="`${trace.role}-${trace.agent_id}-${trace.round ?? 0}-${index}`" :name="`trace-${index}`">
                    <template #title>
                      <span class="trace-avatar">{{ trace.name.slice(0, 1) }}</span>
                      <span class="trace-title"><strong>{{ trace.name }}</strong><small>{{ roleLabel(trace.role) }} · {{ traceStageLabel(trace.stage, trace.round, trace.fallback) }} · {{ trace.model }}</small></span>
                    </template>
                    <pre>{{ trace.output }}</pre>
                  </el-collapse-item>
                </el-collapse>
              </el-tab-pane>

              <el-tab-pane :label="`版本 ${activePrototype.versions.length}`" name="versions">
                <div class="version-history">
                  <article v-for="version in activePrototype.versions" :key="version.id" :class="{ active: version.version === activePrototype.active_version }">
                    <div class="version-marker"><span>v{{ version.version }}</span></div>
                    <div class="version-copy">
                      <div><strong>{{ version.version === activePrototype.active_version ? '当前版本' : `历史版本 v${version.version}` }}</strong><el-tag v-if="version.version === activePrototype.active_version" size="small" type="success">活动</el-tag></div>
                      <span>{{ formatDate(version.created_at) }}</span>
                      <small>{{ generationModeLabel(version.generation_mode) }} · 质量 {{ Math.round(version.quality.score) }}</small>
                    </div>
                    <el-tooltip v-if="canEdit && version.version !== activePrototype.active_version" content="恢复为活动版本" placement="left">
                      <el-button :icon="RefreshLeft" circle aria-label="恢复原型版本" :loading="restoringVersion === version.version" @click="restoreVersion(version.version)" />
                    </el-tooltip>
                  </article>
                </div>
              </el-tab-pane>
            </el-tabs>
          </aside>
        </div>
      </template>
    </div>

    <el-dialog v-model="createDialog" title="生成产品原型" width="min(620px, 94vw)">
      <el-form label-position="top">
        <div class="form-grid-two">
          <el-form-item label="所属项目" required>
            <el-select v-model="createForm.project_id" class="full" placeholder="选择项目" @change="onProjectChange">
              <el-option v-for="project in writableProjects" :key="project.id" :label="project.name" :value="project.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="关联需求">
            <el-select v-model="createForm.requirement_id" clearable class="full" placeholder="不关联需求" @change="onRequirementChange">
              <el-option v-for="item in availableRequirements" :key="item.id" :label="item.title" :value="item.id" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="原型名称" required>
          <el-input v-model="createForm.title" maxlength="200" show-word-limit placeholder="例如：手机号注册与邀请增长原型" />
        </el-form-item>
        <el-form-item label="产品目标与核心流程" required>
          <el-input v-model="createForm.prompt" type="textarea" :rows="7" maxlength="12000" show-word-limit placeholder="描述目标用户、业务目标、关键页面、核心流程和验收要求" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :icon="MagicStick" :loading="creating" :disabled="!canSubmitCreate" @click="generatePrototype">{{ creating ? '正在提交' : '开始生成' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="regenerateDialog" title="重新生成原型" width="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="本轮修改意见">
          <el-input v-model="regenerateFeedback" type="textarea" :rows="6" maxlength="4000" show-word-limit placeholder="例如：增加邀请奖励状态，并将移动端首要操作固定在底部" />
        </el-form-item>
      </el-form>
      <div class="regenerate-note"><el-icon><InfoFilled /></el-icon><span>当前版本会保留，新结果将创建为独立版本。</span></div>
      <template #footer>
        <el-button @click="regenerateDialog = false">取消</el-button>
        <el-button type="primary" :icon="Refresh" :loading="regenerating" @click="regeneratePrototype">{{ regenerating ? '正在提交' : '生成新版本' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="materializationDialog" title="原型交付清单" width="min(860px, 94vw)">
      <template v-if="materialization">
        <div class="materialization-summary">
          <div><span>实现任务</span><strong>{{ materialization.task_ids.length }}</strong></div>
          <div><span>验收用例</span><strong>{{ materialization.test_cases.length }}</strong></div>
          <div><span>原型版本</span><strong>v{{ materialization.prototype_version }}</strong></div>
        </div>
        <el-table :data="materialization.test_cases" class="materialization-table">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="test-case-detail">
                <strong>前置条件</strong><p>{{ row.preconditions }}</p>
                <strong>执行步骤</strong><ol><li v-for="step in row.steps" :key="step">{{ step }}</li></ol>
                <strong>预期结果</strong><p>{{ row.expected_result }}</p>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="验收用例" min-width="260" />
          <el-table-column label="界面" min-width="160"><template #default="{ row }">{{ screenName(row.screen_id) }}</template></el-table-column>
          <el-table-column prop="priority" label="优先级" width="90" />
        </el-table>
      </template>
      <template #footer>
        <el-button @click="materializationDialog = false">关闭</el-button>
        <el-button type="primary" :icon="Tickets" @click="router.push('/tasks')">查看任务看板</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowRight,
  ChatLineRound,
  CircleCheck,
  CircleClose,
  Clock,
  Close,
  Connection,
  Delete,
  Document,
  Download,
  Folder,
  FolderAdd,
  InfoFilled,
  Loading,
  MagicStick,
  MoreFilled,
  Position,
  Plus,
  Refresh,
  RefreshLeft,
  Tickets,
  VideoPlay
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { api, apiBaseURL } from '../api/client'
import type {
  ProductPrototype,
  ProductPrototypeDetail,
  Project,
  PrototypeActionEvent,
  PrototypeGenerationJob,
  PrototypeJourney,
  PrototypeJourneyStep,
  PrototypeMaterialization,
  PrototypeReviewComment,
  PrototypeScreen,
  Requirement
} from '../api/types'
import PrototypeCanvas from '../components/PrototypeCanvas.vue'
import { usePrototypeGenerationStream } from '../composables/usePrototypeGenerationStream'
import { useAuthStore } from '../stores/auth'
import { confirmDestructiveAction } from '../utils/confirm'

type DeviceMode = 'desktop' | 'mobile'
type PrototypeStatus = ProductPrototype['status']

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const prototypes = ref<ProductPrototype[]>([])
const projects = ref<Project[]>([])
const requirements = ref<Requirement[]>([])
const reviewComments = ref<PrototypeReviewComment[]>([])
const activePrototype = ref<ProductPrototypeDetail | null>(null)
const selectedPrototypeId = ref<number | null>(null)
const activeScreenId = ref('')
const screenHistory = ref<string[]>([])
const deviceMode = ref<DeviceMode>('desktop')
const inspectorTab = ref('quality')
const loadingCatalog = ref(true)
const loadingDetail = ref(false)
const createDialog = ref(false)
const creating = ref(false)
const regenerateDialog = ref(false)
const regenerating = ref(false)
const regenerateFeedback = ref('')
const savingStatus = ref(false)
const restoringVersion = ref<number | null>(null)
const commentDraft = ref('')
const commentScreenId = ref('')
const postingComment = ref(false)
const resolvingCommentId = ref<number | null>(null)
const materializing = ref(false)
const materialization = ref<PrototypeMaterialization | null>(null)
const materializationDialog = ref(false)
const canvasSession = ref(0)
const lastInteraction = ref('')
const selectedJourneyId = ref('')
const journeyStepIndex = ref(0)
const journeyRunning = ref(false)
const completedJourneyId = ref('')
const journeyFeedback = ref('')
const journeyFeedbackTone = ref<'info' | 'success' | 'error'>('info')
const cancellingGeneration = ref(false)
const retryingGeneration = ref(false)
const generationConnectionDetail = ref('')
const jobAutoOpen = ref(true)
const handledSuccessfulJobId = ref<number | null>(null)
const prototypeStatuses: PrototypeStatus[] = ['DRAFT', 'REVIEW', 'APPROVED', 'ARCHIVED']
const deviceOptions = [
  { label: '桌面', value: 'desktop' },
  { label: '移动', value: 'mobile' }
]
const createForm = reactive({
  project_id: null as number | null,
  requirement_id: null as number | null,
  title: '',
  prompt: ''
})

const canCreate = computed(() => auth.hasPermission('projects:write'))
const writableProjects = computed(() => projects.value.filter((project) => project.current_user_role !== 'viewer'))
const activeProject = computed(() => projects.value.find((project) => project.id === activePrototype.value?.project_id))
const canEdit = computed(() => canCreate.value && activeProject.value?.current_user_role !== 'viewer')
const activeProjectName = computed(() => activeProject.value?.name || '项目')
const activeRequirementName = computed(() => requirements.value.find((item) => item.id === activePrototype.value?.requirement_id)?.title || '')
const availableRequirements = computed(() => requirements.value.filter((item) => item.project_id === createForm.project_id))
const canSubmitCreate = computed(() => Boolean(
  !creating.value
  && createForm.project_id
  && createForm.title.trim()
  && createForm.prompt.trim().length >= 10
))
const activeScreen = computed<PrototypeScreen | undefined>(() =>
  activePrototype.value?.current.specification.screens.find((screen) => screen.id === activeScreenId.value)
)
const prototypeJourneys = computed(() => activePrototype.value?.current.specification.journeys || [])
const activeJourney = computed<PrototypeJourney | undefined>(() => (
  prototypeJourneys.value.find((journey) => journey.id === selectedJourneyId.value)
  || prototypeJourneys.value[0]
))
const activeJourneyStep = computed(() => (
  journeyRunning.value ? activeJourney.value?.steps[journeyStepIndex.value] : undefined
))
const highlightedJourneyComponentId = computed(() => (
  activeJourneyStep.value?.screen_id === activeScreenId.value
    ? activeJourneyStep.value.component_id
    : undefined
))
const journeyProgress = computed(() => {
  const journey = activeJourney.value
  if (!journey) return 0
  if (completedJourneyId.value === journey.id) return 100
  return Math.round(journeyStepIndex.value / journey.steps.length * 100)
})
const journeyProgressLabel = computed(() => {
  const journey = activeJourney.value
  if (!journey) return ''
  if (completedJourneyId.value === journey.id) return `${journey.steps.length}/${journey.steps.length} 步已完成`
  if (journeyRunning.value) return `步骤 ${journeyStepIndex.value + 1}/${journey.steps.length}`
  return `共 ${journey.steps.length} 步`
})
const openReviewCount = computed(() => reviewComments.value.filter((comment) => comment.status === 'OPEN').length)
const qualityColor = computed(() => {
  const score = activePrototype.value?.current.quality.score || 0
  if (score >= 80) return '#15803d'
  if (score >= 60) return '#b45309'
  return '#b91c1c'
})

const {
  job: generationJob,
  connectionState: generationConnectionState,
  start: startGenerationStream,
  clear: clearGenerationStream,
  dispose: disposeGenerationStream
} = usePrototypeGenerationStream({
  onJob: handleGenerationJob,
  onConnectionState: (state, detail) => {
    generationConnectionDetail.value = state === 'reconnecting' && detail?.retryInMs
      ? `${Math.max(1, Math.ceil(detail.retryInMs / 1000))} 秒后重连`
      : ''
  }
})

const generationActive = computed(() => Boolean(
  generationJob.value && ['QUEUED', 'RUNNING', 'CANCELLING'].includes(generationJob.value.status)
))
const generationTerminal = computed(() => Boolean(
  generationJob.value && ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(generationJob.value.status)
))
const canControlGenerationJob = computed(() => Boolean(
  generationJob.value
  && canCreate.value
  && writableProjects.value.some((project) => project.id === generationJob.value?.project_id)
))
const currentGenerationStage = computed(() => {
  const stages = generationJob.value?.stage_history || []
  return [...stages].reverse().find((stage) => stage.status === 'RUNNING') || stages[stages.length - 1]
})
const generationProgressStatus = computed<'success' | 'exception' | 'warning' | undefined>(() => {
  if (generationJob.value?.status === 'SUCCEEDED') return 'success'
  if (generationJob.value?.status === 'FAILED') return 'exception'
  if (generationJob.value?.status === 'CANCELLED') return 'warning'
  return undefined
})
const generationConnectionNotice = computed(() => {
  if (!generationActive.value) return ''
  if (generationConnectionState.value === 'reconnecting') {
    return `进度连接已中断，任务仍在后台运行。${generationConnectionDetail.value}`
  }
  if (generationConnectionState.value === 'connecting' || generationConnectionState.value === 'loading_snapshot') {
    return '正在连接后台任务，生成不会因刷新页面而中断。'
  }
  return ''
})
const generationStatusDescription = computed(() => {
  if (generationJob.value?.status === 'QUEUED') return '任务已进入队列，正在等待可用的 Agent 执行资源。'
  if (generationJob.value?.status === 'CANCELLING') return '取消请求已收到，当前 Agent 步骤结束后将安全停止。'
  if (generationJob.value?.status === 'SUCCEEDED') return '原型已通过多 Agent 生成与质量门禁。'
  if (generationJob.value?.status === 'FAILED') return '后台任务执行失败，可查看原因并重试。'
  if (generationJob.value?.status === 'CANCELLED') return '任务已取消，未发布不完整的原型版本。'
  return '产品经理、交互架构师和测试工程师正在协同执行。'
})
const generationHeadline = computed(() => {
  if (!generationJob.value) return ''
  if (generationJob.value.status === 'SUCCEEDED') {
    return generationJob.value.operation === 'CREATE' ? '产品原型已生成' : '新版本已生成'
  }
  if (generationJob.value.status === 'FAILED') return '原型生成失败'
  if (generationJob.value.status === 'CANCELLED') return '原型生成已取消'
  if (generationJob.value.status === 'CANCELLING') return '正在安全取消原型生成'
  return generationJob.value.operation === 'CREATE' ? 'AI 团队正在生成产品原型' : 'AI 团队正在生成新版本'
})

function summaryFromDetail(detail: ProductPrototypeDetail): ProductPrototype {
  return {
    id: detail.id,
    project_id: detail.project_id,
    requirement_id: detail.requirement_id,
    created_by_user_id: detail.created_by_user_id,
    title: detail.title,
    summary: detail.summary,
    status: detail.status,
    active_version: detail.active_version,
    screen_count: detail.screen_count,
    quality_score: detail.quality_score,
    created_at: detail.created_at,
    updated_at: detail.updated_at
  }
}

function mergePrototypeSummary(detail: ProductPrototypeDetail) {
  const summary = summaryFromDetail(detail)
  const index = prototypes.value.findIndex((item) => item.id === detail.id)
  if (index >= 0) prototypes.value.splice(index, 1, summary)
  else prototypes.value.unshift(summary)
}

async function loadReviewComments(prototypeId: number, version: number) {
  const { data } = await api.get<PrototypeReviewComment[]>(`/prototypes/${prototypeId}/comments`, {
    params: { version }
  })
  reviewComments.value = data
}

function generationJobUrls(jobId: number) {
  const snapshotUrl = `${apiBaseURL}/prototypes/generation-jobs/${jobId}`
  return { snapshotUrl, eventsUrl: `${snapshotUrl}/events` }
}

function newRequestId() {
  return globalThis.crypto?.randomUUID?.() || `prototype-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function showGenerationJob(job: PrototypeGenerationJob, autoOpen = true) {
  jobAutoOpen.value = autoOpen
  if (job.status !== 'SUCCEEDED') handledSuccessfulJobId.value = null
  await startGenerationStream({ ...generationJobUrls(job.job_id), initialSnapshot: job })
  if (String(route.query.generation_job || '') !== String(job.job_id)) {
    await router.replace({ query: { ...route.query, generation_job: String(job.job_id) } })
  }
}

async function refreshPrototypeCatalog() {
  const { data } = await api.get<ProductPrototype[]>('/prototypes')
  prototypes.value = data
}

async function finishGenerationJob(job: PrototypeGenerationJob) {
  if (!job.result_prototype_id) return
  await refreshPrototypeCatalog()
  const stillFocused = jobAutoOpen.value && generationJob.value?.job_id === job.job_id
  if (stillFocused) {
    await openPrototype(job.result_prototype_id)
    if (job.operation === 'REGENERATE') inspectorTab.value = 'versions'
  }
  ElMessage.success(job.operation === 'CREATE'
    ? '可交互原型已在后台生成完成'
    : `原型 v${job.result_version || ''} 已生成`)
}

function handleGenerationJob(job: PrototypeGenerationJob) {
  if (job.status !== 'SUCCEEDED' || handledSuccessfulJobId.value === job.job_id) return
  handledSuccessfulJobId.value = job.job_id
  void finishGenerationJob(job)
}

async function resumeGenerationJob(queryJobId: number | null, activeJobs: PrototypeGenerationJob[]) {
  let job = activeJobs[0]
  if (queryJobId) {
    try {
      const { data } = await api.get<PrototypeGenerationJob>(`/prototypes/generation-jobs/${queryJobId}`, {
        suppressErrorToast: true
      })
      job = data
    } catch {
      const query = { ...route.query }
      delete query.generation_job
      await router.replace({ query })
    }
  }
  if (job) await showGenerationJob(job, true)
}

async function loadCatalog() {
  loadingCatalog.value = true
  try {
    const [prototypeResponse, projectResponse, requirementResponse, generationResponse] = await Promise.all([
      api.get<ProductPrototype[]>('/prototypes'),
      api.get<Project[]>('/projects'),
      api.get<Requirement[]>('/requirements'),
      api.get<PrototypeGenerationJob[]>('/prototypes/generation-jobs', {
        params: { active: true },
        suppressErrorToast: true
      }).catch(() => ({ data: [] as PrototypeGenerationJob[] }))
    ])
    prototypes.value = prototypeResponse.data
    projects.value = projectResponse.data
    requirements.value = requirementResponse.data
    const queryId = Number(route.query.prototype)
    const initialId = prototypes.value.some((item) => item.id === queryId) ? queryId : prototypes.value[0]?.id
    if (initialId) await openPrototype(initialId)
    await resumeGenerationJob(Number(route.query.generation_job) || null, generationResponse.data)
  } finally {
    loadingCatalog.value = false
  }
}

function resetJourneyState(detail: ProductPrototypeDetail | null = activePrototype.value) {
  selectedJourneyId.value = detail?.current.specification.journeys?.[0]?.id || ''
  journeyStepIndex.value = 0
  journeyRunning.value = false
  completedJourneyId.value = ''
  journeyFeedback.value = ''
  journeyFeedbackTone.value = 'info'
}

async function openPrototype(id: number, syncRoute = true) {
  if (!id) return
  loadingDetail.value = true
  selectedPrototypeId.value = id
  try {
    const { data } = await api.get<ProductPrototypeDetail>(`/prototypes/${id}`)
    activePrototype.value = data
    activeScreenId.value = data.current.specification.start_screen_id
    commentScreenId.value = activeScreenId.value
    screenHistory.value = []
    lastInteraction.value = ''
    materialization.value = null
    canvasSession.value += 1
    resetJourneyState(data)
    mergePrototypeSummary(data)
    await loadReviewComments(data.id, data.active_version)
    if (syncRoute && String(route.query.prototype || '') !== String(id)) {
      await router.replace({ query: { ...route.query, prototype: String(id) } })
    }
  } finally {
    loadingDetail.value = false
  }
}

function selectPrototype(value: unknown) {
  const id = Number(value)
  if (id && id !== activePrototype.value?.id) {
    jobAutoOpen.value = false
    void openPrototype(id)
  }
}

function navigateScreen(screenId: string) {
  if (!activePrototype.value || screenId === activeScreenId.value) return
  if (!activePrototype.value.current.specification.screens.some((screen) => screen.id === screenId)) return
  if (activeScreenId.value) screenHistory.value.push(activeScreenId.value)
  activeScreenId.value = screenId
  commentScreenId.value = screenId
  if (journeyRunning.value && activeJourneyStep.value) {
    lastInteraction.value = `路径步骤 ${journeyStepIndex.value + 1}：${activeJourneyStep.value.instruction}`
  } else if (activeJourney.value && completedJourneyId.value === activeJourney.value.id) {
    lastInteraction.value = `路径已完成：${activeJourney.value.name}`
  } else {
    lastInteraction.value = ''
  }
}

function navigateBack() {
  const previous = screenHistory.value.pop()
  if (previous) activeScreenId.value = previous
  else if (activePrototype.value) activeScreenId.value = activePrototype.value.current.specification.start_screen_id
  commentScreenId.value = activeScreenId.value
}

function resetCanvas() {
  canvasSession.value += 1
  screenHistory.value = []
  if (journeyRunning.value && activeJourneyStep.value) {
    activeScreenId.value = activeJourneyStep.value.screen_id
    commentScreenId.value = activeScreenId.value
    journeyFeedback.value = `交互状态已重置，请继续：${activeJourneyStep.value.instruction}`
    journeyFeedbackTone.value = 'info'
  }
  lastInteraction.value = '交互状态已重置'
}

function selectJourney(value: unknown) {
  selectedJourneyId.value = String(value || '')
  journeyStepIndex.value = 0
  journeyRunning.value = false
  completedJourneyId.value = ''
  journeyFeedback.value = ''
  journeyFeedbackTone.value = 'info'
  lastInteraction.value = ''
}

function startJourney() {
  const journey = activeJourney.value
  if (!journey) return
  selectedJourneyId.value = journey.id
  journeyStepIndex.value = 0
  journeyRunning.value = true
  completedJourneyId.value = ''
  journeyFeedbackTone.value = 'info'
  journeyFeedback.value = `步骤 1：${journey.steps[0].instruction}`
  canvasSession.value += 1
  screenHistory.value = []
  activeScreenId.value = journey.steps[0].screen_id
  commentScreenId.value = activeScreenId.value
  lastInteraction.value = `路径步骤 1：${journey.steps[0].instruction}`
}

function stopJourney() {
  journeyRunning.value = false
  journeyStepIndex.value = 0
  completedJourneyId.value = ''
  journeyFeedbackTone.value = 'info'
  journeyFeedback.value = '已退出引导，可继续自由体验原型。'
  lastInteraction.value = ''
}

function locateJourneyStep() {
  const step = activeJourneyStep.value
  if (!step) return
  if (step.screen_id !== activeScreenId.value) navigateScreen(step.screen_id)
  journeyFeedbackTone.value = 'info'
  journeyFeedback.value = `已定位当前步骤：${step.instruction}`
  lastInteraction.value = `路径步骤 ${journeyStepIndex.value + 1}：${step.instruction}`
}

function journeyComponentLabel(step: PrototypeJourneyStep) {
  const screen = activePrototype.value?.current.specification.screens.find(
    (item) => item.id === step.screen_id
  )
  const component = screen?.sections
    .flatMap((section) => section.components)
    .find((item) => item.id === step.component_id)
  return component?.label || component?.text || step.component_id
}

function handlePrototypeAction(event: PrototypeActionEvent) {
  const journey = activeJourney.value
  const step = activeJourneyStep.value
  if (!journey || !step) return
  if (event.screen_id !== step.screen_id || event.component_id !== step.component_id) {
    journeyFeedbackTone.value = 'error'
    journeyFeedback.value = `当前需要在${screenName(step.screen_id)}触发“${journeyComponentLabel(step)}”。`
    lastInteraction.value = `路径步骤 ${journeyStepIndex.value + 1}：${step.instruction}`
    return
  }

  journeyStepIndex.value += 1
  if (journeyStepIndex.value >= journey.steps.length) {
    journeyRunning.value = false
    completedJourneyId.value = journey.id
    journeyFeedbackTone.value = 'success'
    journeyFeedback.value = `路径体验完成：${journey.goal}`
    lastInteraction.value = `路径已完成：${journey.name}`
    return
  }

  const nextStep = journey.steps[journeyStepIndex.value]
  journeyFeedbackTone.value = 'success'
  journeyFeedback.value = `第 ${journeyStepIndex.value} 步已完成。下一步：${nextStep.instruction}`
  lastInteraction.value = `路径步骤 ${journeyStepIndex.value + 1}：${nextStep.instruction}`
}

function openCreateDialog() {
  const project = writableProjects.value[0]
  Object.assign(createForm, {
    project_id: project?.id || null,
    requirement_id: null,
    title: '',
    prompt: ''
  })
  createDialog.value = true
}

function onProjectChange() {
  if (!availableRequirements.value.some((item) => item.id === createForm.requirement_id)) {
    createForm.requirement_id = null
  }
}

function onRequirementChange(value: unknown) {
  const requirement = requirements.value.find((item) => item.id === Number(value))
  if (!requirement) return
  createForm.title = `${requirement.title} - 产品原型`
  createForm.prompt = [requirement.content, requirement.analysis].filter(Boolean).join('\n\n')
}

async function generatePrototype() {
  if (!canSubmitCreate.value || !createForm.project_id) return
  creating.value = true
  try {
    const { data } = await api.post<PrototypeGenerationJob>('/prototypes/generation-jobs', {
      request_id: newRequestId(),
      project_id: createForm.project_id,
      requirement_id: createForm.requirement_id,
      title: createForm.title.trim(),
      prompt: createForm.prompt.trim()
    })
    createDialog.value = false
    await showGenerationJob(data, true)
    ElMessage.success('生成任务已进入后台队列')
  } finally {
    creating.value = false
  }
}

function openRegenerateDialog() {
  regenerateFeedback.value = ''
  regenerateDialog.value = true
}

async function regeneratePrototype() {
  if (!activePrototype.value) return
  regenerating.value = true
  try {
    const { data } = await api.post<PrototypeGenerationJob>(`/prototypes/${activePrototype.value.id}/generation-jobs`, {
      request_id: newRequestId(),
      feedback: regenerateFeedback.value.trim()
    })
    regenerateDialog.value = false
    await showGenerationJob(data, true)
    ElMessage.success('新版本生成任务已进入后台队列')
  } finally {
    regenerating.value = false
  }
}

async function cancelGeneration() {
  if (!generationJob.value || !generationActive.value) return
  cancellingGeneration.value = true
  try {
    const { data } = await api.post<PrototypeGenerationJob>(
      `/prototypes/generation-jobs/${generationJob.value.job_id}/cancel`
    )
    await showGenerationJob(data, jobAutoOpen.value)
  } finally {
    cancellingGeneration.value = false
  }
}

async function retryGeneration() {
  if (!generationJob.value || !generationJob.value.retryable) return
  retryingGeneration.value = true
  try {
    const { data } = await api.post<PrototypeGenerationJob>(
      `/prototypes/generation-jobs/${generationJob.value.job_id}/retry`
    )
    handledSuccessfulJobId.value = null
    await showGenerationJob(data, true)
    ElMessage.success('任务已重新进入队列')
  } finally {
    retryingGeneration.value = false
  }
}

async function dismissGenerationJob() {
  clearGenerationStream()
  const query = { ...route.query }
  delete query.generation_job
  await router.replace({ query })
}

async function updateStatus(value: unknown) {
  if (!activePrototype.value) return
  savingStatus.value = true
  try {
    const { data } = await api.patch<ProductPrototypeDetail>(`/prototypes/${activePrototype.value.id}`, { status: value })
    activePrototype.value = data
    mergePrototypeSummary(data)
    ElMessage.success(`原型状态已更新为${statusLabel(data.status)}`)
  } finally {
    savingStatus.value = false
  }
}

async function restoreVersion(version: number) {
  if (!activePrototype.value || version === activePrototype.value.active_version) return
  restoringVersion.value = version
  try {
    const { data } = await api.post<ProductPrototypeDetail>(`/prototypes/${activePrototype.value.id}/versions/${version}/activate`)
    activePrototype.value = data
    mergePrototypeSummary(data)
    activeScreenId.value = data.current.specification.start_screen_id
    commentScreenId.value = activeScreenId.value
    screenHistory.value = []
    canvasSession.value += 1
    resetJourneyState(data)
    materialization.value = null
    await loadReviewComments(data.id, data.active_version)
    ElMessage.success(`已恢复原型 v${version}`)
  } finally {
    restoringVersion.value = null
  }
}

function screenName(screenId: string) {
  return activePrototype.value?.current.specification.screens.find((screen) => screen.id === screenId)?.name || screenId
}

async function addReviewComment() {
  if (!activePrototype.value || !commentDraft.value.trim()) return
  postingComment.value = true
  try {
    const approvalRevoked = activePrototype.value.status === 'APPROVED'
    const { data } = await api.post<PrototypeReviewComment>(`/prototypes/${activePrototype.value.id}/comments`, {
      screen_id: commentScreenId.value || null,
      body: commentDraft.value.trim()
    })
    reviewComments.value.unshift(data)
    commentDraft.value = ''
    if (approvalRevoked) {
      activePrototype.value.status = 'REVIEW'
      mergePrototypeSummary(activePrototype.value)
      ElMessage.warning('评审评论已添加，原型已回到评审中')
    } else {
      ElMessage.success('评审评论已添加')
    }
  } finally {
    postingComment.value = false
  }
}

async function resolveReviewComment(commentId: number) {
  if (!activePrototype.value) return
  resolvingCommentId.value = commentId
  try {
    const { data } = await api.patch<PrototypeReviewComment>(`/prototypes/${activePrototype.value.id}/comments/${commentId}`, {
      status: 'RESOLVED'
    })
    const index = reviewComments.value.findIndex((comment) => comment.id === commentId)
    if (index >= 0) reviewComments.value.splice(index, 1, data)
    ElMessage.success('评审评论已解决')
  } finally {
    resolvingCommentId.value = null
  }
}

async function materializePrototype() {
  if (!activePrototype.value) return
  materializing.value = true
  try {
    const { data } = await api.post<PrototypeMaterialization>(`/prototypes/${activePrototype.value.id}/materialize`, {
      request_id: crypto.randomUUID()
    })
    materialization.value = data
    materializationDialog.value = true
    ElMessage.success(`已生成 ${data.task_ids.length} 个任务和 ${data.test_cases.length} 条验收用例`)
  } finally {
    materializing.value = false
  }
}

function exportPrototype() {
  if (!activePrototype.value) return
  const blob = new Blob([JSON.stringify(activePrototype.value.current.specification, null, 2)], { type: 'application/json' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `prototype-${activePrototype.value.id}-v${activePrototype.value.active_version}.json`
  link.click()
  URL.revokeObjectURL(link.href)
}

async function deletePrototype() {
  if (!activePrototype.value) return
  if (!await confirmDestructiveAction('删除后所有原型版本都会永久移除，确认继续吗？', '删除产品原型')) return
  const id = activePrototype.value.id
  await api.delete(`/prototypes/${id}`)
  prototypes.value = prototypes.value.filter((item) => item.id !== id)
  activePrototype.value = null
  selectedPrototypeId.value = null
  const next = prototypes.value[0]
  if (next) await openPrototype(next.id)
  else await router.replace({ query: {} })
  ElMessage.success('产品原型已删除')
}

function handleMoreCommand(command: string | number | object) {
  if (command === 'export') exportPrototype()
  if (command === 'delete') void deletePrototype()
}

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function statusLabel(status: string) {
  return { DRAFT: '草案', REVIEW: '评审中', APPROVED: '已批准', ARCHIVED: '已归档' }[status] || status
}

function statusTagType(status: string) {
  return { DRAFT: 'info', REVIEW: 'warning', APPROVED: 'success', ARCHIVED: 'info' }[status] as 'success' | 'warning' | 'info' | undefined
}

function layoutLabel(layout: string) {
  return { auth: '认证流程', app: '应用界面', dashboard: '数据看板', form: '表单流程', list: '列表界面' }[layout] || layout
}

function qualityCheckLabel(name: string) {
  return {
    navigation_integrity: '导航完整性',
    interactive_paths: '交互路径',
    screen_action_coverage: '界面操作覆盖',
    journey_coverage: '用户旅程覆盖',
    primary_actions: '主要操作',
    visible_form_labels: '表单可访问性',
    responsive_contract: '响应式结构',
    agent_review: '测试 Agent 评审'
  }[name] || name
}

function roleLabel(role: string) {
  return { product_manager: '产品定义', architect: '交互架构', test_engineer: '质量评审', quality_gate: '确定性门禁' }[role] || role
}

function traceStageLabel(stage?: string, round = 0, fallback = false) {
  if (fallback) return '安全模板复审'
  if (stage === 'architecture_repair') return `第 ${round} 轮返修`
  if (stage === 'deterministic_repair') return '结构修复'
  if (stage === 'quality_review_repair') return '评审契约校正'
  if (stage === 'quality_review') return round ? `第 ${round} 轮复审` : '首次评审'
  if (stage === 'product_definition') return '产品定义'
  if (stage === 'architecture') return '首次生成'
  if (stage === 'queued') return '等待执行'
  if (stage === 'persisting') return '发布原型版本'
  if (stage === 'completed') return '生成完成'
  if (stage === 'failed') return '执行失败'
  if (stage === 'cancelled') return '任务已取消'
  return '协作执行'
}

function generationStageLabel(stage?: string, round = 0) {
  return traceStageLabel(stage, round)
}

function generationStageRoleLabel(role?: string | null) {
  return role ? `${roleLabel(role)} Agent` : '多 Agent 编排器'
}

function generationStatusLabel(status: PrototypeGenerationJob['status']) {
  return {
    QUEUED: '等待执行',
    RUNNING: '执行中',
    SUCCEEDED: '已完成',
    FAILED: '执行失败',
    CANCELLING: '正在取消',
    CANCELLED: '已取消'
  }[status]
}

function generationStatusTag(status: PrototypeGenerationJob['status']) {
  return {
    QUEUED: 'info',
    RUNNING: 'primary',
    SUCCEEDED: 'success',
    FAILED: 'danger',
    CANCELLING: 'warning',
    CANCELLED: 'warning'
  }[status] as 'success' | 'warning' | 'info' | 'primary' | 'danger'
}

function generationModeLabel(mode: string) {
  return {
    MULTI_AGENT: '多 Agent 生成',
    MULTI_AGENT_REPAIRED: '多 Agent 自动返修通过',
    MULTI_AGENT_REVIEW_REQUIRED: '多 Agent 生成 · 需要人工评审',
    MULTI_AGENT_TEMPLATE_FALLBACK: '多 Agent + 安全模板'
  }[mode] || mode
}

watch(() => route.query.prototype, (value) => {
  const id = Number(value)
  if (id && id !== activePrototype.value?.id && prototypes.value.some((item) => item.id === id)) {
    void openPrototype(id, false)
  }
})

watch(() => route.query.generation_job, (value) => {
  const jobId = Number(value)
  if (jobId && jobId !== generationJob.value?.job_id) {
    jobAutoOpen.value = true
    handledSuccessfulJobId.value = null
    void startGenerationStream(generationJobUrls(jobId))
  }
})

onMounted(loadCatalog)
onBeforeUnmount(disposeGenerationStream)
</script>

<style scoped>
.prototype-studio-page {
  max-width: 1480px;
}

.studio-page-head {
  margin-bottom: 16px;
}

.generation-job-band {
  display: grid;
  gap: 12px;
  margin-bottom: 16px;
  padding: 16px 18px;
  border: 1px solid #bfdbfe;
  border-left: 4px solid var(--color-primary);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.generation-job-band.job-succeeded {
  border-color: #bbf7d0;
  border-left-color: var(--color-success);
}

.generation-job-band.job-failed {
  border-color: #fecaca;
  border-left-color: var(--color-danger);
}

.generation-job-band.job-cancelled,
.generation-job-band.job-cancelling {
  border-color: #fed7aa;
  border-left-color: var(--color-warning);
}

.generation-job-head,
.generation-job-title,
.generation-job-actions,
.generation-job-current,
.generation-connection-notice {
  display: flex;
  align-items: center;
}

.generation-job-head,
.generation-job-current {
  justify-content: space-between;
  gap: 16px;
}

.generation-job-title {
  min-width: 0;
  gap: 10px;
}

.generation-job-title > div,
.generation-job-current > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.generation-job-title strong {
  font-size: 14px;
}

.generation-job-title span,
.generation-job-current span,
.generation-connection-notice,
.generation-job-error {
  color: var(--color-secondary-text);
  font-size: 12px;
  line-height: 1.5;
}

.job-state-icon {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  place-items: center;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 18px;
}

.job-succeeded .job-state-icon {
  background: #f0fdf4;
  color: var(--color-success);
}

.job-failed .job-state-icon {
  background: #fef2f2;
  color: var(--color-danger);
}

.generation-job-actions {
  flex: 0 0 auto;
  gap: 8px;
}

.generation-job-current strong {
  font-size: 12px;
}

.generation-job-current > span {
  flex: 0 0 auto;
  color: var(--color-muted-text);
  font-variant-numeric: tabular-nums;
}

.generation-connection-notice {
  gap: 7px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: #fff7ed;
  color: #9a3412;
}

.generation-job-error {
  margin: 0;
  padding: 9px 11px;
  overflow-wrap: anywhere;
  border-radius: var(--radius-md);
  background: #fef2f2;
  color: var(--color-danger);
}

.generation-stage-history {
  border-top: 1px solid var(--color-border);
  padding-top: 10px;
}

.generation-stage-history summary {
  display: flex;
  width: fit-content;
  min-height: 44px;
  align-items: center;
  color: var(--color-secondary-text);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}

.generation-stage-history ol {
  display: grid;
  gap: 0;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.generation-stage-history li {
  display: grid;
  min-height: 42px;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  border-bottom: 1px solid var(--color-border);
}

.generation-stage-history li:last-child {
  border-bottom: 0;
}

.stage-marker {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border-radius: 50%;
  background: var(--color-surface-subtle);
  color: var(--color-muted-text);
}

.stage-completed .stage-marker {
  background: #f0fdf4;
  color: var(--color-success);
}

.stage-running .stage-marker {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.stage-failed .stage-marker {
  background: #fef2f2;
  color: var(--color-danger);
}

.generation-stage-history li > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.generation-stage-history strong {
  font-size: 11px;
}

.generation-stage-history span,
.generation-stage-history small {
  color: var(--color-muted-text);
  font-size: 10px;
}

.generation-stage-history small {
  font-variant-numeric: tabular-nums;
}

.studio-head-actions,
.prototype-summary-actions,
.prototype-context,
.prototype-title-row,
.agent-run-meta {
  display: flex;
  align-items: center;
}

.studio-head-actions,
.prototype-summary-actions {
  gap: 8px;
}

.prototype-switcher {
  width: min(340px, 36vw);
}

.studio-content {
  min-height: 520px;
}

.studio-empty {
  display: grid;
  min-height: 520px;
  place-items: center;
  border-block: 1px solid var(--color-border);
}

.prototype-summary-band {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 0 20px;
  border-block: 1px solid var(--color-border);
}

.prototype-heading {
  min-width: 0;
}

.prototype-title-row {
  flex-wrap: wrap;
  gap: 8px;
}

.prototype-title-row h2 {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 21px;
  line-height: 1.35;
}

.version-label {
  color: var(--color-muted-text);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.prototype-heading > p {
  max-width: 900px;
  margin: 8px 0 10px;
  color: var(--color-secondary-text);
  line-height: 1.6;
}

.prototype-context {
  flex-wrap: wrap;
  gap: 8px 16px;
  color: var(--color-muted-text);
  font-size: 12px;
}

.prototype-context span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.prototype-summary-actions {
  flex: 0 0 auto;
}

.studio-shell {
  display: grid;
  min-height: 760px;
  grid-template-columns: 190px minmax(540px, 1fr) 286px;
  gap: 16px;
  padding-top: 16px;
}

.screen-navigator,
.prototype-inspector,
.preview-workbench {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.screen-navigator,
.prototype-inspector {
  align-self: start;
}

.prototype-inspector {
  max-height: 760px;
  overflow-y: auto;
}

.panel-heading {
  display: flex;
  min-height: 48px;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  border-bottom: 1px solid var(--color-border);
}

.panel-heading strong {
  font-size: 13px;
}

.panel-heading span {
  display: grid;
  min-width: 24px;
  height: 22px;
  place-items: center;
  border-radius: 11px;
  background: var(--color-surface-subtle);
  color: var(--color-muted-text);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.screen-list {
  display: grid;
  gap: 3px;
  padding: 7px;
}

.screen-list button {
  display: grid;
  width: 100%;
  min-height: 58px;
  grid-template-columns: 26px minmax(0, 1fr) 16px;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 0;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-secondary-text);
  text-align: left;
  cursor: pointer;
  transition: background-color 180ms ease, color 180ms ease;
}

.screen-list button:hover {
  background: #f3f4f6;
  color: var(--color-foreground);
}

.screen-list button.active {
  background: var(--color-primary-soft);
  color: #1d4ed8;
}

.screen-list button > span {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-muted-text);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.screen-list button.active > span {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
}

.screen-list button div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.screen-list button strong,
.screen-list button small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.screen-list button strong {
  font-size: 12px;
}

.screen-list button small {
  color: var(--color-muted-text);
  font-size: 10px;
}

.screen-list button > .el-icon {
  opacity: 0;
}

.screen-list button.active > .el-icon {
  opacity: 1;
}

.preview-workbench {
  display: flex;
  min-height: 760px;
  flex-direction: column;
}

.preview-toolbar {
  display: flex;
  min-height: 52px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 7px 10px 7px 14px;
  border-bottom: 1px solid var(--color-border);
}

.preview-toolbar > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.preview-toolbar strong {
  font-size: 13px;
}

.preview-toolbar span {
  overflow: hidden;
  color: var(--color-muted-text);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-stage {
  display: flex;
  min-width: 0;
  flex: 1;
  justify-content: center;
  padding: 16px;
  overflow: auto;
  background: #eef1f5;
}

.preview-mobile {
  align-items: flex-start;
  padding: 24px 16px;
}

.device-frame {
  width: 100%;
  min-width: 0;
  overflow: hidden;
  border: 1px solid #cbd5e1;
  background: #fff;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.09);
}

.device-desktop {
  border-radius: 7px;
}

.device-mobile {
  width: min(390px, 100%);
  flex: 0 0 auto;
  padding: 0 7px 9px;
  border: 7px solid #1f2937;
  border-radius: 26px;
  background: #1f2937;
}

.mobile-frame-top {
  display: grid;
  height: 23px;
  place-items: center;
  background: #1f2937;
}

.mobile-frame-top span {
  width: 68px;
  height: 5px;
  border-radius: 3px;
  background: #64748b;
}

.device-mobile :deep(.prototype-runtime) {
  border-radius: 14px;
}

.inspector-status {
  display: flex;
  min-height: 60px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-border);
}

.inspector-status > div {
  display: grid;
  gap: 2px;
}

.inspector-status small {
  color: var(--color-muted-text);
  font-size: 10px;
}

.inspector-status strong {
  font-size: 13px;
}

.inspector-status .el-select {
  width: 108px;
}

.prototype-inspector :deep(.el-tabs__header) {
  margin: 0;
}

.prototype-inspector :deep(.el-tabs__content) {
  padding: 14px;
}

.quality-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border);
}

.quality-summary > div:last-child {
  display: grid;
  gap: 5px;
}

.quality-summary strong {
  font-size: 13px;
}

.quality-summary span {
  color: var(--color-muted-text);
  font-size: 11px;
  line-height: 1.45;
}

.quality-checks {
  display: grid;
  gap: 0;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}

.quality-checks li {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 8px;
  padding: 9px 0;
  border-bottom: 1px solid var(--color-border);
}

.quality-checks .el-icon {
  margin-top: 1px;
  color: var(--color-success);
}

.quality-checks li.failed .el-icon {
  color: var(--color-danger);
}

.quality-checks li div {
  display: grid;
  gap: 2px;
}

.quality-checks strong {
  font-size: 11px;
}

.quality-checks span {
  color: var(--color-muted-text);
  font-size: 10px;
  line-height: 1.45;
}

.reviewer-summary {
  margin-top: 12px;
  padding: 11px 12px;
  border-left: 3px solid var(--color-primary);
  border-radius: var(--radius-sm);
  background: var(--color-primary-soft);
}

.reviewer-summary strong {
  font-size: 11px;
}

.reviewer-summary p {
  max-height: 220px;
  margin: 5px 0 0;
  overflow-y: auto;
  color: var(--color-secondary-text);
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.review-composer {
  display: grid;
  gap: 8px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border);
}

.review-composer .el-button {
  width: 100%;
}

.review-comment-list {
  display: grid;
}

.review-comment-list article {
  padding: 11px 0;
  border-bottom: 1px solid var(--color-border);
}

.review-comment-list article.resolved {
  opacity: 0.66;
}

.review-comment-head,
.review-comment-head > div {
  display: flex;
}

.review-comment-head {
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.review-comment-head > div {
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.review-comment-head strong {
  font-size: 11px;
}

.review-comment-head span {
  overflow: hidden;
  color: var(--color-muted-text);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-comment-list p {
  margin: 7px 0 2px;
  color: var(--color-secondary-text);
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.journey-panel {
  display: grid;
  gap: 12px;
}

.journey-panel > .el-select {
  width: 100%;
}

.journey-panel :deep(.el-select__wrapper) {
  min-height: 40px;
}

.journey-summary {
  display: grid;
  gap: 7px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border);
}

.journey-summary > div {
  display: grid;
  gap: 3px;
}

.journey-summary strong {
  font-size: 13px;
}

.journey-summary span,
.journey-summary small {
  color: var(--color-muted-text);
  font-size: 11px;
  line-height: 1.5;
}

.journey-summary small {
  font-variant-numeric: tabular-nums;
}

.journey-step-list {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

.journey-step-list li {
  display: grid;
  min-width: 0;
  grid-template-columns: 24px minmax(0, 1fr) 16px;
  align-items: start;
  gap: 8px;
  padding: 10px 8px;
  border-bottom: 1px solid var(--color-border);
}

.journey-step-list li.current {
  border-left: 3px solid var(--color-primary);
  background: var(--color-primary-soft);
}

.journey-step-number {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border-radius: 50%;
  background: #eef1f5;
  color: var(--color-secondary-text);
  font-size: 10px;
  font-weight: 750;
}

.journey-step-list li.current .journey-step-number {
  background: var(--color-primary);
  color: #fff;
}

.journey-step-list li.completed .journey-step-number {
  background: var(--color-success);
  color: #fff;
}

.journey-step-list li > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.journey-step-list strong,
.journey-step-list small {
  overflow-wrap: anywhere;
}

.journey-step-list strong {
  font-size: 11px;
  line-height: 1.45;
}

.journey-step-list small {
  color: var(--color-muted-text);
  font-size: 11px;
  line-height: 1.5;
}

.journey-step-list .el-icon {
  margin-top: 3px;
  color: var(--color-success);
}

.journey-feedback {
  padding: 9px 10px;
  border-left: 3px solid var(--color-primary);
  background: var(--color-primary-soft);
  color: var(--color-secondary-text);
  font-size: 11px;
  line-height: 1.55;
}

.journey-feedback.feedback-success {
  border-left-color: var(--color-success);
  background: #f0fdf4;
}

.journey-feedback.feedback-error {
  border-left-color: var(--color-danger);
  background: #fef2f2;
}

.journey-actions {
  display: grid;
  gap: 7px;
}

.journey-actions .el-button {
  width: 100%;
  min-height: 40px;
  margin-left: 0;
}

.materialization-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 16px;
  border-block: 1px solid var(--color-border);
}

.materialization-summary > div {
  display: grid;
  gap: 4px;
  padding: 14px 16px;
  border-right: 1px solid var(--color-border);
}

.materialization-summary > div:last-child {
  border-right: 0;
}

.materialization-summary span {
  color: var(--color-muted-text);
  font-size: 11px;
}

.materialization-summary strong {
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}

.materialization-table {
  width: 100%;
}

.test-case-detail {
  padding: 4px 18px 10px;
}

.test-case-detail strong {
  font-size: 12px;
}

.test-case-detail p,
.test-case-detail ol {
  margin: 5px 0 12px;
  color: var(--color-secondary-text);
  font-size: 12px;
  line-height: 1.6;
}

.test-case-detail ol {
  padding-left: 20px;
}

.agent-run-meta {
  justify-content: space-between;
  margin-bottom: 8px;
  color: var(--color-muted-text);
  font-size: 10px;
}

.agent-trace-list {
  border-top: 0;
}

.agent-trace-list :deep(.el-collapse-item__header) {
  min-height: 58px;
  line-height: 1.2;
}

.agent-trace-list :deep(.el-collapse-item__content) {
  padding-bottom: 10px;
}

.trace-avatar {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  place-items: center;
  margin-right: 8px;
  border-radius: var(--radius-md);
  background: #eef2f7;
  color: var(--color-foreground);
  font-size: 11px;
  font-weight: 750;
}

.trace-title {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.trace-title strong,
.trace-title small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-title strong {
  font-size: 11px;
}

.trace-title small {
  color: var(--color-muted-text);
  font-size: 9px;
}

.agent-trace-list pre {
  max-height: 320px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  border-radius: var(--radius-md);
  background: #f6f8fa;
  color: var(--color-secondary-text);
  font-family: inherit;
  font-size: 10px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.version-history {
  display: grid;
}

.version-history article {
  display: grid;
  min-height: 70px;
  grid-template-columns: 38px minmax(0, 1fr) 34px;
  align-items: center;
  gap: 8px;
  padding: 9px 0;
  border-bottom: 1px solid var(--color-border);
}

.version-history article:last-child {
  border-bottom: 0;
}

.version-marker {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid var(--color-border-strong);
  border-radius: 50%;
  color: var(--color-muted-text);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.version-history article.active .version-marker {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
}

.version-copy,
.version-copy > div {
  display: flex;
  min-width: 0;
}

.version-copy {
  flex-direction: column;
  gap: 3px;
}

.version-copy > div {
  align-items: center;
  gap: 5px;
}

.version-copy strong {
  font-size: 11px;
}

.version-copy span,
.version-copy small {
  color: var(--color-muted-text);
  font-size: 9px;
}

.form-grid-two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.regenerate-note {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
  color: #1d4ed8;
}

.regenerate-note span {
  color: var(--color-secondary-text);
  font-size: 11px;
  line-height: 1.5;
}

@media (max-width: 1280px) {
  .studio-shell {
    grid-template-columns: 180px minmax(0, 1fr);
  }

  .prototype-inspector {
    grid-column: 1 / -1;
  }

  .prototype-inspector :deep(.el-tabs__content) {
    max-width: 760px;
  }
}

@media (max-width: 900px) {
  .prototype-summary-band {
    flex-direction: column;
  }

  .prototype-summary-actions {
    width: 100%;
  }

  .prototype-summary-actions .el-segmented {
    margin-right: auto;
  }
}

@media (max-width: 760px) {
  .studio-page-head,
  .studio-head-actions,
  .prototype-summary-actions {
    align-items: stretch;
  }

  .studio-head-actions,
  .prototype-summary-actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .prototype-switcher {
    width: 100%;
  }

  .generation-job-band {
    padding: 14px 12px;
  }

  .generation-job-head,
  .generation-job-current {
    align-items: stretch;
    flex-direction: column;
    gap: 10px;
  }

  .generation-job-actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .generation-job-actions .el-button {
    min-height: 44px;
    flex: 1;
  }

  .generation-job-actions .el-tag {
    min-height: 32px;
  }

  .generation-stage-history li {
    min-height: 54px;
    grid-template-columns: 24px minmax(0, 1fr);
  }

  .generation-stage-history small {
    grid-column: 2;
  }

  .studio-head-actions > .el-button,
  .prototype-summary-actions > .el-button,
  .prototype-summary-actions > .el-dropdown {
    flex: 1;
  }

  .prototype-summary-actions .el-segmented {
    width: 100%;
    min-height: 44px;
    margin: 0;
  }

  .prototype-summary-actions :deep(.el-dropdown .el-button) {
    width: 100%;
  }

  .studio-shell {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }

  .screen-navigator,
  .preview-workbench,
  .prototype-inspector {
    grid-column: 1;
  }

  .prototype-inspector {
    max-height: none;
    overflow-y: visible;
  }

  .screen-list {
    display: flex;
    overflow-x: auto;
    scroll-snap-type: x proximity;
  }

  .screen-list button {
    min-width: 168px;
    flex: 0 0 168px;
    scroll-snap-align: start;
  }

  .preview-workbench {
    min-height: 720px;
  }

  .preview-stage {
    padding: 10px;
  }

  .preview-mobile {
    padding-block: 16px;
  }

  .form-grid-two {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .materialization-summary {
    grid-template-columns: 1fr;
  }

  .materialization-summary > div {
    grid-template-columns: 1fr auto;
    align-items: center;
    border-right: 0;
    border-bottom: 1px solid var(--color-border);
  }

  .materialization-summary > div:last-child {
    border-bottom: 0;
  }

  .journey-actions .el-button {
    min-height: 44px;
  }

  .journey-panel :deep(.el-select__wrapper),
  .prototype-inspector :deep(.el-tabs__item) {
    min-height: 44px;
  }
}

@media (max-width: 420px) {
  .prototype-title-row h2 {
    width: 100%;
    font-size: 18px;
  }

  .preview-toolbar span {
    max-width: 230px;
  }

  .device-mobile {
    border-width: 5px;
    border-radius: 22px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .screen-list button {
    transition: none;
  }
}
</style>
