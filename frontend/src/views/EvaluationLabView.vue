<template>
  <section class="page evaluation-page">
    <div class="page-head evaluation-head">
      <div>
        <span class="page-kicker">Agent 发布质量</span>
        <h1>Agent 评测实验室</h1>
        <p>对当前多 Agent 团队执行版本化回归评测，保留逐案例证据与发布门禁结论。</p>
      </div>
    </div>

    <section class="evaluation-launcher" aria-label="创建评测运行">
      <div class="launch-field mode-field">
        <span class="launch-label">评测类型</span>
        <el-segmented
          v-model="runMode"
          :options="runModeOptions"
          aria-label="选择评测类型"
          @change="handleRunModeChange"
        />
      </div>
      <div v-if="runMode === 'CHALLENGER'" class="launch-field">
        <label class="launch-label" for="candidate-agent">候选 Agent</label>
        <el-select
          id="candidate-agent"
          v-model="candidateAgentId"
          aria-label="选择候选 Agent"
          placeholder="选择 Agent"
          @change="handleCandidateAgentChange"
        >
          <el-option v-for="agent in agents" :key="agent.id" :label="agent.name" :value="agent.id" />
        </el-select>
      </div>
      <div v-if="runMode === 'CHALLENGER'" class="launch-field">
        <label class="launch-label" for="candidate-version">草稿版本</label>
        <el-select
          id="candidate-version"
          v-model="candidateVersionId"
          :loading="loadingVersions"
          :disabled="!candidateAgentId"
          aria-label="选择草稿版本"
          placeholder="选择草稿"
        >
          <el-option
            v-for="version in candidateVersions"
            :key="version.id"
            :label="`v${version.version} · ${version.release_note || version.model}`"
            :value="version.id"
          />
        </el-select>
      </div>
      <div class="launch-field baseline-field">
        <label class="launch-label" for="evaluation-baseline">{{ runMode === 'CHALLENGER' ? '生产基线' : '对比基线' }}</label>
        <el-select
          id="evaluation-baseline"
          v-model="baselineRunId"
          :clearable="runMode !== 'CHALLENGER'"
          aria-label="选择评测基线"
          :placeholder="runMode === 'CHALLENGER' ? '选择生产基线' : '无基线运行'"
        >
          <el-option
            v-for="run in availableBaselineRuns"
            :key="run.id"
            :label="`#${run.id} · ${(run.average_score * 100).toFixed(1)}% · ${formatDate(run.created_at)}`"
            :value="run.id"
          />
        </el-select>
      </div>
      <div class="launch-action">
        <el-button
          type="primary"
          :icon="VideoPlay"
          :loading="creatingRun"
          :disabled="!canCreateRun"
          @click="createRun"
        >
          {{ runMode === 'CHALLENGER' ? '运行候选评测' : '运行团队评测' }}
        </el-button>
      </div>
    </section>

    <div class="metric-band" aria-label="最近评测摘要">
      <article class="metric-tile">
        <span>发布门禁</span>
        <strong :class="gateClass(latestRun)">{{ gateLabel(latestRun) }}</strong>
        <small>{{ latestRun ? `运行 #${latestRun.id}` : '尚无评测记录' }}</small>
      </article>
      <article class="metric-tile">
        <span>综合得分</span>
        <strong>{{ latestRun ? percent(latestRun.average_score) : '—' }}</strong>
        <small>{{ latestRun ? `${latestRun.passed_cases}/${latestRun.total_cases} 通过` : '等待首次运行' }}</small>
      </article>
      <article class="metric-tile">
        <span>相对基线</span>
        <strong :class="deltaClass(latestRun?.score_delta)">{{ formatDelta(latestRun?.score_delta) }}</strong>
        <small>{{ latestRun?.baseline_run_id ? `基线 #${latestRun.baseline_run_id}` : '未选择基线' }}</small>
      </article>
      <article class="metric-tile">
        <span>测试集版本</span>
        <strong>{{ latestRun?.suite_revision ? `v${latestRun.suite_revision}` : '—' }}</strong>
        <small>{{ enabledCases.length }} 个启用用例</small>
      </article>
    </div>

    <div v-if="activeRun" class="active-run-band" role="status" aria-live="polite">
      <div class="active-run-copy">
        <span class="live-indicator" />
        <div>
          <strong>运行 #{{ activeRun.id }} · {{ statusLabel(activeRun.status) }}</strong>
          <span>{{ activeRun.completed_cases }}/{{ activeRun.total_cases }} 个案例已完成</span>
        </div>
      </div>
      <el-progress :percentage="activeRun.progress_percent" :stroke-width="8" />
      <el-button v-if="canCancel(activeRun)" :icon="Close" @click="cancelRun(activeRun)">取消</el-button>
    </div>

    <el-tabs v-model="activeView" class="evaluation-tabs">
      <el-tab-pane label="运行历史" name="runs">
        <div class="view-toolbar">
          <div class="toolbar-copy">
            <strong>回归运行</strong>
            <span>{{ filteredRuns.length }} 条记录</span>
          </div>
          <div class="toolbar-filters">
            <el-input
              v-model="runQuery"
              :prefix-icon="Search"
              clearable
              aria-label="搜索评测运行"
              placeholder="搜索运行或 Agent"
            />
            <el-select v-model="statusFilter" clearable aria-label="按运行状态筛选" placeholder="全部状态">
              <el-option v-for="option in statusOptions" :key="option" :label="statusLabel(option)" :value="option" />
            </el-select>
            <el-button :icon="Refresh" circle aria-label="刷新评测运行" title="刷新" @click="loadAll" />
          </div>
        </div>

        <div class="desktop-run-table">
          <el-table v-loading="loading" :data="filteredRuns" class="data-table" row-key="id">
            <el-table-column prop="id" label="运行" min-width="130" sortable>
              <template #default="{ row }">
                <button class="run-link" @click="openRun(row)">#{{ row.id }}</button>
                <span class="run-revision">
                  {{ row.candidate_version ? `${row.candidate_agent_name} · Challenger v${row.candidate_version}` : `测试集 v${row.suite_revision || '—'}` }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="状态" min-width="120">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small" effect="plain">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Agent 快照" min-width="220">
              <template #default="{ row }">
                <div class="agent-version-list">
                  <span v-for="agent in row.agent_snapshots.slice(0, 3)" :key="agent.id">
                    {{ roleLabel(agent.role) }} v{{ agent.version }}
                  </span>
                  <small v-if="row.agent_snapshots.length > 3">+{{ row.agent_snapshots.length - 3 }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="通过" min-width="110">
              <template #default="{ row }">{{ row.passed_cases }}/{{ row.total_cases }}</template>
            </el-table-column>
            <el-table-column prop="average_score" label="得分" min-width="110" sortable>
              <template #default="{ row }"><strong class="table-score">{{ percent(row.average_score) }}</strong></template>
            </el-table-column>
            <el-table-column prop="score_delta" label="变化" min-width="110" sortable>
              <template #default="{ row }"><span :class="deltaClass(row.score_delta)">{{ formatDelta(row.score_delta) }}</span></template>
            </el-table-column>
            <el-table-column label="门禁" min-width="110">
              <template #default="{ row }"><span :class="gateClass(row)">{{ gateLabel(row) }}</span></template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" min-width="170" sortable>
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="116" align="right" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openRun(row)">详情</el-button>
                <el-button v-if="row.retryable" link @click="retryRun(row)">重试</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div v-loading="loading" class="mobile-run-list">
          <article v-for="run in filteredRuns" :key="run.id" class="run-card">
            <button class="run-card-main" @click="openRun(run)">
              <span>
                <strong>#{{ run.id }}</strong>
                <small>{{ run.candidate_version ? `${run.candidate_agent_name} · Challenger v${run.candidate_version}` : `测试集 v${run.suite_revision || '—'}` }}</small>
              </span>
              <el-tag :type="statusType(run.status)" size="small" effect="plain">{{ statusLabel(run.status) }}</el-tag>
            </button>
            <dl>
              <div><dt>得分</dt><dd>{{ percent(run.average_score) }}</dd></div>
              <div><dt>通过</dt><dd>{{ run.passed_cases }}/{{ run.total_cases }}</dd></div>
              <div><dt>变化</dt><dd :class="deltaClass(run.score_delta)">{{ formatDelta(run.score_delta) }}</dd></div>
            </dl>
            <div class="run-card-foot">
              <span>{{ formatDate(run.created_at) }}</span>
              <el-button v-if="run.retryable" link @click="retryRun(run)">重试</el-button>
            </div>
          </article>
        </div>
        <el-empty v-if="!loading && !filteredRuns.length" description="没有符合条件的评测运行" />
      </el-tab-pane>

      <el-tab-pane label="用例库" name="cases">
        <div class="view-toolbar">
          <div class="toolbar-copy">
            <strong>团队测试集</strong>
            <span>{{ enabledCases.length }} 个启用，{{ cases.length - enabledCases.length }} 个归档</span>
          </div>
          <div class="toolbar-filters">
            <el-input
              v-model="caseQuery"
              :prefix-icon="Search"
              clearable
              aria-label="搜索评测用例"
              placeholder="搜索用例、角色或关键词"
            />
            <el-button type="primary" :icon="Plus" @click="openCaseDialog()">新建用例</el-button>
          </div>
        </div>

        <div class="desktop-case-table">
          <el-table v-loading="loading" :data="filteredCases" class="data-table" row-key="id">
            <el-table-column prop="name" label="用例" min-width="220" sortable>
              <template #default="{ row }">
                <strong class="case-name">{{ row.name }}</strong>
                <span class="case-input">{{ row.input_text }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="agent_role" label="Agent" min-width="150" sortable>
              <template #default="{ row }">{{ roleLabel(row.agent_role) }}</template>
            </el-table-column>
            <el-table-column label="期望证据" min-width="230">
              <template #default="{ row }">
                <div class="keyword-list">
                  <el-tag v-for="keyword in row.expected_keywords.slice(0, 3)" :key="keyword" size="small" effect="plain">{{ keyword }}</el-tag>
                  <small v-if="row.expected_keywords.length > 3">+{{ row.expected_keywords.length - 3 }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="阈值 / 权重" min-width="130">
              <template #default="{ row }">{{ percent(row.minimum_score) }} / {{ row.weight }}</template>
            </el-table-column>
            <el-table-column label="状态" min-width="100">
              <template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'" size="small" effect="plain">{{ row.enabled ? '启用' : '归档' }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="128" align="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openCaseDialog(row)">编辑</el-button>
                <el-button v-if="row.enabled" link type="danger" @click="archiveCase(row)">归档</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div v-loading="loading" class="mobile-case-list">
          <article v-for="item in filteredCases" :key="item.id" class="case-card">
            <div class="case-card-head"><strong>{{ item.name }}</strong><el-tag :type="item.enabled ? 'success' : 'info'" size="small" effect="plain">{{ item.enabled ? '启用' : '归档' }}</el-tag></div>
            <span>{{ roleLabel(item.agent_role) }}</span>
            <p>{{ item.input_text }}</p>
            <div class="keyword-list"><el-tag v-for="keyword in item.expected_keywords" :key="keyword" size="small" effect="plain">{{ keyword }}</el-tag></div>
            <div class="case-card-actions">
              <el-button @click="openCaseDialog(item)">编辑</el-button>
              <el-button v-if="item.enabled" type="danger" plain @click="archiveCase(item)">归档</el-button>
            </div>
          </article>
        </div>
        <el-empty v-if="!loading && !filteredCases.length" description="没有符合条件的评测用例" />
      </el-tab-pane>

      <el-tab-pane label="反馈队列" name="feedback">
        <div class="view-toolbar">
          <div class="toolbar-copy">
            <strong>生产负反馈</strong>
            <span>当前筛选 {{ filteredFeedback.length }} 条</span>
          </div>
          <div class="toolbar-filters feedback-toolbar-filters">
            <el-input
              v-model="feedbackQuery"
              :prefix-icon="Search"
              clearable
              aria-label="搜索生产负反馈"
              placeholder="搜索输入、回答或评论"
            />
            <el-select v-model="feedbackStatus" aria-label="按反馈状态筛选" @change="loadFeedback">
              <el-option v-for="option in feedbackStatusOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <el-button :icon="Refresh" circle aria-label="刷新反馈队列" title="刷新" @click="loadFeedback" />
          </div>
        </div>

        <div class="desktop-feedback-table">
          <el-table v-loading="loadingFeedback" :data="filteredFeedback" class="data-table" row-key="feedback_id">
            <el-table-column label="来源输入" min-width="250">
              <template #default="{ row }">
                <strong class="feedback-input">{{ row.input_text }}</strong>
                <span class="feedback-meta">{{ row.user_name }} · 会话 #{{ row.conversation_id }}</span>
              </template>
            </el-table-column>
            <el-table-column label="Agent" min-width="150">
              <template #default="{ row }">
                <strong class="feedback-agent">{{ row.agent_name }}</strong>
                <span class="feedback-meta">{{ roleLabel(row.agent_role) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="负反馈" min-width="230">
              <template #default="{ row }">
                <span class="feedback-comment">{{ row.comment || '未填写评论' }}</span>
                <span class="feedback-answer">{{ row.answer }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" min-width="120">
              <template #default="{ row }">
                <el-tag :type="feedbackStatusType(row.status)" size="small" effect="plain">{{ feedbackStatusLabel(row.status) }}</el-tag>
                <span v-if="row.evaluation_case_id" class="feedback-meta">用例 #{{ row.evaluation_case_id }}</span>
              </template>
            </el-table-column>
            <el-table-column label="时间" min-width="150">
              <template #default="{ row }">{{ formatDate(row.reviewed_at || row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="142" align="right" fixed="right">
              <template #default="{ row }">
                <div :data-feedback-id="row.feedback_id">
                  <template v-if="row.status === 'PENDING'">
                    <el-button link type="primary" @click="openPromoteDialog(row)">转为用例</el-button>
                    <el-button link type="danger" @click="dismissFeedback(row)">忽略</el-button>
                  </template>
                  <span v-else class="feedback-reviewed">已复核</span>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div v-loading="loadingFeedback" class="mobile-feedback-list">
          <article
            v-for="item in filteredFeedback"
            :key="item.feedback_id"
            class="feedback-card"
            :data-feedback-id="item.feedback_id"
          >
            <div class="feedback-card-head">
              <span><strong>{{ item.agent_name }}</strong><small>{{ roleLabel(item.agent_role) }} · {{ item.user_name }}</small></span>
              <el-tag :type="feedbackStatusType(item.status)" size="small" effect="plain">{{ feedbackStatusLabel(item.status) }}</el-tag>
            </div>
            <dl class="feedback-card-evidence">
              <div><dt>用户输入</dt><dd>{{ item.input_text }}</dd></div>
              <div><dt>Agent 回答</dt><dd>{{ item.answer }}</dd></div>
              <div><dt>负反馈</dt><dd>{{ item.comment || '未填写评论' }}</dd></div>
            </dl>
            <div v-if="item.status === 'PENDING'" class="feedback-card-actions">
              <el-button type="primary" :icon="Plus" @click="openPromoteDialog(item)">转为用例</el-button>
              <el-button :icon="Close" @click="dismissFeedback(item)">忽略</el-button>
            </div>
            <div v-else class="feedback-card-foot">
              <span>{{ item.resolution_note }}</span>
              <small>{{ formatDate(item.reviewed_at || item.created_at) }}</small>
            </div>
          </article>
        </div>
        <el-empty v-if="!loadingFeedback && !filteredFeedback.length" description="没有符合条件的反馈" />
      </el-tab-pane>
    </el-tabs>

    <el-drawer
      v-model="detailDrawer"
      :title="detailRun ? `评测运行 #${detailRun.id}` : '评测详情'"
      size="min(820px, 100vw)"
      class="evaluation-detail-drawer"
    >
      <div v-if="detailRun" v-loading="detailLoading" class="run-detail">
        <div class="detail-summary">
          <div><span>状态</span><strong>{{ statusLabel(detailRun.status) }}</strong></div>
          <div><span>综合得分</span><strong>{{ percent(detailRun.average_score) }}</strong></div>
          <div><span>相对基线</span><strong :class="deltaClass(detailRun.score_delta)">{{ formatDelta(detailRun.score_delta) }}</strong></div>
          <div><span>门禁</span><strong :class="gateClass(detailRun)">{{ gateLabel(detailRun) }}</strong></div>
        </div>

        <section
          v-if="detailRun.candidate_version"
          class="release-evidence"
          aria-label="候选版本发布证据"
        >
          <div class="release-identity">
            <span>Challenger 发布</span>
            <strong>
              {{ detailRun.candidate_agent_name }} v{{ detailRun.expected_current_version }} → v{{ detailRun.candidate_version }}
            </strong>
            <small>评测 #{{ detailRun.id }} · 基线 #{{ detailRun.baseline_run_id }}</small>
          </div>
          <div class="release-state" role="status" aria-live="polite">
            <el-tag :type="releaseStatusType(detailRun)" effect="plain">
              {{ releaseStatusLabel(detailRun) }}
            </el-tag>
            <span>{{ releaseStatusMessage(detailRun) }}</span>
          </div>
          <div class="release-actions">
            <el-button
              v-if="!detailRun.release"
              type="primary"
              :icon="Upload"
              :loading="publishingRelease"
              :disabled="!canPublishRelease(detailRun)"
              @click="publishRelease(detailRun)"
            >
              发布候选版本
            </el-button>
            <el-button
              v-if="detailRun.release?.status === 'PUBLISHED'"
              :icon="RefreshLeft"
              :loading="rollingBackRelease"
              @click="rollbackRelease(detailRun)"
            >
              回滚此发布
            </el-button>
          </div>
        </section>

        <el-progress
          v-if="isActive(detailRun)"
          :percentage="detailRun.progress_percent"
          :format="() => `${detailRun?.completed_cases || 0}/${detailRun?.total_cases || 0}`"
        />

        <section class="detail-section">
          <div class="section-heading"><h2>维度对比</h2><span>候选与可比较基线</span></div>
          <div class="dimension-table" role="table" aria-label="评测维度分数对比">
            <div v-for="dimension in dimensions" :key="dimension.key" class="dimension-row" role="row">
              <span class="dimension-label" role="rowheader">{{ dimension.label }}</span>
              <div class="dimension-bars" role="cell">
                <div class="score-bar candidate-bar"><span :style="{ width: `${dimensionScore(detailRun, dimension.key) * 100}%` }" /></div>
                <div class="score-bar baseline-bar"><span :style="{ width: `${baselineDimensionScore(detailRun, dimension.key) * 100}%` }" /></div>
              </div>
              <span class="dimension-values" role="cell">
                {{ percent(dimensionScore(detailRun, dimension.key)) }}
                <small>{{ hasBaselineDimension(detailRun, dimension.key) ? percent(baselineDimensionScore(detailRun, dimension.key)) : '—' }}</small>
              </span>
            </div>
          </div>
          <div class="dimension-legend" aria-label="图例"><span class="candidate-key" />候选<span class="baseline-key" />基线</div>
        </section>

        <el-alert
          v-if="detailRun.gate_failures.length"
          type="error"
          :closable="false"
          show-icon
          title="发布门禁未通过"
        >
          <ul class="gate-failures"><li v-for="failure in detailRun.gate_failures" :key="failure">{{ failure }}</li></ul>
        </el-alert>

        <section class="detail-section">
          <div class="section-heading"><h2>案例证据</h2><span>{{ detailRun.results.length }} 个已完成</span></div>
          <el-collapse class="result-collapse">
            <el-collapse-item v-for="result in detailRun.results" :key="result.id" :name="result.id">
              <template #title>
                <div class="result-title">
                  <span><strong>{{ result.case_name }}</strong><small>{{ roleLabel(result.agent_role) }} · v{{ result.agent_version || '—' }}</small></span>
                  <span class="result-title-score" :class="result.passed ? 'gate-pass' : 'gate-fail'">{{ percent(result.score) }}</span>
                  <el-tag v-if="result.regressed" type="danger" size="small" effect="plain">回退</el-tag>
                  <el-tag v-else :type="result.passed ? 'success' : 'danger'" size="small" effect="plain">{{ result.passed ? '通过' : '未通过' }}</el-tag>
                </div>
              </template>
              <div class="result-body">
                <div class="result-meta"><span>{{ result.model }}</span><span>{{ result.latency_ms }} ms</span><span>{{ scoreSourceLabel(result.score_source) }}</span></div>
                <p class="case-prompt"><strong>输入</strong>{{ result.input_text }}</p>
                <div class="answer-compare">
                  <div><strong>候选回答</strong><p>{{ result.answer || result.error || '无回答' }}</p></div>
                  <div v-if="result.baseline_score !== null && result.baseline_score !== undefined"><strong>基线回答</strong><p>{{ result.baseline_answer || '无回答' }}</p></div>
                </div>
                <div class="evidence-block">
                  <div><strong>命中</strong><span v-if="!result.matched_keywords.length">无</span><el-tag v-for="item in result.matched_keywords" :key="item" type="success" size="small" effect="plain">{{ item }}</el-tag></div>
                  <div><strong>缺失</strong><span v-if="!result.missing_keywords.length">无</span><el-tag v-for="item in result.missing_keywords" :key="item" type="warning" size="small" effect="plain">{{ item }}</el-tag></div>
                  <div v-if="result.forbidden_hits.length"><strong>禁用词命中</strong><el-tag v-for="item in result.forbidden_hits" :key="item" type="danger" size="small" effect="plain">{{ item }}</el-tag></div>
                </div>
                <p v-if="result.judge_reason" class="judge-reason"><strong>Judge 依据</strong>{{ result.judge_reason }}</p>
                <el-alert v-if="result.error || result.judge_error" type="warning" :closable="false" :title="result.error || result.judge_error" />
              </div>
            </el-collapse-item>
          </el-collapse>
          <el-empty v-if="!detailRun.results.length" description="评测结果尚未产生" :image-size="72" />
        </section>

        <div class="detail-actions">
          <el-button v-if="canCancel(detailRun)" :icon="Close" @click="cancelRun(detailRun)">取消运行</el-button>
          <el-button v-if="detailRun.retryable" type="primary" :icon="RefreshRight" @click="retryRun(detailRun)">重试运行</el-button>
        </div>
      </div>
    </el-drawer>

    <el-dialog
      v-model="caseDialog"
      :title="editingCaseId ? '编辑评测用例' : '新建评测用例'"
      width="min(720px, calc(100vw - 24px))"
      top="4vh"
      class="evaluation-case-dialog"
    >
      <el-form label-position="top">
        <el-row :gutter="14">
          <el-col :xs="24" :md="14"><el-form-item label="用例名称" required><el-input v-model.trim="caseForm.name" maxlength="200" /></el-form-item></el-col>
          <el-col :xs="24" :md="10"><el-form-item label="目标 Agent" required><el-select v-model="caseForm.agent_role" class="full"><el-option v-for="agent in agents" :key="agent.role" :label="agent.name" :value="agent.role" /></el-select></el-form-item></el-col>
        </el-row>
        <el-form-item label="测试输入" required><el-input v-model.trim="caseForm.input_text" type="textarea" :rows="4" maxlength="20000" show-word-limit /></el-form-item>
        <el-form-item label="期望证据关键词" required><el-input v-model.trim="caseForm.expected_keywords" placeholder="例如：幂等、回滚、审计" /></el-form-item>
        <el-form-item label="禁用词"><el-input v-model.trim="caseForm.forbidden_keywords" placeholder="例如：关闭鉴权、明文密钥" /></el-form-item>
        <el-form-item label="评分 Rubric"><el-input v-model.trim="caseForm.rubric" type="textarea" :rows="3" maxlength="10000" /></el-form-item>
        <div class="case-rule-grid">
          <el-form-item label="最低通过分"><el-input-number v-model="caseForm.minimum_score" :min="0" :max="1" :step="0.05" :precision="2" /></el-form-item>
          <el-form-item label="用例权重"><el-input-number v-model="caseForm.weight" :min="0.1" :max="100" :step="0.5" :precision="1" /></el-form-item>
          <el-form-item label="状态"><el-switch v-model="caseForm.enabled" active-text="启用" inactive-text="归档" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="caseDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingCase" :disabled="!validCaseForm" @click="saveCase">保存用例</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="promoteDialog"
      title="转为评测用例"
      width="min(760px, calc(100vw - 24px))"
      top="3vh"
      class="evaluation-feedback-dialog"
    >
      <div v-if="selectedFeedback" class="feedback-source" aria-label="冻结的反馈来源证据">
        <div class="feedback-source-head">
          <span>来源证据</span>
          <strong>{{ selectedFeedback.agent_name }} · {{ roleLabel(selectedFeedback.agent_role) }}</strong>
        </div>
        <dl>
          <div><dt>用户输入</dt><dd>{{ selectedFeedback.input_text }}</dd></div>
          <div><dt>Agent 回答</dt><dd>{{ selectedFeedback.answer }}</dd></div>
          <div><dt>用户评论</dt><dd>{{ selectedFeedback.comment || '未填写评论' }}</dd></div>
        </dl>
      </div>
      <el-form label-position="top" class="feedback-promote-form">
        <el-form-item label="用例名称" required><el-input v-model.trim="promoteForm.name" maxlength="200" /></el-form-item>
        <el-form-item label="期望证据关键词" required><el-input v-model.trim="promoteForm.expected_keywords" placeholder="例如：租户隔离、引用证据" /></el-form-item>
        <el-form-item label="禁用词"><el-input v-model.trim="promoteForm.forbidden_keywords" placeholder="例如：跳过鉴权、共享密钥" /></el-form-item>
        <el-form-item label="评分 Rubric" required><el-input v-model.trim="promoteForm.rubric" type="textarea" :rows="3" maxlength="10000" /></el-form-item>
        <div class="feedback-rule-grid">
          <el-form-item label="最低通过分"><el-input-number v-model="promoteForm.minimum_score" :min="0" :max="1" :step="0.05" :precision="2" /></el-form-item>
          <el-form-item label="用例权重"><el-input-number v-model="promoteForm.weight" :min="0.1" :max="100" :step="0.5" :precision="1" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="promoteDialog = false">取消</el-button>
        <el-button type="primary" :loading="promotingFeedback" :disabled="!validPromoteForm" @click="promoteFeedback">创建评测用例</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Close, Plus, Refresh, RefreshLeft, RefreshRight, Search, Upload, VideoPlay } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'
import 'element-plus/es/components/message-box/style/css.mjs'
import { api } from '../api/client'
import type {
  Agent,
  AgentEvaluationRelease,
  AgentVersion,
  EvaluationCase,
  EvaluationFeedbackCandidate,
  EvaluationRun,
  EvaluationRunDetail
} from '../api/types'
import { confirmDestructiveAction } from '../utils/confirm'

const ACTIVE_STATUSES = new Set(['QUEUED', 'RUNNING', 'CANCELLING'])
const statusOptions = ['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED']
const feedbackStatusOptions = [
  { label: '待复核', value: 'PENDING' },
  { label: '已转用例', value: 'CONVERTED' },
  { label: '已忽略', value: 'DISMISSED' },
  { label: '全部状态', value: 'ALL' }
]
const DISMISS_FEEDBACK_REASON = '已人工复核，不适合作为可复现评测用例'
const dimensions = [
  { key: 'requirements', label: '需求覆盖' },
  { key: 'correctness', label: '正确性' },
  { key: 'relevance', label: '相关性' },
  { key: 'completeness', label: '完整性' },
  { key: 'safety', label: '安全性' }
]
const runModeOptions = [
  { label: '团队基线', value: 'TEAM' },
  { label: '候选版本', value: 'CHALLENGER' }
]

const route = useRoute()
const agents = ref<Agent[]>([])
const cases = ref<EvaluationCase[]>([])
const feedback = ref<EvaluationFeedbackCandidate[]>([])
const runs = ref<EvaluationRun[]>([])
const loading = ref(false)
const loadingFeedback = ref(false)
const creatingRun = ref(false)
const loadingVersions = ref(false)
const publishingRelease = ref(false)
const rollingBackRelease = ref(false)
const savingCase = ref(false)
const promotingFeedback = ref(false)
const activeView = ref('runs')
const baselineRunId = ref<number | null>(null)
const runMode = ref<'TEAM' | 'CHALLENGER'>('TEAM')
const candidateAgentId = ref<number | null>(null)
const candidateVersionId = ref<number | null>(null)
const candidateVersions = ref<AgentVersion[]>([])
const runQuery = ref('')
const caseQuery = ref('')
const feedbackQuery = ref('')
const feedbackStatus = ref('PENDING')
const statusFilter = ref('')
const detailDrawer = ref(false)
const detailLoading = ref(false)
const detailRun = ref<EvaluationRunDetail | null>(null)
const caseDialog = ref(false)
const promoteDialog = ref(false)
const editingCaseId = ref<number | null>(null)
const selectedFeedback = ref<EvaluationFeedbackCandidate | null>(null)
const caseForm = reactive({
  name: '',
  agent_role: '',
  input_text: '',
  expected_keywords: '',
  forbidden_keywords: '',
  rubric: '',
  minimum_score: 0.8,
  weight: 1,
  enabled: true
})
const promoteForm = reactive({
  name: '',
  expected_keywords: '',
  forbidden_keywords: '',
  rubric: '',
  minimum_score: 0.8,
  weight: 1
})
let pollTimer: ReturnType<typeof window.setInterval> | null = null
let pollBusy = false
const feedbackRequestIds = new Map<string, string>()

const enabledCases = computed(() => cases.value.filter((item) => item.enabled))
const latestRun = computed(() => runs.value[0] || null)
const activeRun = computed(() => runs.value.find((run) => isActive(run)) || null)
const hasActiveRun = computed(() => Boolean(activeRun.value))
const baselineRuns = computed(() => runs.value.filter((run) => (
  run.status === 'COMPLETED' && run.gate_passed === true && run.suite_revision
)))
const availableBaselineRuns = computed(() => {
  if (runMode.value !== 'CHALLENGER' || !candidateAgentId.value) return baselineRuns.value
  const agent = agents.value.find((item) => item.id === candidateAgentId.value)
  if (!agent) return []
  return baselineRuns.value.filter((run) => run.agent_snapshots.some((snapshot) => (
    snapshot.id === agent.id && snapshot.version === agent.current_version
  )))
})
const canCreateRun = computed(() => {
  if (!enabledCases.value.length || hasActiveRun.value) return false
  if (runMode.value === 'TEAM') return true
  return Boolean(candidateAgentId.value && candidateVersionId.value && baselineRunId.value)
})
const filteredRuns = computed(() => {
  const query = runQuery.value.trim().toLocaleLowerCase()
  return runs.value.filter((run) => {
    const matchesStatus = !statusFilter.value || run.status === statusFilter.value
    const haystack = [run.id, run.suite_revision, run.status, ...run.agent_snapshots.flatMap((agent) => [agent.name, agent.role, agent.model])]
      .join(' ')
      .toLocaleLowerCase()
    return matchesStatus && (!query || haystack.includes(query))
  })
})
const filteredCases = computed(() => {
  const query = caseQuery.value.trim().toLocaleLowerCase()
  if (!query) return cases.value
  return cases.value.filter((item) => [item.name, item.agent_role, item.input_text, ...item.expected_keywords, ...item.forbidden_keywords]
    .join(' ')
    .toLocaleLowerCase()
    .includes(query))
})
const filteredFeedback = computed(() => {
  const query = feedbackQuery.value.trim().toLocaleLowerCase()
  return feedback.value.filter((item) => {
    const matchesStatus = feedbackStatus.value === 'ALL' || item.status === feedbackStatus.value
    const haystack = [
      item.user_name,
      item.agent_name,
      item.agent_role,
      item.input_text,
      item.answer,
      item.comment,
      item.resolution_note
    ].join(' ').toLocaleLowerCase()
    return matchesStatus && (!query || haystack.includes(query))
  })
})
const validCaseForm = computed(() => Boolean(
  caseForm.name.trim()
  && caseForm.agent_role
  && caseForm.input_text.trim()
  && splitTerms(caseForm.expected_keywords).length
))
const validPromoteForm = computed(() => Boolean(
  promoteForm.name.trim()
  && splitTerms(promoteForm.expected_keywords).length
  && promoteForm.rubric.trim()
))

function splitTerms(value: string) {
  return [...new Set(value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean))]
}

function requestId() {
  return globalThis.crypto?.randomUUID?.() || `evaluation-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function feedbackRequestId(action: 'promote' | 'dismiss', feedbackId: number) {
  const key = `${action}:${feedbackId}`
  const existing = feedbackRequestIds.get(key)
  if (existing) return existing
  const created = requestId()
  feedbackRequestIds.set(key, created)
  return created
}

function selectMatchingBaseline() {
  if (runMode.value === 'CHALLENGER') {
    baselineRunId.value = availableBaselineRuns.value[0]?.id || null
  }
}

async function loadCandidateVersions(agentId: number, preferredVersionId?: number) {
  loadingVersions.value = true
  candidateVersionId.value = null
  try {
    const { data } = await api.get<AgentVersion[]>(`/agents/${agentId}/versions`)
    candidateVersions.value = data.filter((version) => version.status === 'DRAFT')
    candidateVersionId.value = candidateVersions.value.some((version) => version.id === preferredVersionId)
      ? preferredVersionId || null
      : candidateVersions.value[0]?.id || null
  } finally {
    loadingVersions.value = false
  }
}

async function handleCandidateAgentChange(value: unknown) {
  const agentId = Number(value)
  candidateAgentId.value = Number.isFinite(agentId) ? agentId : null
  candidateVersions.value = []
  selectMatchingBaseline()
  if (candidateAgentId.value) await loadCandidateVersions(candidateAgentId.value)
}

function handleRunModeChange() {
  if (runMode.value === 'TEAM') {
    candidateAgentId.value = null
    candidateVersionId.value = null
    candidateVersions.value = []
    baselineRunId.value = baselineRuns.value[0]?.id || null
    return
  }
  selectMatchingBaseline()
}

function isActive(run: EvaluationRun) {
  return ACTIVE_STATUSES.has(run.status)
}

function canCancel(run: EvaluationRun) {
  return run.status === 'QUEUED' || run.status === 'RUNNING'
}

function percent(value?: number | null) {
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—'
}

function formatDelta(value?: number | null) {
  if (typeof value !== 'number') return '—'
  const points = value * 100
  return `${points > 0 ? '+' : ''}${points.toFixed(1)} pt`
}

function deltaClass(value?: number | null) {
  if (typeof value !== 'number' || value === 0) return 'delta-neutral'
  return value > 0 ? 'delta-positive' : 'delta-negative'
}

function gateLabel(value?: unknown) {
  const run = value as EvaluationRun | null | undefined
  if (!run) return '待评测'
  if (run.release?.status === 'PUBLISHED') return '已发布'
  if (run.release?.status === 'ROLLED_BACK') return '已回滚'
  if (run.gate_passed === null || run.gate_passed === undefined) return isActive(run) ? '评测中' : '待评测'
  return run.gate_passed ? '可发布' : '已阻断'
}

function gateClass(value?: unknown) {
  const run = value as EvaluationRun | null | undefined
  if (!run || run.gate_passed === null || run.gate_passed === undefined) return 'gate-pending'
  return run.gate_passed ? 'gate-pass' : 'gate-fail'
}

function releaseStatusLabel(run: EvaluationRun) {
  if (run.release?.status === 'PUBLISHED') return '已发布'
  if (run.release?.status === 'ROLLED_BACK') return '已回滚'
  return run.gate_passed ? '门禁通过' : '禁止发布'
}

function releaseStatusType(run: EvaluationRun) {
  if (run.release?.status === 'ROLLED_BACK') return 'info'
  return run.release?.status === 'PUBLISHED' || run.gate_passed ? 'success' : 'danger'
}

function releaseStatusMessage(run: EvaluationRun) {
  if (run.release?.status === 'PUBLISHED') return `候选版本 v${run.release.candidate_version} 已发布`
  if (run.release?.status === 'ROLLED_BACK') return `发布已回滚至恢复版本 v${run.release.rollback_version}`
  if (!run.gate_passed) return '门禁未通过，禁止发布'
  if (!canPublishRelease(run)) return '生产版本已变化，需重新评测'
  return '评测通过，可安全发布'
}

function canPublishRelease(run: EvaluationRun) {
  if (run.status !== 'COMPLETED' || run.gate_passed !== true || run.release) return false
  const agent = agents.value.find((item) => item.id === run.candidate_agent_id)
  return Boolean(agent && agent.current_version === run.expected_current_version)
}

function statusLabel(status: string) {
  return ({ QUEUED: '等待执行', RUNNING: '执行中', CANCELLING: '取消中', COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消' } as Record<string, string>)[status] || status
}

function statusType(status: string) {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'RUNNING' || status === 'QUEUED') return 'warning'
  return 'info'
}

function roleLabel(role: string) {
  return ({
    product_manager: '产品经理',
    project_manager: '项目经理',
    architect: '架构师',
    test_engineer: '测试工程师',
    meeting_summarizer: '会议纪要员',
    knowledge_admin: '知识库管理员',
    notification_secretary: '通知秘书',
    operations_analyst: '运营分析师'
  } as Record<string, string>)[role] || role
}

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function dimensionScore(run: EvaluationRun, key: string) {
  return Number(run.dimension_averages[key] || 0)
}

function baselineDimensionScore(run: EvaluationRun, key: string) {
  return Number(run.baseline_dimension_averages[key] || 0)
}

function hasBaselineDimension(run: EvaluationRun, key: string) {
  return Object.prototype.hasOwnProperty.call(run.baseline_dimension_averages, key)
}

function scoreSourceLabel(source: string) {
  if (source === 'llm_judge') return 'LLM Judge'
  if (source === 'judge_fallback') return 'Judge 降级'
  return source === 'execution_error' ? '执行错误' : '确定性评分'
}

function feedbackStatusLabel(status: string) {
  return ({ PENDING: '待复核', CONVERTED: '已转用例', DISMISSED: '已忽略' } as Record<string, string>)[status] || status
}

function feedbackStatusType(status: string) {
  if (status === 'CONVERTED') return 'success'
  if (status === 'DISMISSED') return 'info'
  return 'warning'
}

async function loadFeedback() {
  loadingFeedback.value = true
  try {
    const { data } = await api.get<EvaluationFeedbackCandidate[]>('/evaluations/feedback', {
      params: { status: feedbackStatus.value }
    })
    feedback.value = data
  } finally {
    loadingFeedback.value = false
  }
}

async function loadAll() {
  loading.value = true
  try {
    const [agentsResponse, casesResponse, feedbackResponse, runsResponse] = await Promise.all([
      api.get<Agent[]>('/agents'),
      api.get<EvaluationCase[]>('/evaluations/cases'),
      api.get<EvaluationFeedbackCandidate[]>('/evaluations/feedback', {
        params: { status: feedbackStatus.value }
      }),
      api.get<EvaluationRun[]>('/evaluations/runs')
    ])
    agents.value = agentsResponse.data
    cases.value = casesResponse.data
    feedback.value = feedbackResponse.data
    runs.value = runsResponse.data
    const queryAgentId = Number(route.query.agent || 0)
    const queryVersionId = Number(route.query.version || 0)
    if (queryAgentId && agents.value.some((agent) => agent.id === queryAgentId)) {
      runMode.value = 'CHALLENGER'
      candidateAgentId.value = queryAgentId
      selectMatchingBaseline()
      await loadCandidateVersions(queryAgentId, queryVersionId || undefined)
    } else if (!baselineRunId.value) {
      baselineRunId.value = baselineRuns.value[0]?.id || null
    }
    syncPolling()
  } finally {
    loading.value = false
  }
}

async function refreshRuns() {
  if (pollBusy) return
  pollBusy = true
  try {
    const { data } = await api.get<EvaluationRun[]>('/evaluations/runs')
    runs.value = data
    if (detailRun.value && isActive(detailRun.value)) await loadRunDetail(detailRun.value.id, false)
    syncPolling()
  } finally {
    pollBusy = false
  }
}

function syncPolling() {
  if (hasActiveRun.value && !pollTimer) pollTimer = window.setInterval(refreshRuns, 1500)
  if (!hasActiveRun.value && pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function createRun() {
  creatingRun.value = true
  try {
    const { data } = await api.post<EvaluationRun>('/evaluations/runs', {
      request_id: requestId(),
      baseline_run_id: baselineRunId.value || null,
      candidate_version_id: runMode.value === 'CHALLENGER' ? candidateVersionId.value : null
    })
    runs.value = [data, ...runs.value.filter((run) => run.id !== data.id)]
    activeView.value = 'runs'
    ElMessage.success(`团队评测 #${data.id} 已进入队列`)
    syncPolling()
  } finally {
    creatingRun.value = false
  }
}

async function loadRunDetail(id: number, showLoading = true) {
  if (showLoading) detailLoading.value = true
  try {
    const { data } = await api.get<EvaluationRunDetail>(`/evaluations/runs/${id}`)
    detailRun.value = data
  } finally {
    detailLoading.value = false
  }
}

async function openRun(value: unknown) {
  const run = value as EvaluationRun
  detailDrawer.value = true
  await loadRunDetail(run.id)
}

async function cancelRun(value: unknown) {
  const run = value as EvaluationRun
  if (!await confirmDestructiveAction(`确认取消评测运行 #${run.id} 吗？已完成的案例证据会保留。`, '取消评测运行')) return
  const { data } = await api.post<EvaluationRun>(`/evaluations/runs/${run.id}/cancel`)
  runs.value = runs.value.map((item) => item.id === data.id ? data : item)
  if (detailRun.value?.id === data.id) await loadRunDetail(data.id)
  ElMessage.success(`评测运行 #${run.id} 已请求取消`)
  syncPolling()
}

async function retryRun(value: unknown) {
  const run = value as EvaluationRun
  const { data } = await api.post<EvaluationRun>(`/evaluations/runs/${run.id}/retry`)
  runs.value = runs.value.map((item) => item.id === data.id ? data : item)
  if (detailRun.value?.id === data.id) await loadRunDetail(data.id)
  ElMessage.success(`评测运行 #${run.id} 已重新入队`)
  syncPolling()
}

function applyRelease(runId: number, release: AgentEvaluationRelease) {
  runs.value = runs.value.map((run) => run.id === runId ? { ...run, release } : run)
  if (detailRun.value?.id === runId) detailRun.value = { ...detailRun.value, release }
  agents.value = agents.value.map((agent) => {
    if (agent.id !== release.agent_id) return agent
    const currentVersion = release.status === 'PUBLISHED'
      ? release.candidate_version
      : release.rollback_version || agent.current_version
    return { ...agent, current_version: currentVersion }
  })
}

async function publishRelease(run: EvaluationRunDetail) {
  try {
    await ElMessageBox.confirm(
      `生产版本 v${run.expected_current_version} 将升级到 v${run.candidate_version}，评测证据将永久关联本次发布。`,
      '发布候选版本',
      {
        type: 'warning',
        confirmButtonText: '确认发布',
        cancelButtonText: '取消'
      }
    )
  } catch {
    return
  }
  publishingRelease.value = true
  try {
    const { data } = await api.post<AgentEvaluationRelease>(`/evaluations/runs/${run.id}/publish`, {
      request_id: requestId()
    })
    applyRelease(run.id, data)
    ElMessage.success(`Agent v${data.candidate_version} 已发布`)
  } finally {
    publishingRelease.value = false
  }
}

async function rollbackRelease(run: EvaluationRunDetail) {
  const release = run.release
  if (!release) return
  if (!await confirmDestructiveAction(
    `将为 Agent v${release.previous_version} 创建新的恢复版本，发布证据会保留。确认继续吗？`,
    '回滚评测发布'
  )) return
  rollingBackRelease.value = true
  try {
    const { data } = await api.post<AgentEvaluationRelease>(`/evaluations/releases/${release.id}/rollback`, {
      request_id: requestId()
    })
    applyRelease(run.id, data)
    ElMessage.success(`发布已回滚至恢复版本 v${data.rollback_version}`)
  } finally {
    rollingBackRelease.value = false
  }
}

function openCaseDialog(value?: unknown) {
  const item = value as EvaluationCase | undefined
  editingCaseId.value = item?.id || null
  Object.assign(caseForm, item ? {
    name: item.name,
    agent_role: item.agent_role,
    input_text: item.input_text,
    expected_keywords: item.expected_keywords.join('，'),
    forbidden_keywords: item.forbidden_keywords.join('，'),
    rubric: item.rubric,
    minimum_score: item.minimum_score,
    weight: item.weight,
    enabled: item.enabled
  } : {
    name: '',
    agent_role: agents.value[0]?.role || '',
    input_text: '',
    expected_keywords: '',
    forbidden_keywords: '',
    rubric: '',
    minimum_score: 0.8,
    weight: 1,
    enabled: true
  })
  caseDialog.value = true
}

function casePayload() {
  return {
    name: caseForm.name,
    agent_role: caseForm.agent_role,
    input_text: caseForm.input_text,
    expected_keywords: splitTerms(caseForm.expected_keywords),
    forbidden_keywords: splitTerms(caseForm.forbidden_keywords),
    rubric: caseForm.rubric,
    minimum_score: caseForm.minimum_score,
    weight: caseForm.weight,
    enabled: caseForm.enabled
  }
}

async function saveCase() {
  savingCase.value = true
  try {
    const { data } = editingCaseId.value
      ? await api.patch<EvaluationCase>(`/evaluations/cases/${editingCaseId.value}`, casePayload())
      : await api.post<EvaluationCase>('/evaluations/cases', casePayload())
    cases.value = editingCaseId.value
      ? cases.value.map((item) => item.id === data.id ? data : item)
      : [...cases.value, data]
    caseDialog.value = false
    ElMessage.success(editingCaseId.value ? '评测用例已更新' : '评测用例已创建')
  } finally {
    savingCase.value = false
  }
}

async function archiveCase(value: unknown) {
  const item = value as EvaluationCase
  if (!await confirmDestructiveAction(`归档后不会进入新的评测运行，历史证据仍会保留。确认归档“${item.name}”吗？`, '归档评测用例')) return
  await api.delete(`/evaluations/cases/${item.id}`)
  cases.value = cases.value.map((current) => current.id === item.id ? { ...current, enabled: false } : current)
  ElMessage.success('评测用例已归档')
}

function openPromoteDialog(value: unknown) {
  const item = value as EvaluationFeedbackCandidate
  selectedFeedback.value = item
  Object.assign(promoteForm, {
    name: `${roleLabel(item.agent_role)}负反馈回归 #${item.feedback_id}`,
    expected_keywords: '',
    forbidden_keywords: '',
    rubric: item.comment ? `修正以下用户反馈：${item.comment}` : '',
    minimum_score: 0.8,
    weight: 1
  })
  promoteDialog.value = true
}

async function promoteFeedback() {
  const item = selectedFeedback.value
  if (!item) return
  promotingFeedback.value = true
  try {
    const { data } = await api.post<EvaluationFeedbackCandidate>(`/evaluations/feedback/${item.feedback_id}/promote`, {
      request_id: feedbackRequestId('promote', item.feedback_id),
      name: promoteForm.name,
      expected_keywords: splitTerms(promoteForm.expected_keywords),
      forbidden_keywords: splitTerms(promoteForm.forbidden_keywords),
      rubric: promoteForm.rubric,
      minimum_score: promoteForm.minimum_score,
      weight: promoteForm.weight
    })
    feedback.value = feedback.value.map((candidate) => candidate.feedback_id === data.feedback_id ? data : candidate)
    feedbackRequestIds.delete(`promote:${item.feedback_id}`)
    const casesResponse = await api.get<EvaluationCase[]>('/evaluations/cases')
    cases.value = casesResponse.data
    promoteDialog.value = false
    ElMessage.success('反馈已转为评测用例')
  } finally {
    promotingFeedback.value = false
  }
}

async function dismissFeedback(value: unknown) {
  const item = value as EvaluationFeedbackCandidate
  try {
    await ElMessageBox.confirm(
      `确认忽略反馈 #${item.feedback_id} 吗？复核结论会写入审计记录，之后不会再进入待复核队列。`,
      '忽略反馈',
      {
        type: 'warning',
        confirmButtonText: '确认忽略',
        cancelButtonText: '取消'
      }
    )
  } catch {
    return
  }
  const { data } = await api.post<EvaluationFeedbackCandidate>(`/evaluations/feedback/${item.feedback_id}/dismiss`, {
    request_id: feedbackRequestId('dismiss', item.feedback_id),
    reason: DISMISS_FEEDBACK_REASON
  })
  feedback.value = feedback.value.map((candidate) => candidate.feedback_id === data.feedback_id ? data : candidate)
  feedbackRequestIds.delete(`dismiss:${item.feedback_id}`)
  ElMessage.success('反馈已忽略')
}

onMounted(loadAll)
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.evaluation-page { max-width: 1480px; }
.evaluation-head { align-items: flex-end; margin-bottom: 14px; }
.evaluation-launcher { display: flex; align-items: flex-end; gap: 12px; margin-bottom: 18px; padding: 14px 16px; border-block: 1px solid var(--color-border); background: var(--color-surface); }
.launch-field { display: grid; min-width: 180px; gap: 6px; }
.launch-field :deep(.el-select) { width: 100%; }
.mode-field { min-width: 220px; }
.baseline-field { min-width: 270px; }
.launch-label { color: var(--color-secondary-text); font-size: 12px; font-weight: 650; }
.launch-action { margin-left: auto; }
.launch-action .el-button { min-height: 40px; margin: 0; }
.metric-band { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
.metric-tile { min-width: 0; padding: 16px 18px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); }
.metric-tile span, .metric-tile small { display: block; color: var(--color-muted-text); }
.metric-tile span { font-size: 12px; font-weight: 650; }
.metric-tile strong { display: block; margin: 6px 0 2px; color: var(--color-foreground); font-size: 24px; line-height: 1.2; font-variant-numeric: tabular-nums; }
.metric-tile small { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.active-run-band { display: grid; grid-template-columns: minmax(220px, .65fr) minmax(240px, 1fr) auto; align-items: center; gap: 20px; margin-bottom: 12px; padding: 14px 16px; border: 1px solid color-mix(in srgb, var(--color-primary) 28%, var(--color-border)); border-radius: 8px; background: var(--color-primary-soft); }
.active-run-copy { display: flex; align-items: center; gap: 10px; min-width: 0; }
.active-run-copy div { min-width: 0; }
.active-run-copy strong, .active-run-copy span { display: block; }
.active-run-copy strong { color: var(--color-primary-hover); font-size: 14px; }
.active-run-copy span { color: #475569; font-size: 12px; }
.live-indicator { width: 9px; height: 9px; flex: 0 0 9px; border-radius: 50%; background: var(--color-primary); box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-primary) 14%, transparent); }
.evaluation-tabs { min-width: 0; }
.view-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 14px; }
.toolbar-copy strong, .toolbar-copy span { display: block; }
.toolbar-copy strong { color: var(--color-foreground); font-size: 16px; }
.toolbar-copy span { color: var(--color-muted-text); font-size: 12px; }
.toolbar-filters { display: flex; align-items: center; gap: 8px; }
.toolbar-filters .el-input { width: 250px; }
.toolbar-filters .el-select { width: 150px; }
.run-link { display: block; padding: 0; border: 0; background: transparent; color: var(--color-primary); font: inherit; font-weight: 750; cursor: pointer; }
.run-link:hover { text-decoration: underline; }
.run-revision, .case-input { display: block; overflow: hidden; color: var(--color-muted-text); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.agent-version-list { display: flex; flex-wrap: wrap; gap: 4px 8px; color: var(--color-secondary-text); font-size: 12px; }
.agent-version-list small { color: var(--color-muted-text); }
.table-score { font-variant-numeric: tabular-nums; }
.gate-pass, .delta-positive { color: var(--color-success) !important; }
.gate-fail, .delta-negative { color: var(--color-danger) !important; }
.gate-pending, .delta-neutral { color: var(--color-muted-text) !important; }
.case-name { display: block; color: var(--color-foreground); }
.case-input { max-width: 360px; margin-top: 2px; }
.keyword-list { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.keyword-list small { color: var(--color-muted-text); }
.feedback-input, .feedback-agent, .feedback-comment, .feedback-answer, .feedback-meta { display: block; }
.feedback-input, .feedback-agent { color: var(--color-foreground); }
.feedback-input { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.feedback-comment { color: var(--color-danger); font-weight: 650; }
.feedback-answer { display: -webkit-box; margin-top: 3px; overflow: hidden; color: var(--color-muted-text); font-size: 12px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.feedback-meta { margin-top: 2px; color: var(--color-muted-text); font-size: 11px; }
.feedback-reviewed { color: var(--color-muted-text); font-size: 12px; }
.mobile-run-list, .mobile-case-list, .mobile-feedback-list { display: none; }
.run-detail { min-height: 180px; }
.detail-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; margin-bottom: 18px; overflow: hidden; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-border); }
.detail-summary div { min-width: 0; padding: 12px; background: var(--color-surface); }
.detail-summary span, .detail-summary strong { display: block; }
.detail-summary span { color: var(--color-muted-text); font-size: 11px; }
.detail-summary strong { margin-top: 3px; overflow: hidden; color: var(--color-foreground); font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.release-evidence { display: grid; grid-template-columns: minmax(210px, .8fr) minmax(240px, 1fr) auto; align-items: center; gap: 18px; margin-bottom: 18px; padding: 14px 16px; border: 1px solid color-mix(in srgb, var(--color-primary) 24%, var(--color-border)); border-radius: 8px; background: var(--color-primary-soft); }
.release-identity span, .release-identity strong, .release-identity small { display: block; }
.release-identity span { color: var(--color-primary-hover); font-size: 11px; font-weight: 700; }
.release-identity strong { margin-top: 3px; color: var(--color-foreground); font-size: 15px; overflow-wrap: anywhere; }
.release-identity small { margin-top: 2px; color: var(--color-muted-text); font-size: 11px; }
.release-state { display: flex; align-items: center; min-width: 0; gap: 8px; }
.release-state span { color: var(--color-secondary-text); font-size: 12px; overflow-wrap: anywhere; }
.release-actions { display: flex; justify-content: flex-end; gap: 8px; }
.release-actions .el-button { margin: 0; }
.detail-section { margin-top: 24px; }
.section-heading { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10px; }
.section-heading h2 { margin: 0; color: var(--color-foreground); font-size: 16px; }
.section-heading span { color: var(--color-muted-text); font-size: 12px; }
.dimension-table { border-top: 1px solid var(--color-border); }
.dimension-row { display: grid; grid-template-columns: 86px minmax(160px, 1fr) 104px; align-items: center; gap: 12px; min-height: 48px; border-bottom: 1px solid var(--color-border); }
.dimension-label { color: var(--color-secondary-text); font-size: 13px; font-weight: 650; }
.dimension-bars { display: grid; gap: 5px; }
.score-bar { height: 6px; overflow: hidden; border-radius: 3px; background: var(--color-border); }
.score-bar span { display: block; height: 100%; border-radius: inherit; }
.candidate-bar span { background: var(--color-primary); }
.baseline-bar span { background: var(--color-muted-text); }
.dimension-values { text-align: right; font-size: 13px; font-variant-numeric: tabular-nums; }
.dimension-values small { margin-left: 8px; color: var(--color-muted-text); }
.dimension-legend { display: flex; justify-content: flex-end; align-items: center; gap: 6px; margin-top: 8px; color: var(--color-muted-text); font-size: 11px; }
.dimension-legend span { width: 16px; height: 4px; margin-left: 8px; border-radius: 2px; }
.candidate-key { background: var(--color-primary); }
.baseline-key { background: var(--color-muted-text); }
.gate-failures { margin: 8px 0 0; padding-left: 20px; }
.result-title { display: grid; grid-template-columns: minmax(0, 1fr) 72px auto; align-items: center; gap: 10px; width: 100%; padding-right: 12px; }
.result-title > span:first-child { min-width: 0; }
.result-title strong, .result-title small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-title small { color: var(--color-muted-text); font-size: 11px; font-weight: 400; }
.result-title-score { text-align: right; font-weight: 750; font-variant-numeric: tabular-nums; }
.result-body { padding: 4px 2px 16px; }
.result-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-bottom: 12px; color: var(--color-muted-text); font-size: 11px; }
.case-prompt { display: grid; grid-template-columns: 68px 1fr; gap: 10px; margin: 0 0 14px; color: var(--color-secondary-text); line-height: 1.6; }
.answer-compare { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.answer-compare > div { min-width: 0; padding: 12px; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-background); }
.answer-compare strong { color: var(--color-secondary-text); font-size: 12px; }
.answer-compare p { margin: 8px 0 0; color: var(--color-foreground); line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.evidence-block { display: grid; gap: 8px; margin-top: 14px; }
.evidence-block > div { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.evidence-block strong { width: 72px; color: var(--color-secondary-text); font-size: 12px; }
.evidence-block span { color: var(--color-muted-text); font-size: 12px; }
.judge-reason { display: grid; grid-template-columns: 72px 1fr; gap: 5px; margin: 14px 0 0; color: var(--color-secondary-text); line-height: 1.6; }
.detail-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--color-border); }
.case-rule-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.feedback-source { overflow: hidden; margin-bottom: 18px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-background); }
.feedback-source-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 14px; border-bottom: 1px solid var(--color-border); background: var(--color-surface); }
.feedback-source-head span { color: var(--color-muted-text); font-size: 12px; font-weight: 650; }
.feedback-source-head strong { color: var(--color-secondary-text); font-size: 13px; }
.feedback-source dl { display: grid; margin: 0; }
.feedback-source dl div { display: grid; grid-template-columns: 88px minmax(0, 1fr); gap: 12px; padding: 11px 14px; border-bottom: 1px solid var(--color-border); }
.feedback-source dl div:last-child { border-bottom: 0; }
.feedback-source dt { color: var(--color-muted-text); font-size: 12px; font-weight: 650; }
.feedback-source dd { margin: 0; color: var(--color-secondary-text); line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
.feedback-rule-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }

@media (max-width: 980px) {
  .evaluation-launcher { flex-wrap: wrap; }
  .launch-field { flex: 1 1 220px; }
  .launch-action { margin-left: 0; }
  .metric-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .active-run-band { grid-template-columns: 1fr auto; }
  .active-run-band .el-progress { grid-column: 1 / -1; grid-row: 2; }
  .view-toolbar { align-items: flex-start; flex-direction: column; }
  .toolbar-filters { width: 100%; }
  .toolbar-filters .el-input { flex: 1; width: auto; }
  .release-evidence { grid-template-columns: 1fr auto; }
  .release-state { grid-column: 1 / -1; grid-row: 2; }
}

@media (max-width: 640px) {
  .evaluation-head { align-items: stretch; }
  .evaluation-launcher { align-items: stretch; flex-direction: column; padding: 12px 0; }
  .launch-field, .mode-field, .baseline-field { width: 100%; min-width: 0; }
  .launch-action { width: 100%; }
  .launch-action .el-button { width: 100%; min-height: 44px; }
  .metric-band { gap: 8px; }
  .metric-tile { padding: 13px 14px; }
  .metric-tile strong { font-size: 20px; }
  .active-run-band { grid-template-columns: 1fr; gap: 12px; }
  .active-run-band .el-progress { grid-column: auto; grid-row: auto; }
  .active-run-band .el-button { min-height: 44px; }
  .toolbar-filters { display: grid; grid-template-columns: 1fr auto; }
  .toolbar-filters .el-input { grid-column: 1 / -1; width: 100%; }
  .toolbar-filters .el-select { width: 100%; }
  .toolbar-filters .el-button { min-width: 44px; min-height: 44px; }
  .desktop-run-table, .desktop-case-table, .desktop-feedback-table { display: none; }
  .mobile-run-list, .mobile-case-list, .mobile-feedback-list { display: grid; gap: 10px; }
  .run-card, .case-card, .feedback-card { min-width: 0; padding: 14px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); }
  .run-card-main { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; min-height: 44px; padding: 0; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }
  .run-card-main span span, .run-card-main strong, .run-card-main small { display: block; }
  .run-card-main small { margin-top: 2px; color: var(--color-muted-text); font-size: 11px; }
  .run-card dl { display: grid; grid-template-columns: repeat(3, 1fr); margin: 12px 0; padding: 10px 0; border-block: 1px solid var(--color-border); }
  .run-card dl div { min-width: 0; }
  .run-card dt { color: var(--color-muted-text); font-size: 11px; }
  .run-card dd { margin: 3px 0 0; font-weight: 700; font-variant-numeric: tabular-nums; }
  .run-card-foot { display: flex; align-items: center; justify-content: space-between; color: var(--color-muted-text); font-size: 11px; }
  .case-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
  .case-card > span { display: block; margin-top: 3px; color: var(--color-primary); font-size: 12px; }
  .case-card p { display: -webkit-box; margin: 10px 0; overflow: hidden; color: var(--color-secondary-text); line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
  .case-card-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
  .case-card-actions .el-button { min-height: 44px; margin: 0; }
  .feedback-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
  .feedback-card-head > span { min-width: 0; }
  .feedback-card-head strong, .feedback-card-head small { display: block; }
  .feedback-card-head strong { color: var(--color-foreground); }
  .feedback-card-head small { margin-top: 2px; color: var(--color-muted-text); font-size: 11px; }
  .feedback-card-evidence { display: grid; gap: 10px; margin: 14px 0 0; }
  .feedback-card-evidence div { min-width: 0; }
  .feedback-card-evidence dt { color: var(--color-muted-text); font-size: 11px; font-weight: 650; }
  .feedback-card-evidence dd { display: -webkit-box; margin: 2px 0 0; overflow: hidden; color: var(--color-secondary-text); line-height: 1.5; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
  .feedback-card-evidence div:last-child dd { color: var(--color-danger); font-weight: 650; }
  .feedback-card-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 14px; }
  .feedback-card-actions .el-button { min-height: 44px; margin: 0; }
  .feedback-card-foot { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-top: 14px; color: var(--color-muted-text); font-size: 11px; }
  :deep(.el-input__inner), :deep(.el-textarea__inner) { font-size: 16px; }
  .detail-summary { grid-template-columns: repeat(2, 1fr); }
  .release-evidence { grid-template-columns: 1fr; gap: 12px; padding: 14px; }
  .release-state { grid-column: auto; grid-row: auto; align-items: flex-start; flex-direction: column; }
  .release-actions { justify-content: stretch; }
  .release-actions .el-button { width: 100%; min-height: 44px; }
  .dimension-row { grid-template-columns: 72px minmax(90px, 1fr) 86px; gap: 8px; }
  .result-title { grid-template-columns: minmax(0, 1fr) 58px; }
  .result-title .el-tag { display: none; }
  .answer-compare { grid-template-columns: 1fr; }
  .case-prompt, .judge-reason { grid-template-columns: 1fr; }
  .case-rule-grid { grid-template-columns: 1fr 1fr; }
  .feedback-source-head { align-items: flex-start; flex-direction: column; }
  .feedback-source dl div { grid-template-columns: 1fr; gap: 4px; }
  .feedback-rule-grid { grid-template-columns: 1fr 1fr; }
  :deep(.evaluation-feedback-dialog .el-dialog__footer .el-button) { min-height: 44px; }
}
</style>
