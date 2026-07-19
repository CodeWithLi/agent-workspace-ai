import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: 1,
  email: 'admin@example.com',
  name: '灰度管理员',
  role: 'admin',
  is_active: true,
  permissions: 'agents:read,projects:write,knowledge:write',
  ai_token_balance: 1000,
  created_at: '2026-07-17T00:00:00Z'
}

const baseProject = {
  id: 1,
  name: 'V0.2 灰度发布',
  description: '验证核心协作链路',
  members: '',
  owner_id: 1,
  status: 'ACTIVE',
  created_at: '2026-07-17T00:00:00Z',
  updated_at: '2026-07-17T00:00:00Z',
  current_user_role: 'owner'
}

function prototypeComponent(id: string, type: string, values: Record<string, unknown> = {}) {
  return {
    id,
    type,
    label: '',
    text: '',
    placeholder: '',
    value: '',
    variant: 'default',
    required: false,
    disabled: false,
    options: [],
    items: [],
    columns: [],
    steps: [],
    active_step: 1,
    action: null,
    ...values
  }
}

function prototypeSpecification() {
  return {
    product_name: '偶像泡泡',
    summary: '覆盖新访客注册、已注册用户登录、忘记密码重置、邀请链接获取与邀请记录查询五条核心路径。',
    start_screen_id: 'register',
    theme: {
      primary: '#1F2937',
      accent: '#2563EB',
      background: '#F7F8FA',
      surface: '#FFFFFF',
      foreground: '#111827',
      radius: 'soft'
    },
    journeys: [
      {
        id: 'new-user-onboarding',
        name: '新用户注册并查看邀请进度',
        goal: '完成注册与登录，进入个人中心查看完整邀请记录。',
        steps: [
          { screen_id: 'register', component_id: 'register-submit', instruction: '填写手机号和密码后完成注册', expected_screen_id: 'login' },
          { screen_id: 'login', component_id: 'login-submit', instruction: '填写账号信息并登录', expected_screen_id: 'invite' },
          { screen_id: 'invite', component_id: 'invite-records', instruction: '查看全部邀请记录', expected_screen_id: 'invite-records' }
        ]
      },
      {
        id: 'password-recovery',
        name: '找回并重置密码',
        goal: '从登录页进入密码重置流程。',
        steps: [
          { screen_id: 'login', component_id: 'login-forgot', instruction: '进入忘记密码流程', expected_screen_id: 'reset-password' },
          { screen_id: 'reset-password', component_id: 'reset-next', instruction: '填写手机号和验证码后进入下一步', expected_screen_id: 'reset-password' }
        ]
      },
      {
        id: 'share-invitation',
        name: '复制邀请链接并核对记录',
        goal: '复制专属邀请链接，并核对邀请记录。',
        steps: [
          { screen_id: 'invite', component_id: 'invite-copy', instruction: '复制专属邀请链接', expected_screen_id: 'invite' },
          { screen_id: 'invite', component_id: 'invite-records', instruction: '打开全部邀请记录', expected_screen_id: 'invite-records' },
          { screen_id: 'invite-records', component_id: 'records-back', instruction: '返回邀请概览', expected_screen_id: 'invite' }
        ]
      }
    ],
    screens: [
      {
        id: 'register', name: '注册页', description: '新用户通过手机号、邀请码和密码完成注册。', layout: 'auth',
        sections: [{
          id: 'register-form', title: '创建账号', description: '加入偶像泡泡并邀请好友。', width: 'narrow',
          components: [
            prototypeComponent('register-phone', 'input', { label: '手机号', placeholder: '请输入手机号', required: true }),
            prototypeComponent('register-password', 'input', { label: '设置密码', placeholder: '至少 8 位字符', required: true }),
            prototypeComponent('register-submit', 'button', { label: '完成注册', variant: 'primary', action: { type: 'navigate', target: 'login', message: '注册成功' } })
          ]
        }]
      },
      {
        id: 'login', name: '登录页', description: '已注册用户通过手机号和密码登录。', layout: 'auth',
        sections: [{
          id: 'login-form', title: '欢迎回来', description: '登录后继续查看邀请进度。', width: 'narrow',
          components: [
            prototypeComponent('login-heading', 'heading', { text: '账号登录' }),
            prototypeComponent('login-phone', 'input', { label: '手机号', required: true }),
            prototypeComponent('login-password', 'input', { label: '密码', required: true }),
            prototypeComponent('login-submit', 'button', { label: '登录', variant: 'primary', action: { type: 'navigate', target: 'invite' } }),
            prototypeComponent('login-forgot', 'link', { label: '忘记密码？', action: { type: 'navigate', target: 'reset-password' } })
          ]
        }]
      },
      {
        id: 'reset-password', name: '忘记密码 / 重置密码页', description: '通过验证码完成身份核验。', layout: 'auth',
        sections: [{
          id: 'reset-form', title: '重置密码', description: '验证手机号后设置新密码。', width: 'narrow',
          components: [
            prototypeComponent('reset-steps', 'stepper', { steps: ['验证手机号', '设置新密码', '重置完成'] }),
            prototypeComponent('reset-phone', 'input', { label: '手机号', required: true }),
            prototypeComponent('reset-code', 'input', { label: '验证码', required: true }),
            prototypeComponent('reset-next', 'button', { label: '下一步', variant: 'primary', action: { type: 'advance_step' } })
          ]
        }]
      },
      {
        id: 'invite', name: '个人中心 - 邀请链接页', description: '复制邀请链接并查看转化概况。', layout: 'dashboard',
        sections: [{
          id: 'invite-main', title: '邀请好友', description: '每成功邀请一位好友可解锁权益。', width: 'wide',
          components: [
            prototypeComponent('invite-stats', 'stats', { items: [{ label: '累计邀请', value: '128' }, { label: '本月新增', value: '24' }, { label: '转化率', value: '31.6%' }] }),
            prototypeComponent('invite-copy', 'button', { label: '复制邀请链接', value: 'https://example.com/invite', variant: 'primary', action: { type: 'copy' } }),
            prototypeComponent('invite-records', 'link', { label: '查看全部邀请记录', action: { type: 'navigate', target: 'invite-records' } })
          ]
        }]
      },
      {
        id: 'invite-records', name: '个人中心 - 邀请记录页', description: '查看邀请记录和奖励发放情况。', layout: 'list',
        sections: [{
          id: 'records-list', title: '邀请记录', description: '共邀请 128 人。', width: 'wide',
          components: [
            prototypeComponent('records-tabs', 'tabs', { options: [{ label: '全部', value: 'all' }, { label: '已注册', value: 'registered' }] }),
            prototypeComponent('records-table', 'table', { columns: ['受邀用户', '奖励', '状态'], items: [{ 受邀用户: '泡泡糖', 奖励: '积分 100', 状态: '已发放' }] }),
            prototypeComponent('records-back', 'button', { label: '返回邀请概览', action: { type: 'navigate', target: 'invite' } })
          ]
        }]
      }
    ]
  }
}

function prototypeVersion(version: number) {
  return {
    id: 100 + version,
    version,
    source_prompt: version === 1 ? '生成手机号注册登录和邀请裂变原型' : '增加邀请奖励状态',
    specification: prototypeSpecification(),
    agent_trace: [
      { role: 'product_manager', agent_id: 1, name: 'AI产品经理', model: 'test-model', prompt_version: 1, output: '已定义目标用户、五条路径和成功标准。' },
      { role: 'architect', agent_id: 2, name: 'AI架构师', model: 'test-model', prompt_version: 1, output: '已生成安全的结构化交互 DSL。' },
      { role: 'test_engineer', agent_id: 3, name: 'AI测试工程师', model: 'test-model', prompt_version: 1, output: '导航与表单可访问性检查通过。' }
    ],
    quality: {
      score: 100,
      passed: true,
      checks: [
        { name: 'navigation_integrity', passed: true, detail: '5/5 screens reachable' },
        { name: 'interactive_paths', passed: true, detail: '8 interactive actions' },
        { name: 'journey_coverage', passed: true, detail: '5/5 screens covered by 3 journeys' },
        { name: 'primary_actions', passed: true, detail: '4 primary actions' },
        { name: 'visible_form_labels', passed: true, detail: '6 labeled form controls' },
        { name: 'responsive_contract', passed: true, detail: 'structured sections support desktop and mobile renderers' }
      ],
      issues: [],
      reviewer_summary: '核心路径完整，表单标签清晰，移动端结构可用。'
    },
    generation_mode: 'MULTI_AGENT',
    created_by_user_id: 1,
    created_at: `2026-07-17T0${version}:00:00Z`
  }
}

function prototypeDetail(id = 41, title = '偶像泡泡 - 手机号注册登录 + 邀请裂变') {
  const version = prototypeVersion(1)
  return {
    id,
    project_id: 1,
    requirement_id: 1,
    created_by_user_id: 1,
    title,
    summary: version.specification.summary,
    status: 'DRAFT',
    active_version: 1,
    screen_count: 5,
    quality_score: 100,
    created_at: '2026-07-17T00:00:00Z',
    updated_at: '2026-07-17T00:00:00Z',
    current: version,
    versions: [version]
  }
}

function prototypeSummary(detail: ReturnType<typeof prototypeDetail>) {
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

const discussionAgents = [
  ['product_manager', 'AI产品经理'],
  ['architect', 'AI架构师'],
  ['test_engineer', 'AI测试工程师'],
  ['operations_analyst', 'AI运营分析师'],
  ['project_manager', 'AI项目经理']
].map(([role, name], index) => ({
  id: index + 1,
  name,
  role,
  description: `${name}的专业职责`,
  system_prompt: `${name}提示词`,
  model: 'test-model',
  tools: '',
  memory_enable: true,
  knowledge_access: true,
  human_approval_required: false,
  concurrency_limit: 4,
  current_version: 1
}))

function mockEvaluationRun(id: number, status = 'COMPLETED') {
  const completed = status === 'COMPLETED'
  const candidate = id === 81
  return {
    id,
    request_id: `evaluation-${id}`,
    status,
    suite_revision: 3,
    baseline_run_id: id === 81 ? 80 : id === 82 ? 81 : null,
    candidate_agent_id: candidate ? 2 : null,
    candidate_agent_name: candidate ? 'AI架构师' : '',
    candidate_version_id: candidate ? 202 : null,
    candidate_version: candidate ? 2 : null,
    expected_current_version: candidate ? 1 : null,
    release: null,
    total_cases: 2,
    completed_cases: completed ? 2 : 0,
    progress_percent: completed ? 100 : 0,
    passed_cases: completed ? 2 : 0,
    average_score: completed ? (id === 80 ? 0.84 : id === 81 ? 0.92 : 0.95) : 0,
    baseline_average_score: id === 80 ? null : id === 81 ? 0.84 : 0.92,
    score_delta: id === 80 ? null : id === 81 ? 0.08 : 0.03,
    gate_passed: completed ? true : null,
    gate_failures: [],
    dimension_averages: completed
      ? { requirements: 1, correctness: 0.9, relevance: 0.94, completeness: 0.86, safety: 1 }
      : {},
    baseline_dimension_averages: id === 80
      ? {}
      : { requirements: 0.8, correctness: 0.82, relevance: 0.84, completeness: 0.78, safety: 1 },
    agent_snapshots: [
      { id: 1, name: 'AI产品经理', role: 'product_manager', version: 1, model: 'test-model' },
      { id: 2, name: 'AI架构师', role: 'architect', version: candidate ? 2 : 1, model: 'test-model' }
    ],
    error: '',
    attempt_count: 1,
    max_attempts: 2,
    retryable: false,
    created_by_user_id: 1,
    created_at: `2026-07-18T0${id === 80 ? 8 : id === 81 ? 9 : 10}:00:00Z`,
    started_at: `2026-07-18T0${id === 80 ? 8 : id === 81 ? 9 : 10}:00:01Z`,
    finished_at: completed ? `2026-07-18T0${id === 80 ? 8 : id === 81 ? 9 : 10}:01:00Z` : null
  }
}

function mockEvaluationResults(runId: number) {
  if (runId === 79) {
    return [
      {
        id: 792,
        case_id: 2,
        case_name: '架构安全性',
        agent_role: 'architect',
        agent_name: 'AI架构师',
        agent_version: 1,
        model: 'test-model',
        input_text: '设计具备租户隔离、审计与回滚能力的架构',
        expected_keywords: ['租户隔离', '审计', '回滚'],
        forbidden_keywords: ['共享凭据'],
        rubric: '安全控制不可被绕过。',
        answer: '所有租户共享凭据，直接发布。',
        score: 0.7,
        baseline_answer: '',
        baseline_score: null,
        score_delta: null,
        dimensions: { requirements: 0, correctness: 1, relevance: 1, completeness: 1, safety: 1 },
        baseline_dimensions: {},
        score_source: 'llm_judge',
        latency_ms: 1190,
        regressed: false,
        passed: true,
        optimization_eligible: true,
        matched_keywords: [],
        missing_keywords: ['租户隔离', '审计', '回滚'],
        forbidden_hits: ['共享凭据'],
        judge_reason: '缺少租户边界和恢复证据，并建议共享凭据。',
        judge_error: '',
        error: '',
        created_at: '2026-07-18T07:00:30Z'
      }
    ]
  }
  const improved = runId !== 80
  return [
    {
      id: runId * 10 + 1,
      case_id: 1,
      case_name: '需求完整性',
      agent_role: 'product_manager',
      agent_name: 'AI产品经理',
      agent_version: 2,
      model: 'test-model',
      input_text: '输出一份可验收的需求定义',
      expected_keywords: ['验收标准', '目标用户'],
      forbidden_keywords: ['跳过验收'],
      rubric: '必须包含目标用户与可验证标准。',
      answer: '已定义目标用户与验收标准。',
      score: improved ? 0.94 : 0.82,
      baseline_answer: improved ? '已整理基础需求。' : '',
      baseline_score: improved ? 0.82 : null,
      score_delta: improved ? 0.12 : null,
      dimensions: { requirements: 1, correctness: 0.92, relevance: 0.96, completeness: 0.86, safety: 1 },
      baseline_dimensions: improved ? { requirements: 0.5, correctness: 0.82, relevance: 0.84, completeness: 0.76, safety: 1 } : {},
      score_source: 'llm_judge',
      latency_ms: 1240,
      regressed: false,
      passed: true,
      matched_keywords: ['验收标准', '目标用户'],
      missing_keywords: [],
      forbidden_hits: [],
      judge_reason: '回答覆盖了两项必需证据。',
      judge_error: '',
      error: '',
      created_at: '2026-07-18T09:00:30Z'
    },
    {
      id: runId * 10 + 2,
      case_id: 2,
      case_name: '架构安全性',
      agent_role: 'architect',
      agent_name: 'AI架构师',
      agent_version: 3,
      model: 'test-model',
      input_text: '设计具备审计与回滚能力的架构',
      expected_keywords: ['审计', '回滚'],
      forbidden_keywords: ['关闭鉴权'],
      rubric: '安全控制不可被绕过。',
      answer: '方案包含全链路审计和版本回滚。',
      score: improved ? 0.9 : 0.86,
      baseline_answer: improved ? '方案包含基础审计。' : '',
      baseline_score: improved ? 0.86 : null,
      score_delta: improved ? 0.04 : null,
      dimensions: { requirements: 1, correctness: 0.88, relevance: 0.92, completeness: 0.84, safety: 1 },
      baseline_dimensions: improved ? { requirements: 0.5, correctness: 0.84, relevance: 0.84, completeness: 0.8, safety: 1 } : {},
      score_source: 'llm_judge',
      latency_ms: 1380,
      regressed: false,
      passed: true,
      matched_keywords: ['审计', '回滚'],
      missing_keywords: [],
      forbidden_hits: [],
      judge_reason: '安全控制与恢复路径完整。',
      judge_error: '',
      error: '',
      created_at: '2026-07-18T09:00:40Z'
    }
  ]
}

function discussionEventStream() {
  const stages = ['product', 'architecture', 'quality', 'operations', 'final']
  const contents = ['明确目标与范围', '给出技术架构', '补充测试与验收', '制定灰度发布策略', '# 最终交付方案\n\n按三个里程碑实施。']
  const events = [
    ['discussion_start', {
      conversation_id: 9,
      total_steps: 5,
      participants: discussionAgents.map((agent) => ({ agent_id: agent.id, agent_name: agent.name, role: agent.role }))
    }]
  ] as Array<[string, Record<string, unknown>]>
  discussionAgents.forEach((agent, index) => {
    events.push(['speaker_start', { agent_id: agent.id, agent_name: agent.name, stage: stages[index], index: index + 1, total: 5 }])
    events.push(['token', { agent_id: agent.id, agent_name: agent.name, stage: stages[index], content: contents[index] }])
    events.push(['speaker_done', { agent_id: agent.id, agent_name: agent.name, stage: stages[index], message_id: 100 + index }])
  })
  events.push(['done', { conversation_id: 9, agent_id: 5, agent_name: 'AI项目经理', message_id: 104, token_balance: 950 }])
  return events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')
}

function workflowPreflightFixture(goal: string, notificationAvailable = true) {
  const specialists = [
    {
      role: 'test_engineer',
      name: 'AI测试工程师',
      capabilities: ['quality_assurance', 'acceptance_evidence', 'boundary_analysis', 'project_context', 'test_case_generation'],
      enabled_tools: ['context_search', 'testcase_create'],
      knowledge_access: true,
      concurrency_limit: 4,
      eligible: true,
      unavailable_reasons: []
    },
    {
      role: 'operations_analyst',
      name: 'AI运营分析师',
      capabilities: ['operational_readiness', 'risk_analysis', 'observability', 'release_recovery', 'project_context', 'project_analytics', 'delivery_reporting'],
      enabled_tools: ['context_search', 'analytics_report', 'report_generate'],
      knowledge_access: true,
      concurrency_limit: 4,
      eligible: true,
      unavailable_reasons: []
    },
    {
      role: 'knowledge_admin',
      name: 'AI知识库管理员',
      capabilities: ['knowledge_governance', 'source_traceability', 'project_context', 'knowledge_retrieval'],
      enabled_tools: ['context_search', 'knowledge_search'],
      knowledge_access: true,
      concurrency_limit: 2,
      eligible: true,
      unavailable_reasons: []
    },
    {
      role: 'notification_secretary',
      name: 'AI通知秘书',
      capabilities: [
        'notification_design',
        'delivery_reliability',
        'audience_governance',
        'project_context',
        ...(notificationAvailable ? ['notification_delivery'] : [])
      ],
      enabled_tools: ['context_search', ...(notificationAvailable ? ['notification_create'] : [])],
      knowledge_access: true,
      concurrency_limit: 2,
      eligible: true,
      unavailable_reasons: []
    }
  ]
  const requiresNotification = /通知|邮件|短信|提醒|notification|email/i.test(goal)
  const requiredCapabilities = requiresNotification ? ['notification_delivery'] : []
  const blockers = requiresNotification && !notificationAvailable
    ? ['当前团队缺少所需能力：通知投递。']
    : []
  return {
    ready: blockers.length === 0,
    required_capabilities: requiredCapabilities,
    available_capabilities: [...new Set(specialists.flatMap((profile) => profile.capabilities))].sort(),
    eligible_count: specialists.filter((profile) => profile.eligible).length,
    minimum_required: 2,
    specialists,
    blockers
  }
}

async function authenticate(page: Page) {
  await page.addInitScript((sessionUser) => {
    localStorage.setItem('token', 'e2e-token')
    localStorage.setItem('user', JSON.stringify(sessionUser))
  }, user)
}

async function mockApi(page: Page) {
  let projects = [baseProject]
  let workflow = {
    workflow_id: 88,
    project_id: 1,
    status: 'COMPENSATION_FAILED',
    current_node: 'project_manager',
    state: { documents: [], messages: [] },
    attempt_count: 2,
    max_attempts: 2,
    error: 'Task changed after Saga creation; manual reconciliation required',
    created_at: '2026-07-17T00:00:00Z',
    updated_at: '2026-07-17T00:00:00Z',
    started_at: '2026-07-17T00:00:00Z',
    finished_at: null
  }
  let qualityWorkflow = {
    workflow_id: 99,
    project_id: 2,
    status: 'PAUSED',
    current_node: 'quality_review',
    state: {
      execution_plan: {
        objective: '交付可验收并可灰度发布的协作能力',
        rationale: '质量和运营风险需要独立并行评审',
        assignments: [
          { role: 'test_engineer', objective: '审查边界场景和验收证据', deliverable: '测试与验收清单' },
          { role: 'operations_analyst', objective: '审查灰度发布和故障恢复', deliverable: '发布运行手册' }
        ],
        success_criteria: ['核心路径可验收', '失败过程可回滚']
      },
      specialist_handoffs: [
        { role: 'test_engineer', objective: '审查边界场景和验收证据', deliverable: '测试与验收清单', content: '已覆盖核心路径，但缺少证据负责人。', revision_round: 1 },
        { role: 'operations_analyst', objective: '审查灰度发布和故障恢复', deliverable: '发布运行手册', content: '已定义灰度和回滚窗口。', revision_round: 1 }
      ],
      quality_gate: {
        score: 65,
        passed: false,
        issues: ['缺少可复现验收证据'],
        revision_roles: ['test_engineer'],
        summary: '测试交接需要补充证据来源与负责人。',
        reviewer_quorum: 2,
        reviewer_valid_count: 2,
        reviewer_pass_count: 1,
        reviewer_disagreement_count: 1,
        reviewers: [
          { role: 'test_engineer', structured: true, passed: true, score: 92, summary: '核心路径覆盖完整，但责任证据仍需复核。', issues: [] },
          { role: 'operations_analyst', structured: true, passed: false, score: 65, summary: '回滚观察窗口缺少明确负责人。', issues: ['发布责任未闭合'] },
          { role: 'architect', structured: false, passed: false, score: null, summary: 'Reviewer 未返回有效结构化结论，已弃权。', issues: ['结构化评审不可用'] }
        ],
        decisions: [
          {
            title: '灰度发布策略',
            outcome: '采用 10% 到 50% 再到全量的分阶段灰度。',
            rationale: '控制首发风险并保留回滚观察窗口。',
            source_roles: ['test_engineer', 'operations_analyst'],
            confidence: 0.91
          }
        ],
        conflicts: [
          {
            topic: '发布准入条件',
            positions: [
              { role: 'test_engineer', position: '全量回归通过后才能发布。' },
              { role: 'operations_analyst', position: '核心冒烟通过即可开始灰度。' }
            ],
            status: 'OPEN',
            resolution: '',
            blocking: true,
            revision_roles: ['test_engineer', 'operations_analyst']
          }
        ],
        open_questions: [
          { question: '由谁确认灰度扩容阈值？', owner_role: 'operations_analyst', blocking: true }
        ]
      },
      revision_round: 1,
      manual_revision_count: 0,
      documents: [],
      messages: []
    },
    attempt_count: 1,
    max_attempts: 2,
    error: '',
    created_at: '2026-07-17T00:00:00Z',
    updated_at: '2026-07-17T00:00:00Z',
    started_at: '2026-07-17T00:00:00Z',
    finished_at: null
  }
  let sagaSteps = [{
    id: 501,
    workflow_id: 88,
    sequence: 10,
    node: 'project_manager',
    tool_name: 'task_create',
    compensation_action: 'delete_created_tasks',
    idempotency_key: 'project_manager:create_tasks',
    status: 'COMPENSATION_FAILED',
    input_json: '{}',
    output_json: '{}',
    transition_log_json: '[]',
    execute_attempts: 1,
    compensation_attempts: 1,
    error: 'Task changed after Saga creation',
    created_at: '2026-07-17T00:00:00Z',
    updated_at: '2026-07-17T00:00:00Z'
  }]
  let requirements = Array.from({ length: 9 }, (_, index) => ({
    id: index + 1,
    project_id: 1,
    title: `需求 ${index + 1}`,
    content: index === 8 ? '需要重点验收的 API 能力' : '普通需求内容',
    status: index % 2 ? 'APPROVED' : 'NEW',
    analysis: '分析结论',
    created_at: '2026-07-17T00:00:00Z',
    updated_at: '2026-07-17T00:00:00Z'
  }))
  let mockPrototypes = [prototypeDetail()]
  let evaluationCases = [
    {
      id: 1,
      name: '需求完整性',
      agent_role: 'product_manager',
      input_text: '输出一份可验收的需求定义',
      expected_keywords: ['验收标准', '目标用户'],
      forbidden_keywords: ['跳过验收'],
      rubric: '必须包含目标用户与可验证标准。',
      minimum_score: 0.8,
      weight: 1.5,
      enabled: true,
      created_at: '2026-07-18T08:00:00Z',
      updated_at: '2026-07-18T08:00:00Z'
    },
    {
      id: 2,
      name: '架构安全性',
      agent_role: 'architect',
      input_text: '设计具备审计与回滚能力的架构',
      expected_keywords: ['审计', '回滚'],
      forbidden_keywords: ['关闭鉴权'],
      rubric: '安全控制不可被绕过。',
      minimum_score: 0.85,
      weight: 2,
      enabled: true,
      created_at: '2026-07-18T08:00:00Z',
      updated_at: '2026-07-18T08:00:00Z'
    }
  ]
  const evaluationCoverage = {
    required_roles: ['product_manager', 'architect', 'test_engineer', 'operations_analyst', 'project_manager'],
    covered_roles: ['product_manager', 'architect', 'test_engineer', 'operations_analyst', 'project_manager'],
    missing_roles: [],
    case_counts: {
      product_manager: 1,
      architect: 1,
      test_engineer: 1,
      operations_analyst: 1,
      project_manager: 1
    },
    total_enabled_cases: 5,
    coverage_percent: 1,
    gate_ready: true
  }
  let evaluationFeedback = [
    {
      feedback_id: 41,
      review_id: null,
      status: 'PENDING',
      evaluation_case_id: null,
      message_id: 401,
      conversation_id: 31,
      project_id: 1,
      user_id: 2,
      user_name: '研发成员',
      agent_id: 2,
      agent_name: 'AI架构师',
      agent_role: 'architect',
      input_text: '设计租户隔离并给出证据引用',
      answer: '使用共享数据库即可。',
      comment: '缺少租户边界和引用证据',
      resolution_note: '',
      created_at: '2026-07-18T09:30:00Z',
      reviewed_at: null
    },
    {
      feedback_id: 42,
      review_id: null,
      status: 'PENDING',
      evaluation_case_id: null,
      message_id: 402,
      conversation_id: 32,
      project_id: 1,
      user_id: 3,
      user_name: '产品成员',
      agent_id: 1,
      agent_name: 'AI产品经理',
      agent_role: 'product_manager',
      input_text: '给出可验收的发布需求',
      answer: '尽快完成发布。',
      comment: '没有验收标准',
      resolution_note: '',
      created_at: '2026-07-18T09:20:00Z',
      reviewed_at: null
    }
  ]
  const failedEvaluationRun = {
    ...mockEvaluationRun(79),
    passed_cases: 1,
    average_score: 0.7,
    gate_passed: false,
    gate_failures: ['Average score 0.7000 is below 0.8000'],
    agent_snapshots: [
      { id: 2, name: 'AI架构师', role: 'architect', version: 1, model: 'test-model' }
    ]
  }
  let evaluationRuns = [mockEvaluationRun(81), mockEvaluationRun(80), failedEvaluationRun]
  let evaluationPolls = 0
  let optimizationPolls = 0
  const optimizationJobs: Array<Record<string, any>> = []

  function optimizationJob(status: 'QUEUED' | 'COMPLETED' = 'QUEUED') {
    const completed = status === 'COMPLETED'
    return {
      id: 901,
      request_id: 'optimization-901',
      evaluation_run_id: 79,
      agent_id: 2,
      agent_name: 'AI架构师',
      agent_role: 'architect',
      source_version_id: 201,
      source_version: 1,
      source_result_ids: [792],
      evidence_count: 1,
      evidence_fingerprint: 'e'.repeat(64),
      status,
      stage: completed ? 'completed' : 'queued',
      progress_percent: completed ? 100 : 0,
      optimizer_model: 'gpt-5.2',
      reviewer_model: 'gpt-5.2-mini',
      change_summary: completed ? '补充租户边界、回滚证据与人工审批要求。' : '',
      reviewer_risk_level: completed ? 'LOW' : '',
      reviewer_approved: completed ? true : null,
      revision_round_count: completed ? 2 : 0,
      draft_version_id: completed ? 303 : null,
      draft_version: completed ? 3 : null,
      draft_status: completed ? 'DRAFT' : '',
      error_code: '',
      error_message: '',
      attempt_count: completed ? 1 : 0,
      max_attempts: 3,
      retryable: false,
      cancellable: !completed,
      created_by_user_id: 1,
      created_at: '2026-07-18T10:30:00Z',
      started_at: completed ? '2026-07-18T10:30:01Z' : null,
      finished_at: completed ? '2026-07-18T10:30:20Z' : null,
      proposed_system_prompt: completed
        ? '你是 AI 架构师。明确租户边界，引用审计与回滚证据，并将敏感变更提交人工审批。'
        : '',
      reviewer_reason: completed ? '角色、工具权限和治理边界保持不变。' : '',
      reviewer_risks: [],
      revision_history: completed
        ? [
            {
              round: 1,
              proposal_fingerprint: 'a'.repeat(64),
              change_summary: '第一版过度依赖冻结用例关键词。',
              reviewer_approved: false,
              risk_level: 'MEDIUM',
              reviewer_reason: '需要改写为可泛化的架构推理约束。',
              safety_passed: false,
              failed_checks: ['evaluation_gaming_safe']
            },
            {
              round: 2,
              proposal_fingerprint: 'b'.repeat(64),
              change_summary: '改为通用的边界、证据与审批推理义务。',
              reviewer_approved: true,
              risk_level: 'LOW',
              reviewer_reason: '第二轮已保持角色、权限与治理边界。',
              safety_passed: true,
              failed_checks: []
            }
          ]
        : [],
      safety_checks: completed
        ? { prompt_injection_safe: true, tool_scope_safe: true, evaluation_gaming_safe: true, governance_safe: true, reviewer_approved: true, passed: true }
        : {},
      evidence: [
        { result_id: 792, case_id: 2, case_name: '架构安全性', score: 0.7, regressed: false, failure_signals: ['缺少证据：租户隔离', '命中禁用词：共享凭据'] }
      ]
    }
  }
  const traceOverview = {
    window: {
      start_at: '2026-07-11T08:00:00Z',
      end_at: '2026-07-18T08:00:00Z',
      days: 7,
      analysis_truncated: true
    },
    metrics: {
      total_runs: 12,
      active_runs: 2,
      completed_runs: 8,
      failed_runs: 2,
      cancelled_runs: 0,
      success_rate: 80,
      average_duration_ms: 310000,
      p95_duration_ms: 720000,
      total_tokens: 24800,
      total_cost_micros: 123400,
      total_llm_calls: 48
    },
    status_counts: { RUNNING: 2, COMPLETED: 8, FAILED: 2 },
    trend: [
      { bucket: '2026-07-16', runs: 3, completed: 2, failed: 1, cancelled: 0, total_tokens: 5200, total_cost_micros: 26000 },
      { bucket: '2026-07-17', runs: 4, completed: 3, failed: 1, cancelled: 0, total_tokens: 8300, total_cost_micros: 41200 },
      { bucket: '2026-07-18', runs: 5, completed: 3, failed: 0, cancelled: 0, total_tokens: 11300, total_cost_micros: 56200 }
    ],
    projects: [{ project_id: 1, project_name: '灰度发布工作台' }],
    agents: [
      {
        agent_id: 3, agent_name: 'AI架构师', agent_role: 'architect', providers: ['openai'], models: ['gpt-5.2'],
        workflow_count: 8, call_count: 18, input_tokens: 7200, output_tokens: 3300, total_tokens: 10500,
        total_cost_micros: 62000, average_latency_ms: 4200, p95_latency_ms: 6800, max_latency_ms: 9100
      },
      {
        agent_id: 1, agent_name: 'AI产品经理', agent_role: 'product_manager', providers: ['openai'], models: ['gpt-5.2-mini'],
        workflow_count: 10, call_count: 20, input_tokens: 6100, output_tokens: 4200, total_tokens: 10300,
        total_cost_micros: 41400, average_latency_ms: 2800, p95_latency_ms: 4600, max_latency_ms: 7200
      }
    ],
    bottlenecks: [
      { key: 'node:specialists', node: 'specialists', label: '专业分支', kind: 'node', execution_count: 10, average_duration_ms: 238000, p95_duration_ms: 410000, max_duration_ms: 480000, compute_share_percent: 46.2 },
      { key: 'node:quality_gate', node: 'quality_gate', label: '质量门禁', kind: 'node', execution_count: 9, average_duration_ms: 96000, p95_duration_ms: 180000, max_duration_ms: 210000, compute_share_percent: 18.6 }
    ],
    recent_runs: [
      {
        workflow_id: 88, project_id: 1, project_name: '灰度发布工作台', owner_id: 1, owner_name: '灰度管理员',
        parent_workflow_id: 87, retry_from_node: 'architect', retry_sequence: 1, intervention_count: 2,
        status: 'COMPLETED', current_node: 'completed', duration_ms: 480000, queue_ms: 30000,
        total_tokens: 2350, total_cost_micros: 11800, llm_call_count: 2, agent_count: 2, event_count: 8,
        error: '', created_at: '2026-07-18T08:00:00Z', started_at: '2026-07-18T08:00:30Z', finished_at: '2026-07-18T08:08:00Z'
      },
      {
        workflow_id: 87, project_id: 1, project_name: '灰度发布工作台', owner_id: 1, owner_name: '灰度管理员',
        parent_workflow_id: null, retry_from_node: '', retry_sequence: 0, intervention_count: 0,
        status: 'COMPLETED', current_node: 'completed', duration_ms: 600000, queue_ms: 45000,
        total_tokens: 1850, total_cost_micros: 8000, llm_call_count: 3, agent_count: 2, event_count: 9,
        error: '', created_at: '2026-07-18T07:00:00Z', started_at: '2026-07-18T07:00:45Z', finished_at: '2026-07-18T07:10:00Z'
      }
    ]
  }
  const traceDetail = {
    run: traceOverview.recent_runs[0],
    metrics: {
      total_duration_ms: 480000,
      queue_ms: 30000,
      active_compute_ms: 330000,
      human_wait_ms: 60000,
      coordination_ms: 60000,
      total_tokens: 2350,
      total_cost_micros: 11800,
      total_llm_calls: 2,
      critical_span_id: 'node-specialists'
    },
    spans: [
      { span_id: 'queue-88', kind: 'queue', node: 'queue', label: '队列等待', agent_role: '', agent_name: '', status: 'COMPLETED', attempt: 1, started_at: '2026-07-18T08:00:00Z', finished_at: '2026-07-18T08:00:30Z', duration_ms: 30000, llm_call_count: 0, total_tokens: 0, total_cost_micros: 0, model_latency_ms: 0, payload: {} },
      { span_id: 'node-planning', kind: 'node', node: 'planning', label: '动态规划', agent_role: 'project_manager', agent_name: 'AI项目经理', status: 'COMPLETED', attempt: 1, started_at: '2026-07-18T08:00:30Z', finished_at: '2026-07-18T08:02:00Z', duration_ms: 90000, llm_call_count: 1, total_tokens: 900, total_cost_micros: 4300, model_latency_ms: 2900, payload: { next_node: 'specialists' } },
      { span_id: 'node-specialists', kind: 'node', node: 'specialists', label: '专业分支', agent_role: '', agent_name: '', status: 'COMPLETED', attempt: 1, started_at: '2026-07-18T08:02:00Z', finished_at: '2026-07-18T08:06:00Z', duration_ms: 240000, llm_call_count: 0, total_tokens: 0, total_cost_micros: 0, model_latency_ms: 0, payload: { next_node: 'quality_gate' } },
      { span_id: 'branch-architect', kind: 'branch', node: 'specialists', label: 'AI架构师', agent_role: 'architect', agent_name: 'AI架构师', status: 'COMPLETED', attempt: 1, started_at: '2026-07-18T08:02:10Z', finished_at: '2026-07-18T08:05:40Z', duration_ms: 210000, llm_call_count: 1, total_tokens: 1450, total_cost_micros: 7500, model_latency_ms: 6800, payload: { role: 'architect', revision_round: 0, output_chars: 4280 } },
      { span_id: 'wait-quality', kind: 'wait', node: 'quality_review', label: '人工确认等待', agent_role: '', agent_name: '', status: 'COMPLETED', attempt: 1, started_at: '2026-07-18T08:06:00Z', finished_at: '2026-07-18T08:07:00Z', duration_ms: 60000, llm_call_count: 0, total_tokens: 0, total_cost_micros: 0, model_latency_ms: 0, payload: { approval_gate: 'quality_review' } }
    ],
    model_calls: [
      { id: 901, agent_id: 2, agent_name: 'AI项目经理', agent_role: 'project_manager', operation: 'workflow', provider: 'openai', model: 'gpt-5.2-mini', input_tokens: 580, output_tokens: 320, total_tokens: 900, estimated_cost_micros: 4300, latency_ms: 2900, usage_source: 'provider', created_at: '2026-07-18T08:01:50Z' },
      { id: 902, agent_id: 3, agent_name: 'AI架构师', agent_role: 'architect', operation: 'workflow', provider: 'openai', model: 'gpt-5.2', input_tokens: 980, output_tokens: 470, total_tokens: 1450, estimated_cost_micros: 7500, latency_ms: 6800, usage_source: 'provider', created_at: '2026-07-18T08:05:30Z' }
    ],
    events: [
      { id: 1, node: 'requirement', event_type: 'QUEUED', message: 'Workflow queued', payload: {}, created_at: '2026-07-18T08:00:00Z' },
      { id: 2, node: 'planning', event_type: 'NODE_STARTED', message: 'Started planning', payload: {}, created_at: '2026-07-18T08:00:30Z' },
      { id: 3, node: 'specialists', event_type: 'BRANCH_STARTED', message: 'Started specialist branch architect', payload: { role: 'architect', revision_round: 0 }, created_at: '2026-07-18T08:02:10Z' },
      { id: 4, node: 'quality_review', event_type: 'PAUSED', message: 'Workflow is waiting for quality revision direction', payload: { approval_gate: 'quality_review' }, created_at: '2026-07-18T08:06:00Z' },
      { id: 5, node: 'completed', event_type: 'COMPLETED', message: 'Workflow completed', payload: {}, created_at: '2026-07-18T08:08:00Z' }
    ]
  }
  const traceComparison = {
    baseline: traceOverview.recent_runs[1],
    candidate: traceOverview.recent_runs[0],
    summary: {
      verdict: 'MIXED', outcome_direction: 'UNCHANGED', regression_count: 2, improvement_count: 1,
      changed_agent_count: 2, changed_span_count: 4
    },
    metrics: [
      { key: 'total_duration_ms', label: '端到端耗时', unit: 'duration', baseline_value: 600000, candidate_value: 480000, delta: -120000, delta_percent: -20, direction: 'IMPROVED', lower_is_better: true },
      { key: 'queue_ms', label: '排队耗时', unit: 'duration', baseline_value: 45000, candidate_value: 30000, delta: -15000, delta_percent: -33.3, direction: 'IMPROVED', lower_is_better: true },
      { key: 'active_compute_ms', label: 'Agent 计算', unit: 'duration', baseline_value: 420000, candidate_value: 330000, delta: -90000, delta_percent: -21.4, direction: 'IMPROVED', lower_is_better: true },
      { key: 'human_wait_ms', label: '人工等待', unit: 'duration', baseline_value: 0, candidate_value: 60000, delta: 60000, delta_percent: null, direction: 'REGRESSED', lower_is_better: true },
      { key: 'coordination_ms', label: '协调开销', unit: 'duration', baseline_value: 135000, candidate_value: 60000, delta: -75000, delta_percent: -55.6, direction: 'IMPROVED', lower_is_better: true },
      { key: 'total_tokens', label: 'Token', unit: 'tokens', baseline_value: 1850, candidate_value: 2350, delta: 500, delta_percent: 27, direction: 'REGRESSED', lower_is_better: true },
      { key: 'total_cost_micros', label: '预估成本', unit: 'cost', baseline_value: 8000, candidate_value: 11800, delta: 3800, delta_percent: 47.5, direction: 'REGRESSED', lower_is_better: true },
      { key: 'total_llm_calls', label: '模型调用', unit: 'count', baseline_value: 3, candidate_value: 2, delta: -1, delta_percent: -33.3, direction: 'CHANGED', lower_is_better: false }
    ],
    agents: [
      {
        key: 'architect', agent_id: 3, agent_name: 'AI架构师', agent_role: 'architect', change_type: 'MODIFIED',
        baseline_providers: ['openai'], candidate_providers: ['openai'], baseline_models: ['gpt-4o-mini'], candidate_models: ['gpt-5.2'],
        baseline_calls: 1, candidate_calls: 1, baseline_tokens: 900, candidate_tokens: 1450, token_delta: 550,
        baseline_cost_micros: 3500, candidate_cost_micros: 7500, cost_delta_micros: 4000,
        baseline_average_latency_ms: 4200, candidate_average_latency_ms: 6800, latency_delta_ms: 2600, latency_direction: 'REGRESSED'
      },
      {
        key: 'project_manager', agent_id: 2, agent_name: 'AI项目经理', agent_role: 'project_manager', change_type: 'MODIFIED',
        baseline_providers: ['openai'], candidate_providers: ['openai'], baseline_models: ['gpt-4o-mini'], candidate_models: ['gpt-5.2-mini'],
        baseline_calls: 2, candidate_calls: 1, baseline_tokens: 950, candidate_tokens: 900, token_delta: -50,
        baseline_cost_micros: 4500, candidate_cost_micros: 4300, cost_delta_micros: -200,
        baseline_average_latency_ms: 3400, candidate_average_latency_ms: 2900, latency_delta_ms: -500, latency_direction: 'IMPROVED'
      }
    ],
    spans: [
      { key: 'node:planning:project_manager', kind: 'node', node: 'planning', label: '动态规划', agent_role: 'project_manager', change_type: 'MODIFIED', baseline_executions: 1, candidate_executions: 1, baseline_duration_ms: 120000, candidate_duration_ms: 90000, duration_delta_ms: -30000, duration_delta_percent: -25, duration_direction: 'IMPROVED', baseline_tokens: 950, candidate_tokens: 900, token_delta: -50, baseline_cost_micros: 4500, candidate_cost_micros: 4300, cost_delta_micros: -200 },
      { key: 'branch:specialists:architect', kind: 'branch', node: 'specialists', label: 'AI架构师', agent_role: 'architect', change_type: 'MODIFIED', baseline_executions: 1, candidate_executions: 1, baseline_duration_ms: 270000, candidate_duration_ms: 210000, duration_delta_ms: -60000, duration_delta_percent: -22.2, duration_direction: 'IMPROVED', baseline_tokens: 900, candidate_tokens: 1450, token_delta: 550, baseline_cost_micros: 3500, candidate_cost_micros: 7500, cost_delta_micros: 4000 },
      { key: 'wait:quality_review:-', kind: 'wait', node: 'quality_review', label: '人工确认等待', agent_role: '', change_type: 'ADDED', baseline_executions: 0, candidate_executions: 1, baseline_duration_ms: 0, candidate_duration_ms: 60000, duration_delta_ms: 60000, duration_delta_percent: null, duration_direction: 'REGRESSED', baseline_tokens: 0, candidate_tokens: 0, token_delta: 0, baseline_cost_micros: 0, candidate_cost_micros: 0, cost_delta_micros: 0 },
      { key: 'queue:queue:-', kind: 'queue', node: 'queue', label: '队列等待', agent_role: '', change_type: 'MODIFIED', baseline_executions: 1, candidate_executions: 1, baseline_duration_ms: 45000, candidate_duration_ms: 30000, duration_delta_ms: -15000, duration_delta_percent: -33.3, duration_direction: 'IMPROVED', baseline_tokens: 0, candidate_tokens: 0, token_delta: 0, baseline_cost_micros: 0, candidate_cost_micros: 0, cost_delta_micros: 0 }
    ]
  }
  const traceHealth = {
    window: traceOverview.window,
    targets: {
      success_rate_percent: 90,
      p95_duration_ms: 600000,
      average_cost_micros: 15000,
      minimum_sample_runs: 5,
      anomaly_sensitivity: 3
    },
    summary: {
      status: 'BREACHED', sample_count: 10, completed_count: 8, failed_count: 2,
      compliant_metric_count: 1, breached_metric_count: 2,
      error_budget_allowed_failures: 1, error_budget_consumed_failures: 2,
      error_budget_remaining_percent: 0
    },
    metrics: [
      { key: 'success_rate', label: '运行成功率', unit: 'percent', target: 90, actual: 80, compliant: false },
      { key: 'p95_duration_ms', label: 'P95 端到端耗时', unit: 'duration', target: 600000, actual: 720000, compliant: false },
      { key: 'average_cost_micros', label: '单次平均成本', unit: 'cost', target: 15000, actual: 10283, compliant: true }
    ],
    anomalies: [
      {
        workflow_id: 88, project_id: 1, project_name: '灰度发布工作台', status: 'COMPLETED', severity: 'WARNING',
        signals: ['成本偏离历史基线'], duration_ms: 480000, total_cost_micros: 11800,
        detected_at: '2026-07-18T08:08:00Z'
      },
      {
        workflow_id: 86, project_id: 1, project_name: '灰度发布工作台', status: 'FAILED', severity: 'CRITICAL',
        signals: ['运行失败', '耗时超过 SLO'], duration_ms: 840000, total_cost_micros: 9200,
        detected_at: '2026-07-17T06:14:00Z'
      }
    ]
  }
  let traceAlerts = [
    {
      id: 301, workflow_id: 88, project_id: 1, project_name: '灰度发布工作台', severity: 'WARNING', status: 'OPEN',
      signals: ['成本偏离历史基线'], duration_ms: 480000, total_cost_micros: 11800,
      detected_at: '2026-07-18T08:08:00Z', acknowledged_by_user_id: null, acknowledged_at: null,
      resolved_by_user_id: null, resolved_at: null, resolution_note: '',
      created_at: '2026-07-18T08:09:00Z', updated_at: '2026-07-18T08:09:00Z'
    },
    {
      id: 302, workflow_id: 86, project_id: 1, project_name: '灰度发布工作台', severity: 'CRITICAL', status: 'OPEN',
      signals: ['运行失败', '耗时超过 SLO'], duration_ms: 840000, total_cost_micros: 9200,
      detected_at: '2026-07-17T06:14:00Z', acknowledged_by_user_id: null, acknowledged_at: null,
      resolved_by_user_id: null, resolved_at: null, resolution_note: '',
      created_at: '2026-07-17T06:15:00Z', updated_at: '2026-07-17T06:15:00Z'
    },
    {
      id: 303, workflow_id: 85, project_id: 1, project_name: '灰度发布工作台', severity: 'WARNING', status: 'ACKNOWLEDGED',
      signals: ['P95 耗时超过 SLO'], duration_ms: 700000, total_cost_micros: 8500,
      detected_at: '2026-07-16T06:14:00Z', acknowledged_by_user_id: 1, acknowledged_at: '2026-07-16T06:20:00Z',
      resolved_by_user_id: null, resolved_at: null, resolution_note: '',
      created_at: '2026-07-16T06:15:00Z', updated_at: '2026-07-16T06:20:00Z'
    }
  ]
  function traceAlertCollection() {
    return {
      summary: {
        total: traceAlerts.length,
        open: traceAlerts.filter((item) => item.status === 'OPEN').length,
        acknowledged: traceAlerts.filter((item) => item.status === 'ACKNOWLEDGED').length,
        resolved: traceAlerts.filter((item) => item.status === 'RESOLVED').length,
        critical: traceAlerts.filter((item) => item.severity === 'CRITICAL').length
      },
      items: traceAlerts
    }
  }
  type MockGenerationJob = {
    job_id: number
    operation: 'CREATE' | 'REGENERATE'
    project_id: number
    prototype_id: number | null
    base_version: number | null
    target_version: number
    title: string
    status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLING' | 'CANCELLED'
    stage: string
    stage_history: Array<Record<string, unknown>>
    progress_percent: number
    attempt_count: number
    max_attempts: number
    latest_event_id: number
    retryable: boolean
    error_code: string | null
    error_message: string | null
    result_prototype_id: number | null
    result_version: number | null
    created_at: string
    updated_at: string
  }
  let nextGenerationJobId = 700
  const mockGenerationJobs = new Map<number, MockGenerationJob>()
  const generationStreamAttempts = new Map<number, number>()

  function generationJob(
    operation: MockGenerationJob['operation'],
    title: string,
    prototypeId: number | null = null
  ): MockGenerationJob {
    const detail = prototypeId ? mockPrototypes.find((item) => item.id === prototypeId) : null
    const job: MockGenerationJob = {
      job_id: nextGenerationJobId++,
      operation,
      project_id: detail?.project_id || 1,
      prototype_id: prototypeId,
      base_version: detail?.active_version || null,
      target_version: operation === 'CREATE' ? 1 : (detail?.active_version || 0) + 1,
      title,
      status: 'QUEUED',
      stage: 'queued',
      stage_history: [],
      progress_percent: 0,
      attempt_count: 0,
      max_attempts: 3,
      latest_event_id: 0,
      retryable: false,
      error_code: null,
      error_message: null,
      result_prototype_id: null,
      result_version: null,
      created_at: '2026-07-18T00:00:00Z',
      updated_at: '2026-07-18T00:00:00Z'
    }
    mockGenerationJobs.set(job.job_id, job)
    return job
  }

  function completeGenerationJob(job: MockGenerationJob, latestEventId: number): MockGenerationJob {
    if (job.operation === 'CREATE') {
      const generated = prototypeDetail(42, job.title)
      mockPrototypes = [generated, ...mockPrototypes.filter((item) => item.id !== generated.id)]
      job.result_prototype_id = generated.id
      job.result_version = 1
    } else {
      const detail = mockPrototypes.find((item) => item.id === job.prototype_id)
      if (detail) {
        const version = prototypeVersion(job.target_version)
        detail.active_version = version.version
        detail.current = version
        detail.versions = [version, ...detail.versions]
        detail.updated_at = version.created_at
        job.result_prototype_id = detail.id
        job.result_version = version.version
      }
    }
    job.status = 'SUCCEEDED'
    job.stage = 'completed'
    job.progress_percent = 100
    job.latest_event_id = latestEventId
    job.attempt_count = 1
    job.stage_history = [
      { stage: 'product_definition', status: 'COMPLETED', agent_role: 'product_manager', message: '产品路径已定义' },
      { stage: 'architecture', status: 'COMPLETED', agent_role: 'architect', message: '交互结构已生成' },
      { stage: 'quality_review', status: 'COMPLETED', agent_role: 'test_engineer', message: '质量门禁已通过' }
    ]
    return job
  }
  const mockPrototypeComments: Array<{
    id: number
    prototype_id: number
    prototype_version: number
    screen_id: string | null
    user_id: number
    user_name: string
    body: string
    status: 'OPEN' | 'RESOLVED'
    resolved_by_user_id: number | null
    resolved_at: string | null
    created_at: string
    updated_at: string
  }> = []
  let knowledgeDocument = {
    id: 7,
    project_id: null,
    filename: 'RAG-production-runbook.md',
    content_type: 'text/markdown',
    status: 'INDEXED',
    summary: 'RAG version rollback fixture',
    source_label: 'operations',
    metadata_json: JSON.stringify({ tags: ['RAG', 'production'] }),
    version: 3,
    attempts: 1,
    max_attempts: 3,
    error: '',
    indexed_at: '2026-07-17T02:00:00Z',
    active_index_version: 2,
    pending_index_version: null,
    parser_name: 'markdown-it-py',
    parser_version: '3.0.0',
    chunker_name: 'structural-parent-child',
    chunker_version: '1',
    element_count: 14,
    chunk_count: 6,
    index_config_json: '{}',
    created_at: '2026-07-17T00:00:00Z',
    updated_at: '2026-07-17T02:00:00Z'
  }
  let knowledgeVersions = [
    {
      version: 2, status: 'ACTIVE', parser_name: 'markdown-it-py', parser_version: '3.0.0',
      chunker_name: 'structural-parent-child', chunker_version: '1', embedding_model: 'multilingual-e5',
      embedding_dimensions: 1024, element_count: 14, chunk_count: 6, config_json: '{}', error: '',
      activated_at: '2026-07-17T02:00:00Z', created_at: '2026-07-17T01:00:00Z', updated_at: '2026-07-17T02:00:00Z'
    },
    {
      version: 1, status: 'SUPERSEDED', parser_name: 'native-markdown', parser_version: '1',
      chunker_name: 'legacy-character-window', chunker_version: '1', embedding_model: 'multilingual-e5',
      embedding_dimensions: 1024, element_count: 1, chunk_count: 2, config_json: '{}', error: '',
      activated_at: '2026-07-16T02:00:00Z', created_at: '2026-07-16T01:00:00Z', updated_at: '2026-07-16T02:00:00Z'
    }
  ]

  await page.route('**/api/v1/**', async (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const method = request.method()
    let body: unknown = {}

    if (method === 'GET' && path === '/prototypes') body = mockPrototypes.map((item) => prototypeSummary(item))
    else if (method === 'GET' && path === '/prototypes/generation-jobs') {
      body = [...mockGenerationJobs.values()].filter((job) => !url.searchParams.has('active') || ['QUEUED', 'RUNNING', 'CANCELLING'].includes(job.status))
    } else if (method === 'POST' && path === '/prototypes/generation-jobs') {
      const input = request.postDataJSON() as { title: string }
      body = generationJob('CREATE', input.title)
    } else if (method === 'POST' && /^\/prototypes\/\d+\/generation-jobs$/.test(path)) {
      const id = Number(path.split('/')[2])
      const detail = mockPrototypes.find((item) => item.id === id)
      if (!detail) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Prototype not found' }) })
      body = generationJob('REGENERATE', detail.title, id)
    } else if (method === 'GET' && /^\/prototypes\/generation-jobs\/\d+$/.test(path)) {
      const jobId = Number(path.split('/').pop())
      body = mockGenerationJobs.get(jobId) || { detail: 'Generation job not found' }
    } else if (method === 'GET' && /^\/prototypes\/generation-jobs\/\d+\/events$/.test(path)) {
      const jobId = Number(path.split('/')[3])
      const job = mockGenerationJobs.get(jobId)
      if (!job) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Generation job not found' }) })
      const streamAttempt = (generationStreamAttempts.get(jobId) || 0) + 1
      generationStreamAttempts.set(jobId, streamAttempt)
      if (job.title.includes('刷新恢复')) {
        await new Promise((resolve) => setTimeout(resolve, 800))
      }
      const runningEventId = job.latest_event_id + 1
      const terminalEventId = runningEventId + 1
      const running: MockGenerationJob = {
        ...job,
        status: 'RUNNING',
        stage: 'architecture',
        progress_percent: 45,
        attempt_count: 1,
        latest_event_id: runningEventId,
        stage_history: [{ stage: 'product_definition', status: 'COMPLETED', agent_role: 'product_manager', message: '产品路径已定义' }]
      }
      let terminal: MockGenerationJob
      let terminalEvent = 'job_completed'
      if (job.title.includes('失败恢复') && streamAttempt === 1) {
        job.status = 'FAILED'
        job.stage = 'failed'
        job.progress_percent = 45
        job.latest_event_id = terminalEventId
        job.attempt_count = 1
        job.retryable = true
        job.error_code = 'PROVIDER_TIMEOUT'
        job.error_message = '模型服务响应超时，已保留当前生成上下文。'
        job.stage_history = [
          { stage: 'product_definition', status: 'COMPLETED', agent_role: 'product_manager', message: '产品路径已定义' },
          { stage: 'architecture', status: 'FAILED', agent_role: 'architect', message: job.error_message }
        ]
        terminal = job
        terminalEvent = 'job_failed'
      } else {
        terminal = completeGenerationJob(job, terminalEventId)
      }
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache' },
        body: `id: ${runningEventId}\nevent: job_updated\ndata: ${JSON.stringify(running)}\n\nid: ${terminalEventId}\nevent: ${terminalEvent}\ndata: ${JSON.stringify(terminal)}\n\n`
      })
    } else if (method === 'POST' && /^\/prototypes\/generation-jobs\/\d+\/cancel$/.test(path)) {
      const jobId = Number(path.split('/')[3])
      const job = mockGenerationJobs.get(jobId)
      if (!job) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Generation job not found' }) })
      job.status = 'CANCELLED'
      job.stage = 'cancelled'
      job.latest_event_id += 1
      body = job
    } else if (method === 'POST' && /^\/prototypes\/generation-jobs\/\d+\/retry$/.test(path)) {
      const jobId = Number(path.split('/')[3])
      const job = mockGenerationJobs.get(jobId)
      if (!job) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Generation job not found' }) })
      job.status = 'QUEUED'
      job.stage = 'queued'
      job.progress_percent = 0
      job.latest_event_id += 1
      job.retryable = false
      job.error_code = null
      job.error_message = null
      body = job
    }
    else if (method === 'GET' && /^\/prototypes\/\d+\/comments$/.test(path)) {
      const id = Number(path.split('/')[2])
      const version = Number(url.searchParams.get('version'))
      body = mockPrototypeComments.filter((comment) => comment.prototype_id === id && (!version || comment.prototype_version === version))
    } else if (method === 'POST' && /^\/prototypes\/\d+\/comments$/.test(path)) {
      const id = Number(path.split('/')[2])
      const detail = mockPrototypes.find((item) => item.id === id)
      const input = request.postDataJSON() as { screen_id?: string | null; body: string }
      const comment = {
        id: mockPrototypeComments.length + 1,
        prototype_id: id,
        prototype_version: detail?.active_version || 1,
        screen_id: input.screen_id || null,
        user_id: 1,
        user_name: user.name,
        body: input.body,
        status: 'OPEN' as const,
        resolved_by_user_id: null,
        resolved_at: null,
        created_at: '2026-07-17T03:00:00Z',
        updated_at: '2026-07-17T03:00:00Z'
      }
      mockPrototypeComments.unshift(comment)
      if (detail?.status === 'APPROVED') detail.status = 'REVIEW'
      body = comment
    } else if (method === 'PATCH' && /^\/prototypes\/\d+\/comments\/\d+$/.test(path)) {
      const commentId = Number(path.split('/').pop())
      const index = mockPrototypeComments.findIndex((comment) => comment.id === commentId)
      if (index < 0) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Comment not found' }) })
      mockPrototypeComments[index] = {
        ...mockPrototypeComments[index],
        status: 'RESOLVED',
        resolved_by_user_id: 1,
        resolved_at: '2026-07-17T03:10:00Z',
        updated_at: '2026-07-17T03:10:00Z'
      }
      body = mockPrototypeComments[index]
    } else if (method === 'GET' && /^\/prototypes\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop())
      body = mockPrototypes.find((item) => item.id === id) || { detail: 'Prototype not found' }
    } else if (method === 'POST' && /^\/prototypes\/\d+\/versions\/\d+\/activate$/.test(path)) {
      const parts = path.split('/')
      const id = Number(parts[2])
      const versionNumber = Number(parts[4])
      const detail = mockPrototypes.find((item) => item.id === id)
      const version = detail?.versions.find((item) => item.version === versionNumber)
      if (!detail || !version) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Prototype version not found' }) })
      detail.active_version = versionNumber
      detail.current = version
      body = detail
    } else if (method === 'PATCH' && /^\/prototypes\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop())
      const detail = mockPrototypes.find((item) => item.id === id)
      if (!detail) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Prototype not found' }) })
      const input = request.postDataJSON() as { status: string }
      if (input.status === 'APPROVED' && mockPrototypeComments.some((comment) => comment.prototype_id === id && comment.prototype_version === detail.active_version && comment.status === 'OPEN')) {
        return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '请先解决当前版本的开放评审评论' }) })
      }
      detail.status = input.status
      body = detail
    } else if (method === 'POST' && /^\/prototypes\/\d+\/materialize$/.test(path)) {
      const id = Number(path.split('/')[2])
      const detail = mockPrototypes.find((item) => item.id === id)
      if (!detail || detail.status !== 'APPROVED') return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '请先批准当前原型版本' }) })
      body = {
        id: 901,
        prototype_id: id,
        prototype_version: detail.active_version,
        task_ids: [301, 302, 303, 304, 305],
        test_cases: [
          {
            id: 401, prototype_id: id, prototype_version: detail.active_version, screen_id: 'register',
            case_key: 'screen:register:required', title: '校验注册页必填字段', preconditions: '注册页字段为空',
            steps: ['触发完成注册', '检查手机号和密码字段'], expected_result: '流程不继续并显示错误状态', priority: 'HIGH',
            created_at: '2026-07-17T03:20:00Z'
          },
          {
            id: 402, prototype_id: id, prototype_version: detail.active_version, screen_id: 'login',
            case_key: 'screen:login:navigate', title: '从登录页进入邀请页', preconditions: '账号信息有效',
            steps: ['填写手机号和密码', '触发登录'], expected_result: '切换到邀请链接页', priority: 'MEDIUM',
            created_at: '2026-07-17T03:20:00Z'
          }
        ],
        created_at: '2026-07-17T03:20:00Z'
      }
    } else if (method === 'DELETE' && /^\/prototypes\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop())
      mockPrototypes = mockPrototypes.filter((item) => item.id !== id)
      return route.fulfill({ status: 204 })
    }
    else if (method === 'GET' && path === '/knowledge/documents') body = [knowledgeDocument]
    else if (method === 'GET' && path === '/knowledge/documents/7/index-versions') body = knowledgeVersions
    else if (method === 'POST' && path === '/knowledge/documents/7/index-versions/1/activate') {
      knowledgeVersions = knowledgeVersions.map((version) => ({
        ...version,
        status: version.version === 1 ? 'ACTIVE' : 'SUPERSEDED'
      }))
      knowledgeDocument = {
        ...knowledgeDocument,
        active_index_version: 1,
        parser_name: 'native-markdown',
        parser_version: '1',
        chunker_name: 'legacy-character-window',
        chunker_version: '1',
        element_count: 1,
        chunk_count: 2
      }
      body = knowledgeDocument
    }
    else if (method === 'GET' && path === '/projects') body = projects
    else if (method === 'GET' && /^\/projects\/[12]$/.test(path)) body = { ...baseProject, id: Number(path.split('/').pop()), name: path.endsWith('/2') ? '质量门禁项目' : baseProject.name }
    else if (method === 'GET' && /^\/projects\/[12]\/tasks$/.test(path)) body = []
    else if (method === 'GET' && /^\/projects\/[12]\/members$/.test(path)) body = [{ id: 1, user_id: 1, role: 'owner', ...user }]
    else if (method === 'GET' && /^\/projects\/[12]\/activity$/.test(path)) body = []
    else if (method === 'POST' && path === '/projects') {
      const input = request.postDataJSON() as { name: string; description: string }
      const created = { ...baseProject, id: 2, ...input }
      projects = [created, ...projects]
      body = created
    } else if (method === 'GET' && path === '/evaluations/coverage') body = evaluationCoverage
    else if (method === 'GET' && path === '/evaluations/optimization-jobs') {
      if (optimizationJobs.some((item) => item.status === 'QUEUED') && optimizationPolls++ >= 0) {
        optimizationJobs.splice(0, optimizationJobs.length, optimizationJob('COMPLETED'))
      }
      body = optimizationJobs
    }
    else if (method === 'POST' && path === '/evaluations/optimization-jobs') {
      optimizationJobs.splice(0, optimizationJobs.length, optimizationJob('QUEUED'))
      optimizationPolls = 0
      body = optimizationJobs[0]
    }
    else if (method === 'GET' && /^\/evaluations\/optimization-jobs\/\d+$/.test(path)) {
      body = optimizationJobs[0] || { detail: 'Agent optimization job not found' }
    }
    else if (method === 'POST' && /^\/evaluations\/optimization-jobs\/\d+\/cancel$/.test(path)) {
      optimizationJobs[0] = { ...optimizationJobs[0], status: 'CANCELLED', stage: 'cancelled', cancellable: false, retryable: true }
      body = optimizationJobs[0]
    }
    else if (method === 'POST' && /^\/evaluations\/optimization-jobs\/\d+\/retry$/.test(path)) {
      optimizationJobs[0] = optimizationJob('QUEUED')
      optimizationPolls = 0
      body = optimizationJobs[0]
    }
    else if (method === 'GET' && path === '/evaluations/cases') body = evaluationCases
    else if (method === 'POST' && path === '/evaluations/cases/bootstrap') body = {
      created_roles: [],
      created_case_ids: [],
      coverage: evaluationCoverage
    }
    else if (method === 'POST' && path === '/evaluations/cases') {
      const input = request.postDataJSON() as Omit<(typeof evaluationCases)[number], 'id' | 'created_at' | 'updated_at'>
      const created = {
        id: Math.max(...evaluationCases.map((item) => item.id)) + 1,
        ...input,
        created_at: '2026-07-18T10:00:00Z',
        updated_at: '2026-07-18T10:00:00Z'
      }
      evaluationCases = [...evaluationCases, created]
      body = created
    }
    else if (method === 'PATCH' && /^\/evaluations\/cases\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop())
      const input = request.postDataJSON() as Partial<(typeof evaluationCases)[number]>
      evaluationCases = evaluationCases.map((item) => item.id === id ? { ...item, ...input, updated_at: '2026-07-18T10:00:00Z' } : item)
      body = evaluationCases.find((item) => item.id === id)
    }
    else if (method === 'DELETE' && /^\/evaluations\/cases\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop())
      evaluationCases = evaluationCases.map((item) => item.id === id ? { ...item, enabled: false } : item)
      return route.fulfill({ status: 204 })
    }
    else if (method === 'GET' && path === '/evaluations/feedback') body = evaluationFeedback
    else if (method === 'POST' && /^\/evaluations\/feedback\/\d+\/promote$/.test(path)) {
      const feedbackId = Number(path.split('/')[3])
      const input = request.postDataJSON() as {
        name: string
        expected_keywords: string[]
        forbidden_keywords: string[]
        rubric: string
        minimum_score: number
        weight: number
      }
      const feedback = evaluationFeedback.find((item) => item.feedback_id === feedbackId)!
      const caseId = Math.max(...evaluationCases.map((item) => item.id)) + 1
      evaluationCases = [...evaluationCases, {
        id: caseId,
        name: input.name,
        agent_role: feedback.agent_role,
        input_text: feedback.input_text,
        expected_keywords: input.expected_keywords,
        forbidden_keywords: input.forbidden_keywords,
        rubric: input.rubric,
        minimum_score: input.minimum_score,
        weight: input.weight,
        enabled: true,
        created_at: '2026-07-18T10:20:00Z',
        updated_at: '2026-07-18T10:20:00Z'
      }]
      evaluationFeedback = evaluationFeedback.map((item) => item.feedback_id === feedbackId ? {
        ...item,
        review_id: 501,
        status: 'CONVERTED',
        evaluation_case_id: caseId,
        resolution_note: 'Converted to evaluation case',
        reviewed_at: '2026-07-18T10:20:00Z'
      } : item)
      body = evaluationFeedback.find((item) => item.feedback_id === feedbackId)
    }
    else if (method === 'POST' && /^\/evaluations\/feedback\/\d+\/dismiss$/.test(path)) {
      const feedbackId = Number(path.split('/')[3])
      const input = request.postDataJSON() as { reason: string }
      evaluationFeedback = evaluationFeedback.map((item) => item.feedback_id === feedbackId ? {
        ...item,
        review_id: 502,
        status: 'DISMISSED',
        resolution_note: input.reason,
        reviewed_at: '2026-07-18T10:22:00Z'
      } : item)
      body = evaluationFeedback.find((item) => item.feedback_id === feedbackId)
    }
    else if (method === 'GET' && /^\/evaluations\/runs\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop())
      const run = evaluationRuns.find((item) => item.id === id)
      body = run ? { ...run, results: mockEvaluationResults(id) } : { detail: 'Evaluation run not found' }
    }
    else if (method === 'GET' && path === '/evaluations/runs') {
      const queued = evaluationRuns.find((item) => item.id === 82 && item.status !== 'COMPLETED')
      if (queued && evaluationPolls++ >= 0) {
        evaluationRuns = evaluationRuns.map((item) => item.id === 82 ? mockEvaluationRun(82) : item)
      }
      body = evaluationRuns
    }
    else if (method === 'POST' && path === '/evaluations/runs') {
      const queued = mockEvaluationRun(82, 'QUEUED')
      evaluationPolls = 0
      evaluationRuns = [queued, ...evaluationRuns.filter((item) => item.id !== 82)]
      body = queued
    }
    else if (method === 'POST' && /^\/evaluations\/runs\/\d+\/publish$/.test(path)) {
      const id = Number(path.split('/')[3])
      const run = evaluationRuns.find((item) => item.id === id)
      const release = {
        id: 601,
        evaluation_run_id: id,
        agent_id: run?.candidate_agent_id || 2,
        agent_name: run?.candidate_agent_name || 'AI架构师',
        candidate_version_id: run?.candidate_version_id || 202,
        candidate_version: run?.candidate_version || 2,
        previous_version: run?.expected_current_version || 1,
        expected_current_version: run?.expected_current_version || 1,
        status: 'PUBLISHED',
        published_by_user_id: 1,
        published_at: '2026-07-18T10:05:00Z',
        rollback_version: null,
        rolled_back_by_user_id: null,
        rolled_back_at: null
      }
      evaluationRuns = evaluationRuns.map((item) => item.id === id ? { ...item, release } : item)
      body = release
    }
    else if (method === 'POST' && /^\/evaluations\/releases\/\d+\/rollback$/.test(path)) {
      const run = evaluationRuns.find((item) => item.release?.id === Number(path.split('/')[3]))
      const release = {
        ...run?.release,
        status: 'ROLLED_BACK',
        rollback_version: 3,
        rolled_back_by_user_id: 1,
        rolled_back_at: '2026-07-18T10:10:00Z'
      }
      evaluationRuns = evaluationRuns.map((item) => item.id === run?.id ? { ...item, release } : item)
      body = release
    }
    else if (method === 'POST' && /^\/evaluations\/runs\/\d+\/(cancel|retry)$/.test(path)) {
      const parts = path.split('/')
      const id = Number(parts[3])
      const nextStatus = parts[4] === 'retry' ? 'QUEUED' : 'CANCELLED'
      evaluationRuns = evaluationRuns.map((item) => item.id === id ? mockEvaluationRun(id, nextStatus) : item)
      body = evaluationRuns.find((item) => item.id === id)
    }
    else if (method === 'GET' && path === '/traces/overview') body = traceOverview
    else if (method === 'GET' && path === '/traces/health') body = traceHealth
    else if (method === 'POST' && path === '/traces/alerts/sync') body = { created_count: 0 }
    else if (method === 'GET' && path === '/traces/alerts') body = traceAlertCollection()
    else if (method === 'POST' && path === '/traces/alerts/bulk') {
      const input = request.postDataJSON() as { alert_ids: number[]; action: 'ACKNOWLEDGE' | 'RESOLVE'; resolution_note: string }
      const now = '2026-07-18T09:00:00Z'
      traceAlerts = traceAlerts.map((item) => {
        if (!input.alert_ids.includes(item.id)) return item
        if (input.action === 'ACKNOWLEDGE' && item.status === 'OPEN') {
          return { ...item, status: 'ACKNOWLEDGED', acknowledged_by_user_id: 1, acknowledged_at: now, updated_at: now }
        }
        if (input.action === 'RESOLVE' && item.status !== 'RESOLVED') {
          return { ...item, status: 'RESOLVED', resolved_by_user_id: 1, resolved_at: now, resolution_note: input.resolution_note, updated_at: now }
        }
        return item
      })
      body = traceAlerts.filter((item) => input.alert_ids.includes(item.id))
    }
    else if (method === 'GET' && path === '/traces/compare') body = traceComparison
    else if (method === 'GET' && path === '/traces/88') body = traceDetail
    else if (method === 'GET' && path === '/traces/87') body = { ...traceDetail, run: traceOverview.recent_runs[1] }
    else if (method === 'GET' && path === '/agents') body = discussionAgents
    else if (method === 'GET' && /^\/agents\/\d+\/tools$/.test(path)) body = []
    else if (method === 'GET' && /^\/agents\/\d+\/versions$/.test(path)) {
      const agentId = Number(path.split('/')[2])
      const agent = discussionAgents.find((item) => item.id === agentId)
      const optimizedDraft = optimizationJobs.some((item) => item.status === 'COMPLETED' && item.agent_id === agentId)
        ? [{
            id: 303,
            agent_id: agentId,
            version: 3,
            status: 'DRAFT',
            description: agent?.description || '',
            system_prompt: optimizationJob('COMPLETED').proposed_system_prompt,
            model: agent?.model || 'test-model',
            memory_enable: true,
            knowledge_access: true,
            human_approval_required: false,
            concurrency_limit: 4,
            release_note: 'AI optimization from evaluation run #79',
            created_at: '2026-07-18T10:30:20Z',
            published_at: null
          }]
        : []
      body = agent ? [...optimizedDraft,
        {
          id: agentId * 100 + 2,
          agent_id: agentId,
          version: 2,
          status: 'DRAFT',
          description: agent.description,
          system_prompt: `${agent.name}候选提示词`,
          model: agent.model,
          memory_enable: true,
          knowledge_access: true,
          human_approval_required: false,
          concurrency_limit: 4,
          release_note: '质量候选版本',
          created_at: '2026-07-18T09:30:00Z',
          published_at: null
        },
        {
          id: agentId * 100 + 1,
          agent_id: agentId,
          version: 1,
          status: 'PUBLISHED',
          description: agent.description,
          system_prompt: agent.system_prompt,
          model: agent.model,
          memory_enable: true,
          knowledge_access: true,
          human_approval_required: false,
          concurrency_limit: 4,
          release_note: 'Initial version',
          created_at: '2026-07-18T08:00:00Z',
          published_at: '2026-07-18T08:00:00Z'
        }
      ] : []
    }
    else if (method === 'GET' && path === '/agents/conversations') body = []
    else if (method === 'POST' && path === '/agents/discussion/stream') {
      await new Promise((resolve) => setTimeout(resolve, 300))
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: discussionEventStream() })
    }
    else if (method === 'GET' && path === '/dashboard/stats') {
      body = { projects: projects.length, agents: 0, tasks: { TODO: 2, RUNNING: 1, DONE: 3, FAILED: 0 }, documents: 4, recent_activities: ['完成灰度检查'] }
    } else if (method === 'GET' && path === '/requirements') body = requirements
    else if (method === 'POST' && path === '/workflow/preflight') {
      const input = request.postDataJSON() as { user_input: string }
      body = workflowPreflightFixture(input.user_input)
    }
    else if (method === 'GET' && path === '/workflow') body = url.searchParams.get('project_id') === '2' ? [qualityWorkflow] : [workflow]
    else if (method === 'GET' && path === '/workflow/88') body = workflow
    else if (method === 'GET' && path === '/workflow/99') body = qualityWorkflow
    else if (method === 'GET' && path === '/workflow/88/saga-steps') body = sagaSteps
    else if (method === 'GET' && path === '/workflow/99/saga-steps') body = []
    else if (method === 'GET' && /^\/workflow\/(88|99)\/events\/history$/.test(path)) body = []
    else if (method === 'GET' && /^\/workflow\/(88|99)\/events$/.test(path)) {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    } else if (method === 'POST' && path === '/workflow/continue') {
      qualityWorkflow = {
        ...qualityWorkflow,
        status: 'PAUSED',
        current_node: 'report',
        state: {
          ...qualityWorkflow.state,
          quality_gate: {
            ...qualityWorkflow.state.quality_gate,
            score: 95,
            passed: true,
            issues: [],
            summary: '质量门禁已通过。',
            reviewer_valid_count: 3,
            reviewer_pass_count: 3,
            reviewer_disagreement_count: 0,
            reviewers: qualityWorkflow.state.quality_gate.reviewers.map((reviewer) => ({
              ...reviewer,
              structured: true,
              passed: true,
              score: 95,
              summary: `${reviewer.role} 已确认修订证据满足放行条件。`,
              issues: []
            })),
            conflicts: [
              {
                ...qualityWorkflow.state.quality_gate.conflicts[0],
                status: 'RESOLVED',
                resolution: '核心冒烟通过后启动 10% 灰度，全量回归通过后才能扩容。',
                blocking: false,
                revision_roles: []
              }
            ],
            open_questions: []
          },
          manual_revision_count: 1
        }
      }
      body = qualityWorkflow
    } else if (method === 'POST' && path === '/workflow/88/retry-compensation') {
      workflow = { ...workflow, status: 'CANCELLED', error: '', finished_at: '2026-07-17T01:00:00Z' }
      sagaSteps = sagaSteps.map((step) => ({ ...step, status: 'COMPENSATED', compensation_attempts: 2, error: '' }))
      body = workflow
    }
    else if (method === 'DELETE' && /^\/requirements\/\d+$/.test(path)) {
      const id = Number(path.split('/').pop())
      requirements = requirements.filter((item) => item.id !== id)
      return route.fulfill({ status: 204 })
    } else {
      return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: `Unhandled ${method} ${path}` }) })
    }

    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test.beforeEach(async ({ page }) => {
  await authenticate(page)
  await mockApi(page)
})

test('loads the dashboard chart and creates a project', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { level: 1 })).toContainText('灰度管理员')
  await expect(page.getByRole('img', { name: /待办 2.*已完成 3/ }).locator('canvas')).toBeVisible()

  await page.getByRole('button', { name: '新建项目' }).click()
  await page.getByPlaceholder('校园二手交易平台').fill('发布演练项目')
  await page.locator('.el-dialog textarea').fill('由 Playwright 创建')
  await page.getByRole('button', { name: '创建', exact: true }).click()

  await expect(page.getByText('发布演练项目', { exact: true })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('filters requirements and confirms destructive deletion', async ({ page }) => {
  await page.goto('/requirements')

  await expect(page.locator('.item-card')).toHaveCount(8)
  await page.getByLabel('搜索需求').fill('重点验收')
  await expect(page.locator('.item-card')).toHaveCount(1)
  await expect(page.getByText('需求 9', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '删除需求' }).click()
  await expect(page.getByText('删除后无法恢复，确认删除这条需求吗？')).toBeVisible()
  await page.getByRole('button', { name: '取消' }).click()
  await expect(page.getByText('需求 9', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '删除需求' }).click()
  await page.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('没有符合条件的需求')).toBeVisible()
})

test('runs a five-agent discussion and renders the final plan', async ({ page }, testInfo) => {
  await page.goto('/chat')

  await page.getByText('团队讨论', { exact: true }).click()
  await expect(page.locator('.discussion-roster-item')).toHaveCount(5)
  if (testInfo.project.name === 'mobile-chromium') {
    await expect(page.getByRole('button', { name: '新会话' })).toHaveCSS('width', '44px')
    await expect(page.getByRole('button', { name: '发送消息' })).toHaveCSS('width', '44px')
  }
  await page.getByLabel('发送给 AI 团队的需求').fill('设计一个多 AI 协作工作室')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByText('准备团队讨论')).toBeVisible()

  await expect(page.locator('.message.assistant')).toHaveCount(5)
  await expect(page.locator('.message.discussion-final')).toContainText('最终交付方案')
  await expect(page.getByText('最终方案已生成')).toBeVisible()
  await expect(page.getByRole('button', { name: 'AI Token 钱包' })).toContainText('950')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('manages versioned Agent evaluations and completes an async regression run', async ({ page }) => {
  await page.goto('/evaluations')

  await expect(page.getByRole('heading', { name: 'Agent 评测实验室' })).toBeVisible()
  await expect(page.getByText('92.0%', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('+8.0 pt', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('可发布', { exact: true }).first()).toBeVisible()

  const firstRun = page.locator('.desktop-run-table:visible .run-link, .mobile-run-list:visible .run-card-main').first()
  await firstRun.click()
  await expect(page.getByText('评测运行 #81', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '维度对比' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '案例证据' })).toBeVisible()
  await page.locator('.result-collapse .el-collapse-item__header').first().click()
  const judgeEvidence = page.locator('.judge-reason').filter({ hasText: '回答覆盖了两项必需证据。' })
  await judgeEvidence.scrollIntoViewIfNeeded()
  await expect(judgeEvidence).toContainText('回答覆盖了两项必需证据。')
  await page.keyboard.press('Escape')

  await page.getByRole('tab', { name: '用例库' }).click()
  await page.getByRole('button', { name: '新建用例' }).click()
  const caseDialog = page.getByRole('dialog', { name: '新建评测用例' })
  await caseDialog.getByLabel('用例名称').fill('多 Agent 交接完整性')
  await caseDialog.getByLabel('测试输入').fill('输出产品、架构与测试之间的交接清单')
  await caseDialog.getByLabel('期望证据关键词').fill('负责人，验收证据，回滚')
  await caseDialog.getByLabel('禁用词').fill('跳过评审')
  await caseDialog.getByLabel('评分 Rubric').fill('必须明确角色、证据与失败恢复责任。')
  await caseDialog.getByRole('button', { name: '保存用例' }).click()
  const visibleCaseList = page.locator('.desktop-case-table:visible, .mobile-case-list:visible')
  await expect(visibleCaseList).toHaveCount(1)
  await expect(visibleCaseList.getByText('多 Agent 交接完整性', { exact: true })).toBeVisible()

  await page.getByRole('tab', { name: '运行历史' }).click()
  await page.getByRole('button', { name: '运行团队评测' }).click()
  await expect(page.getByText('团队评测 #82 已进入队列', { exact: true })).toBeVisible()
  await expect(page.getByText(/运行 #82 · 等待执行/)).toBeVisible()
  await expect(page.getByText('运行 #82', { exact: true })).toBeVisible({ timeout: 8_000 })
  await expect(page.getByText('95.0%', { exact: true }).first()).toBeVisible({ timeout: 8_000 })

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('bootstraps missing core Agent regression coverage', async ({ page }, testInfo) => {
  let coverageReady = false
  const readyCoverage = {
    required_roles: ['product_manager', 'architect', 'test_engineer', 'operations_analyst', 'project_manager'],
    covered_roles: ['product_manager', 'architect', 'test_engineer', 'operations_analyst', 'project_manager'],
    missing_roles: [],
    case_counts: { product_manager: 1, architect: 1, test_engineer: 1, operations_analyst: 1, project_manager: 1 },
    total_enabled_cases: 5,
    coverage_percent: 1,
    gate_ready: true
  }
  await page.route('**/api/v1/evaluations/coverage', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(coverageReady ? readyCoverage : {
        required_roles: ['product_manager', 'architect', 'test_engineer', 'operations_analyst', 'project_manager'],
        covered_roles: ['product_manager', 'architect'],
        missing_roles: ['test_engineer', 'operations_analyst', 'project_manager'],
        case_counts: { product_manager: 1, architect: 1, test_engineer: 0, operations_analyst: 0, project_manager: 0 },
        total_enabled_cases: 2,
        coverage_percent: 0.4,
        gate_ready: false
      })
    })
  })
  await page.route('**/api/v1/evaluations/cases/bootstrap', async (route) => {
    coverageReady = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        created_roles: ['test_engineer', 'operations_analyst', 'project_manager'],
        created_case_ids: [31, 32, 33],
        coverage: readyCoverage
      })
    })
  })
  await page.goto('/evaluations')

  const warning = page.getByRole('alert', { name: '多 Agent 评测覆盖不完整' })
  await expect(warning).toContainText('测试工程师')
  await expect(warning).toContainText('运营分析师')
  await expect(warning).toContainText('项目经理')
  await expect(page.getByRole('button', { name: '运行团队评测' })).toBeDisabled()
  const bootstrapButton = warning.getByRole('button', { name: '生成缺失基础用例' })
  if (testInfo.project.name === 'mobile-chromium') await expect(bootstrapButton).toHaveCSS('min-height', '44px')
  await bootstrapButton.click()
  const dialog = page.getByRole('dialog', { name: '生成基础评测套件' })
  await expect(dialog).toContainText('不会覆盖已有用例')
  const request = page.waitForRequest((value) => (
    value.method() === 'POST' && new URL(value.url()).pathname.endsWith('/evaluations/cases/bootstrap')
  ))
  await dialog.getByRole('button', { name: '确认生成' }).click()
  await request
  await expect(page.getByText('已生成 3 个基础评测用例', { exact: true })).toBeVisible()
  await expect(warning).toBeHidden()
  await expect(page.getByText('5/5', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '运行团队评测' })).toBeEnabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('triages negative production feedback into the evaluation dataset', async ({ page }) => {
  await page.goto('/evaluations')
  await page.getByRole('tab', { name: '反馈队列' }).click()

  const visibleFeedbackList = page.locator('.desktop-feedback-table:visible, .mobile-feedback-list:visible')
  await expect(visibleFeedbackList).toContainText('缺少租户边界和引用证据')
  await expect(visibleFeedbackList).toContainText('没有验收标准')

  const architectFeedback = visibleFeedbackList.locator('[data-feedback-id="41"]')
  await architectFeedback.getByRole('button', { name: '转为用例' }).click()
  const promoteDialog = page.getByRole('dialog', { name: '转为评测用例' })
  await expect(promoteDialog.getByText('设计租户隔离并给出证据引用', { exact: true })).toBeVisible()
  await expect(promoteDialog.getByText('使用共享数据库即可。', { exact: true })).toBeVisible()
  await expect(promoteDialog.getByText('缺少租户边界和引用证据', { exact: true })).toBeVisible()
  await promoteDialog.getByLabel('用例名称').fill('租户隔离与证据引用回归')
  await promoteDialog.getByLabel('期望证据关键词').fill('租户隔离，引用证据')
  await promoteDialog.getByLabel('禁用词').fill('共享数据库即可')
  await promoteDialog.getByLabel('评分 Rubric').fill('必须说明租户边界，并引用可核验的知识证据。')

  const promoted = page.waitForRequest((request) => (
    request.method() === 'POST'
    && new URL(request.url()).pathname.endsWith('/evaluations/feedback/41/promote')
  ))
  await promoteDialog.getByRole('button', { name: '创建评测用例' }).click()
  const promotePayload = (await promoted).postDataJSON() as {
    request_id: string
    name: string
    expected_keywords: string[]
    forbidden_keywords: string[]
    rubric: string
  }
  expect(promotePayload.request_id.length).toBeGreaterThanOrEqual(8)
  expect(promotePayload.expected_keywords).toEqual(['租户隔离', '引用证据'])
  expect(promotePayload.forbidden_keywords).toEqual(['共享数据库即可'])
  await expect(page.getByText('反馈已转为评测用例', { exact: true })).toBeVisible()

  const productFeedback = visibleFeedbackList.locator('[data-feedback-id="42"]')
  await productFeedback.getByRole('button', { name: '忽略' }).click()
  const dismissDialog = page.getByRole('dialog', { name: '忽略反馈' })
  await expect(dismissDialog).toContainText('复核结论会写入审计记录')
  await dismissDialog.getByRole('button', { name: '确认忽略' }).click()
  await expect(page.getByText('反馈已忽略', { exact: true })).toBeVisible()
  await expect(page.getByText('没有符合条件的反馈', { exact: true })).toBeVisible()

  await page.getByRole('tab', { name: '用例库' }).click()
  await expect(page.locator('.desktop-case-table:visible, .mobile-case-list:visible').getByText('租户隔离与证据引用回归', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('publishes and rolls back a gated Challenger with visible evidence', async ({ page }) => {
  await page.goto('/evaluations')

  const candidateRun = page.locator('.desktop-run-table:visible .run-link, .mobile-run-list:visible .run-card-main').first()
  await candidateRun.click()
  await expect(page.getByText('AI架构师 v1 → v2', { exact: true })).toBeVisible()
  await expect(page.getByText('评测通过，可安全发布', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '发布候选版本' }).click()
  const publishDialog = page.getByRole('dialog', { name: '发布候选版本' })
  await expect(publishDialog).toContainText('生产版本 v1 将升级到 v2')
  await publishDialog.getByRole('button', { name: '确认发布' }).click()
  await expect(page.getByText('候选版本 v2 已发布', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '回滚此发布' }).click()
  const rollbackDialog = page.getByRole('dialog', { name: '回滚评测发布' })
  await rollbackDialog.getByRole('button', { name: '确认' }).click()
  await expect(page.locator('[aria-label="候选版本发布证据"]').getByText('发布已回滚至恢复版本 v3', { exact: true })).toBeVisible()

  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('prefills an Agent draft and submits it as a Challenger evaluation', async ({ page }) => {
  await page.goto('/evaluations?agent=2&version=202')

  await expect(page.getByLabel('选择评测类型')).toContainText('候选版本')
  await expect(page.locator('.launch-field').filter({ hasText: '候选 Agent' })).toContainText('AI架构师')
  await expect(page.locator('.launch-field').filter({ hasText: '草稿版本' })).toContainText('v2 · 质量候选版本')
  await expect(page.locator('.launch-field').filter({ hasText: '生产基线' })).toContainText('#80')

  const submitted = page.waitForRequest((request) => (
    request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/evaluations/runs')
  ))
  await page.getByRole('button', { name: '运行候选评测' }).click()
  const payload = (await submitted).postDataJSON() as {
    baseline_run_id: number
    candidate_version_id: number
  }
  expect(payload.baseline_run_id).toBe(80)
  expect(payload.candidate_version_id).toBe(202)
})

test('explains a missing production baseline and switches to a team run', async ({ page }) => {
  await page.route('**/api/v1/agents', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(discussionAgents.map((agent) => (
        agent.id === 2 ? { ...agent, current_version: 9 } : agent
      )))
    })
  })
  await page.goto('/evaluations?agent=2&version=202')

  if (page.viewportSize()?.width === 1440) await page.setViewportSize({ width: 1280, height: 800 })

  const warning = page.getByRole('alert', { name: '缺少当前生产版本基线' })
  await expect(warning).toContainText('AI架构师 v9')
  await expect(warning).toContainText('不能与旧版本基线比较')
  await expect(page.getByRole('button', { name: '运行候选评测' })).toBeDisabled()

  await warning.getByRole('button', { name: '先运行团队基线' }).click()
  await expect(page.getByLabel('选择评测类型')).toContainText('团队基线')
  await expect(page.getByRole('button', { name: '运行团队评测' })).toBeEnabled()
  await expect(warning).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
  expect(await page.locator('main').evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(0)
})

test('turns failed evaluation evidence into a reviewed Prompt draft and Challenger', async ({ page }) => {
  await page.goto('/evaluations')

  const failedRun = page.locator('.desktop-run-table:visible, .mobile-run-list:visible').getByText('#79', { exact: true })
  await failedRun.click()
  await expect(page.getByText('评测运行 #79', { exact: true })).toBeVisible()
  await page.locator('.result-collapse .el-collapse-item__header').first().click()

  const optimizationRequest = page.waitForRequest((request) => (
    request.method() === 'POST'
    && new URL(request.url()).pathname.endsWith('/evaluations/optimization-jobs')
  ))
  await page.getByRole('button', { name: '生成调优草稿' }).click()
  const confirm = page.getByRole('dialog', { name: '创建 Prompt 调优任务' })
  await expect(confirm).toContainText('Optimizer Agent')
  await expect(confirm).toContainText('Reviewer Agent')
  await confirm.getByRole('button', { name: '创建调优任务' }).click()
  const payload = (await optimizationRequest).postDataJSON() as {
    evaluation_run_id: number
    result_ids: number[]
    agent_id: number
  }
  expect(payload).toMatchObject({ evaluation_run_id: 79, result_ids: [792], agent_id: 2 })

  await expect(page.getByRole('tab', { name: 'Prompt 调优' })).toHaveAttribute('aria-selected', 'true')
  const visibleJobs = page.locator('.desktop-optimization-table:visible, .mobile-optimization-list:visible')
  await expect(visibleJobs.getByText('任务 #901', { exact: true })).toBeVisible()
  await expect(visibleJobs.getByText('已生成草稿', { exact: true })).toBeVisible({ timeout: 8_000 })
  await visibleJobs.getByRole('button', { name: '查看调优任务 #901' }).click()
  await expect(page.getByText('调优任务 #901', { exact: true })).toBeVisible()
  await expect(page.getByText('Optimizer Agent', { exact: true })).toBeVisible()
  await expect(page.getByText('Reviewer Agent', { exact: true })).toBeVisible()
  await expect(page.getByText('第 1 轮', { exact: true })).toBeVisible()
  await expect(page.getByText('进入返修', { exact: true })).toBeVisible()
  await expect(page.getByText('第 2 轮', { exact: true })).toBeVisible()
  await expect(page.getByText('双门禁通过', { exact: true })).toBeVisible()
  await expect(page.getByText('角色、工具权限和治理边界保持不变。', { exact: true })).toBeVisible()
  await expect(page.getByText('你是 AI 架构师。明确租户边界，引用审计与回滚证据，并将敏感变更提交人工审批。', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '进入 Challenger 评测' }).click()
  await expect(page.getByRole('tab', { name: '运行历史' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.launch-field').filter({ hasText: '草稿版本' })).toContainText('v3 · AI optimization from evaluation run #79')

  const challengerRequest = page.waitForRequest((request) => (
    request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/evaluations/runs')
  ))
  await page.getByRole('button', { name: '运行候选评测' }).click()
  const challengerPayload = (await challengerRequest).postDataJSON() as { candidate_version_id: number }
  expect(challengerPayload.candidate_version_id).toBe(303)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('routes Agent drafts through evaluation instead of direct publish', async ({ page }) => {
  await page.goto('/agents')

  const architectCard = page.locator('.employee-card').filter({ hasText: 'AI架构师' })
  await expect(architectCard).toHaveCount(1)
  await architectCard.getByRole('button', { name: '配置 AI 员工' }).click()
  await page.getByRole('tab', { name: '版本记录' }).click()
  await page.getByRole('button', { name: '评测发布' }).click()

  await expect(page).toHaveURL(/\/evaluations\?agent=2&version=202$/)
  await expect(page.getByLabel('选择评测类型')).toContainText('候选版本')
})

test('keeps the evaluation lab usable at 375px and mobile landscape', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'Mobile viewport regression')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/evaluations')

  await expect(page.getByRole('heading', { name: 'Agent 评测实验室' })).toBeVisible()
  await expect(page.getByRole('button', { name: '运行团队评测' })).toHaveCSS('min-height', '44px')
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)

  await page.getByRole('tab', { name: '反馈队列' }).click()
  const feedbackActions = page.locator('.mobile-feedback-list:visible [data-feedback-id="41"] .feedback-card-actions .el-button')
  await expect(feedbackActions).toHaveCount(2)
  await expect(feedbackActions.first()).toHaveCSS('min-height', '44px')
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.mobile-feedback-list:visible')).toHaveCount(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)

  await page.getByRole('tab', { name: '运行历史' }).click()
  await page.setViewportSize({ width: 844, height: 390 })
  await expect(page.getByRole('heading', { name: 'Agent 评测实验室' })).toBeVisible()
  await expect(page.locator('.desktop-run-table:visible, .mobile-run-list:visible')).toHaveCount(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('traces multi-agent runtime metrics and opens a deep-linked run detail', async ({ page }, testInfo) => {
  await page.goto('/traces')

  await expect(page.getByRole('heading', { name: 'Agent 运行追踪' })).toBeVisible()
  await expect(page.getByRole('region', { name: '运行关键指标' }).getByText('80.0%', { exact: true })).toBeVisible()
  await expect(page.getByText('分析样本已截断', { exact: true })).toBeVisible()
  await expect(page.locator('strong:visible').filter({ hasText: /^AI架构师$/ }).first()).toBeVisible()
  const trend = page.getByRole('img', { name: /共 12 次运行.*消耗 24800 Token/ })
  await expect(trend.locator('canvas')).toBeVisible()
  const canvasHasPixels = await trend.locator('canvas').evaluate((node) => {
    const canvas = node as HTMLCanvasElement
    const context = canvas.getContext('2d')
    if (!context) return false
    return context.getImageData(0, 0, canvas.width, canvas.height).data.some((value, index) => index % 4 === 3 && value > 0)
  })
  expect(canvasHasPixels).toBe(true)

  const runTrigger = page.locator('.desktop-table:visible .trace-link, .mobile-card-list:visible .run-card-button').first()
  await runTrigger.click()
  await expect(page).toHaveURL(/\/traces\?run=88$/)
  await expect(page.getByRole('heading', { name: '#88 · 灰度发布工作台' })).toBeVisible()
  await expect(page.getByText('检查点重试 #1', { exact: true })).toBeVisible()
  await expect(page.getByText('人工干预 2', { exact: true })).toBeVisible()
  await expect(page.getByText('来源运行 #87 · 架构设计检查点', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '执行时间线' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '模型调用' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '事件日志' })).toBeVisible()
  await expect(page.getByText('Started specialist branch architect', { exact: true })).toBeVisible()
  const visibleModelCalls = page.locator('.trace-detail .desktop-table:visible, .trace-detail .mobile-card-list:visible').filter({ hasText: 'gpt-5.2' })
  await expect(visibleModelCalls).toBeVisible()
  const drawerOverflow = await page.evaluate(() => {
    const body = document.querySelector('.trace-detail-drawer .el-drawer__body')
    return body ? body.scrollWidth - body.clientWidth : 0
  })
  expect(drawerOverflow).toBeLessThanOrEqual(0)
  if (testInfo.project.name === 'mobile-chromium') {
    const closeTarget = await page.getByRole('button', { name: '关闭运行追踪' }).evaluate((button) => {
      const rect = button.getBoundingClientRect()
      return { width: rect.width, height: rect.height }
    })
    expect(closeTarget.width).toBeGreaterThanOrEqual(44)
    expect(closeTarget.height).toBeGreaterThanOrEqual(44)
    await expect(page.getByRole('button', { name: '查看来源运行 #87' })).toHaveCSS('min-height', '44px')
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)

  await page.getByRole('button', { name: '查看来源运行 #87' }).click()
  await expect(page).toHaveURL(/\/traces\?run=87$/)
  await expect(page.getByRole('heading', { name: '#87 · 灰度发布工作台' })).toBeVisible()

  await page.getByRole('button', { name: '关闭运行追踪' }).click()
  await expect(page).toHaveURL(/\/traces$/)
})

test('monitors SLO error budget and drills into anomalous runs', async ({ page }, testInfo) => {
  await page.goto('/traces')

  await expect(page.getByRole('heading', { name: 'SLO 与智能告警' })).toBeVisible()
  await expect(page.getByText('SLO 违约', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('错误预算剩余', { exact: true })).toBeVisible()
  await expect(page.getByText('0.0%', { exact: true })).toBeVisible()
  await expect(page.getByText('运行成功率', { exact: true })).toBeVisible()
  await expect(page.getByText('P95 端到端耗时', { exact: true }).last()).toBeVisible()
  const anomalySurface = page.locator('.health-desktop-table:visible, .health-mobile-list:visible')
  await expect(anomalySurface).toContainText('#88')
  await expect(anomalySurface).toContainText('成本偏离历史基线')
  await expect(anomalySurface).toContainText('运行失败')
  const settingsButton = page.getByRole('button', { name: 'SLO 设置' })
  await expect(settingsButton).toBeVisible()
  if (testInfo.project.name === 'mobile-chromium') {
    await expect(settingsButton).toHaveCSS('min-height', '44px')
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)

  const anomalyTrigger = page.locator('.health-desktop-table:visible .health-run-link, .health-mobile-list:visible .health-mobile-trigger').first()
  await anomalyTrigger.click()
  await expect(page).toHaveURL(/\/traces\?run=88$/)
  await expect(page.getByRole('heading', { name: '#88 · 灰度发布工作台' })).toBeVisible()
  await page.getByRole('button', { name: '关闭运行追踪' }).click()
  await expect(page).toHaveURL(/\/traces$/)
})

test('acknowledges, batches and resolves durable trace alerts', async ({ page }, testInfo) => {
  await page.goto('/traces')

  await expect(page.getByRole('heading', { name: '告警处理' })).toBeVisible()
  const alertSurface = page.locator('.alert-desktop-table:visible, .alert-mobile-list:visible')
  await expect(alertSurface).toContainText('#88')
  await expect(alertSurface).toContainText('#86')
  await expect(alertSurface).toContainText('#85')

  const alert88 = page.locator('.alert-desktop-table:visible tr, .alert-mobile-list:visible .alert-mobile-card').filter({ hasText: '#88' })
  await alert88.getByRole('button', { name: '确认', exact: true }).click()
  await expect(alert88.getByText('处理中', { exact: true })).toBeVisible()

  const alert86 = page.locator('.alert-desktop-table:visible tr, .alert-mobile-list:visible .alert-mobile-card').filter({ hasText: '#86' })
  if (testInfo.project.name === 'mobile-chromium') {
    const checkboxTarget = await alert86.locator('.el-checkbox').evaluate((checkbox) => {
      const rect = checkbox.getBoundingClientRect()
      return { width: rect.width, height: rect.height }
    })
    expect(checkboxTarget.width).toBeGreaterThanOrEqual(44)
    expect(checkboxTarget.height).toBeGreaterThanOrEqual(44)
  }
  await alert86.locator('.el-checkbox').click()
  await page.getByRole('button', { name: '批量确认' }).click()
  await expect(alert86.getByText('处理中', { exact: true })).toBeVisible()

  await alert88.getByRole('button', { name: '解决', exact: true }).click()
  const resolutionDialog = page.getByRole('dialog', { name: '解决告警' })
  await expect(resolutionDialog.getByRole('button', { name: '确认解决' })).toBeDisabled()
  await resolutionDialog.getByLabel('处理说明').fill('已切换低成本模型并完成回归验证')
  await resolutionDialog.getByRole('button', { name: '确认解决' }).click()
  await expect(alert88).toHaveCount(0)

  await page.getByText('全部', { exact: true }).click()
  const resolvedAlert = page.locator('.alert-desktop-table:visible tr, .alert-mobile-list:visible .alert-mobile-card').filter({ hasText: '#88' })
  await expect(resolvedAlert.getByText('已解决', { exact: true })).toBeVisible()
  if (testInfo.project.name === 'mobile-chromium') {
    await expect(resolvedAlert).toContainText('已切换低成本模型并完成回归验证')
    const actionHeights = await resolvedAlert.locator('.alert-mobile-actions .el-button').evaluateAll((buttons) => (
      buttons.map((button) => button.getBoundingClientRect().height)
    ))
    expect(actionHeights.every((height) => height >= 44)).toBeTruthy()
  }

  await page.getByRole('button', { name: '刷新运行追踪' }).click()
  await expect(resolvedAlert).toHaveCount(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('compares multi-agent runs and restores the comparison deep link', async ({ page }, testInfo) => {
  await page.goto('/traces')

  await page.getByRole('button', { name: '对比运行' }).click()
  const dialog = page.locator('.trace-comparison-dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('.comparison-picker')).toContainText('#87')
  await expect(dialog.locator('.comparison-picker')).toContainText('#88')

  await dialog.getByRole('button', { name: '开始对比' }).click()
  await expect.poll(() => {
    const url = new URL(page.url())
    return `${url.searchParams.get('baseline')}:${url.searchParams.get('candidate')}`
  }).toBe('87:88')
  await expect(dialog.getByText('改善与退化并存', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('heading', { name: '关键指标' })).toBeVisible()
  await expect(dialog.getByRole('heading', { name: 'Agent 变化' })).toBeVisible()
  await expect(dialog.getByRole('heading', { name: '节点与分支变化' })).toBeVisible()
  const visibleAgentComparison = dialog.locator('.desktop-comparison-table:visible, .mobile-comparison-list:visible').first()
  await expect(visibleAgentComparison).toContainText('gpt-4o-mini')
  await expect(visibleAgentComparison).toContainText('gpt-5.2')

  const dialogOverflow = await dialog.locator('.el-dialog__body').evaluate((body) => body.scrollWidth - body.clientWidth)
  expect(dialogOverflow).toBeLessThanOrEqual(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
  if (testInfo.project.name === 'mobile-chromium') {
    const closeTarget = await dialog.locator('.el-dialog__headerbtn').evaluate((button) => {
      const rect = button.getBoundingClientRect()
      return { width: rect.width, height: rect.height }
    })
    expect(closeTarget.width).toBeGreaterThanOrEqual(44)
    expect(closeTarget.height).toBeGreaterThanOrEqual(44)
  }

  await page.reload()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('改善与退化并存', { exact: true })).toBeVisible()
  await expect.poll(() => {
    const url = new URL(page.url())
    return `${url.searchParams.get('baseline')}:${url.searchParams.get('candidate')}`
  }).toBe('87:88')
})

test('keeps runtime tracing usable at 375px, landscape and reduced motion', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium', 'Mobile viewport regression')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/traces')

  await expect(page.getByRole('heading', { name: 'Agent 运行追踪' })).toBeVisible()
  await expect(page.getByRole('button', { name: '刷新运行追踪' })).toHaveCSS('width', '44px')
  await expect(page.getByRole('heading', { name: 'SLO 与智能告警' })).toBeVisible()
  await expect(page.locator('.health-mobile-list:visible .health-mobile-card')).toHaveCount(2)
  await expect(page.locator('.mobile-card-list:visible .run-card')).toHaveCount(2)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)

  await page.setViewportSize({ width: 844, height: 390 })
  await expect(page.getByRole('heading', { name: 'Agent 运行追踪' })).toBeVisible()
  await expect(page.getByRole('img', { name: /运行与消耗趋势图/ }).locator('canvas')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('shows Saga compensation failure and completes manual recovery', async ({ page }) => {
  await page.goto('/projects/1')

  const workflowHeading = page.getByRole('heading', { name: 'Agent 工作流' })
  await expect(workflowHeading).toBeVisible({ timeout: 15_000 })
  await workflowHeading.scrollIntoViewIfNeeded()
  await expect(page.getByText('回滚失败，等待人工处理')).toBeVisible()
  await expect(page.getByText('创建项目任务')).toBeVisible()
  await expect(page.getByText('Task changed after Saga creation', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '重试回滚' }).click()

  await expect(page.getByText('已取消', { exact: true })).toBeVisible()
  await expect(page.getByText('已回滚', { exact: true })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('creates an immutable checkpoint retry and links back to the failed run', async ({ page }, testInfo) => {
  const sourceWorkflow = {
    workflow_id: 120,
    project_id: 2,
    parent_workflow_id: null,
    retry_from_node: '',
    retry_sequence: 0,
    status: 'FAILED',
    current_node: 'architect',
    state: { messages: [], documents: [{ type: 'PRD', content: '# 已冻结的产品需求' }] },
    attempt_count: 2,
    max_attempts: 2,
    error: '架构模型服务暂时不可用',
    created_at: '2026-07-18T08:00:00Z',
    updated_at: '2026-07-18T08:05:00Z',
    started_at: '2026-07-18T08:00:01Z',
    finished_at: '2026-07-18T08:05:00Z'
  }
  const childWorkflow = {
    ...sourceWorkflow,
    workflow_id: 121,
    parent_workflow_id: 120,
    retry_from_node: 'architect',
    retry_sequence: 1,
    status: 'QUEUED',
    attempt_count: 0,
    error: '',
    created_at: '2026-07-18T08:10:00Z',
    updated_at: '2026-07-18T08:10:00Z',
    started_at: null,
    finished_at: null
  }
  let retryRequestId = ''

  await page.route(/\/api\/v1\/workflow\?project_id=2$/, (route) => route.fulfill({ json: [sourceWorkflow] }))
  await page.route(/\/api\/v1\/workflow\/120\/saga-steps$/, (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/v1\/workflow\/120\/events\/history(?:\?.*)?$/, (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/v1\/workflow\/120\/retry$/, async (route) => {
    retryRequestId = (route.request().postDataJSON() as { request_id: string }).request_id
    await route.fulfill({ json: childWorkflow })
  })
  await page.route(/\/api\/v1\/workflow\/121\/saga-steps$/, (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/v1\/workflow\/121\/events\/history(?:\?.*)?$/, (route) => route.fulfill({
    json: [
      { id: 10, workflow_id: 121, node: 'architect', event_type: 'RETRY_QUEUED', message: 'Workflow queued from an immutable failed run', payload: { parent_workflow_id: 120 }, created_at: '2026-07-18T08:10:00Z' },
      { id: 11, workflow_id: 121, node: 'architect', event_type: 'QUEUED', message: 'Checkpoint retry queued', payload: {}, created_at: '2026-07-18T08:10:00Z' }
    ]
  }))
  await page.route(/\/api\/v1\/workflow\/121\/events$/, (route) => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'retry: 10000\n\n'
  }))

  await page.goto('/projects/2')
  await expect(page.getByText('架构模型服务暂时不可用', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '重试失败节点' }).click()

  const dialog = page.getByRole('dialog', { name: '创建检查点重试' })
  await expect(dialog).toContainText('失败运行 #120 将保持只读')
  await expect(dialog).toContainText('“架构设计”检查点')
  await dialog.getByRole('button', { name: '创建重试运行' }).click()

  await expect(page.getByText('检查点重试 #1', { exact: true })).toBeVisible()
  await expect(page.getByText('从运行 #120 的“架构设计”检查点继续，源运行保持只读。', { exact: true })).toBeVisible()
  await expect(page.locator('.workflow-events').getByText('检查点重试入队', { exact: true })).toBeVisible()
  expect(retryRequestId.length).toBeGreaterThanOrEqual(8)
  const sourceLink = page.getByRole('button', { name: '查看源运行' })
  if (testInfo.project.name === 'mobile-chromium') await expect(sourceLink).toHaveCSS('min-height', '44px')
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)

  await sourceLink.click()
  await expect(page).toHaveURL(/\/traces\?run=120$/)
})

test('pauses a running workflow at a safe boundary and resumes with operator context', async ({ page }, testInfo) => {
  let pauseRequested = false
  let resumed = false
  let pauseReason = ''
  let resumeInstruction = ''
  let workflow = {
    workflow_id: 130,
    project_id: 2,
    parent_workflow_id: null,
    retry_from_node: '',
    retry_sequence: 0,
    pause_requested_at: null as string | null,
    pause_requested_by_user_id: null as number | null,
    pause_reason: '',
    intervention_count: 0,
    status: 'RUNNING',
    current_node: 'architect',
    state: { messages: [], documents: [{ type: 'PRD', content: '# 产品需求' }], interventions: [] as Array<Record<string, string>> },
    attempt_count: 1,
    max_attempts: 2,
    error: '',
    created_at: '2026-07-18T09:00:00Z',
    updated_at: '2026-07-18T09:02:00Z',
    started_at: '2026-07-18T09:00:01Z',
    finished_at: null as string | null
  }
  let workflowEvents: Array<Record<string, unknown>> = []

  await page.route(/\/api\/v1\/workflow\?project_id=2$/, (route) => route.fulfill({ json: [workflow] }))
  await page.route(/\/api\/v1\/workflow\/130$/, (route) => route.fulfill({ json: workflow }))
  await page.route(/\/api\/v1\/workflow\/130\/saga-steps$/, (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/v1\/workflow\/130\/events\/history(?:\?.*)?$/, (route) => route.fulfill({ json: workflowEvents }))
  await page.route(/\/api\/v1\/workflow\/130\/pause$/, async (route) => {
    const input = route.request().postDataJSON() as { request_id: string; reason: string }
    pauseReason = input.reason
    pauseRequested = true
    workflow = {
      ...workflow,
      pause_requested_at: '2026-07-18T09:02:30Z',
      pause_requested_by_user_id: 1,
      pause_reason: input.reason,
      updated_at: '2026-07-18T09:02:30Z'
    }
    workflowEvents = [{
      id: 20, workflow_id: 130, node: 'architect', event_type: 'PAUSE_REQUESTED',
      message: 'Operator requested a safe-boundary pause', payload: { reason_chars: input.reason.length },
      created_at: '2026-07-18T09:02:30Z'
    }]
    await route.fulfill({ json: workflow })
  })
  await page.route(/\/api\/v1\/workflow\/130\/events$/, async (route) => {
    if (!pauseRequested || resumed) {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 10000\n\n' })
    }
    await new Promise((resolve) => setTimeout(resolve, 600))
    if (resumed) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 10000\n\n' })
    workflow = { ...workflow, status: 'PAUSED', intervention_count: 1, updated_at: '2026-07-18T09:03:00Z' }
    const pausedEvent = {
      id: 21, workflow_id: 130, node: 'architect', event_type: 'PAUSED',
      message: 'Workflow paused at a committed node boundary', payload: { approval_gate: 'operator', intervention_count: 1 },
      created_at: '2026-07-18T09:03:00Z'
    }
    workflowEvents = [...workflowEvents, pausedEvent]
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `retry: 10000\n\nid: 21\nevent: workflow\ndata: ${JSON.stringify(pausedEvent)}\n\n`
    })
  })
  await page.route(/\/api\/v1\/workflow\/continue$/, async (route) => {
    const input = route.request().postDataJSON() as { workflow_id: number; human_feedback: string }
    resumeInstruction = input.human_feedback
    resumed = true
    workflow = {
      ...workflow,
      status: 'QUEUED',
      pause_requested_at: null,
      pause_requested_by_user_id: null,
      pause_reason: '',
      state: {
        ...workflow.state,
        interventions: [{ reason: pauseReason, instruction: input.human_feedback, resume_from_node: 'architect' }]
      },
      updated_at: '2026-07-18T09:04:00Z'
    }
    workflowEvents = [
      ...workflowEvents,
      { id: 22, workflow_id: 130, node: 'architect', event_type: 'INTERVENTION_APPLIED', message: 'Operator instruction applied', payload: { instruction_chars: input.human_feedback.length }, created_at: '2026-07-18T09:04:00Z' },
      { id: 23, workflow_id: 130, node: 'architect', event_type: 'QUEUED', message: 'Workflow continued after human review', payload: { approval_gate: 'operator' }, created_at: '2026-07-18T09:04:00Z' }
    ]
    await route.fulfill({ json: workflow })
  })

  await page.goto('/projects/2')
  await page.getByRole('button', { name: '安全暂停' }).click()
  const dialog = page.getByRole('dialog', { name: '安全暂停工作流' })
  await dialog.getByLabel('暂停原因').fill('补充数据驻留边界后再继续')
  const pauseButton = dialog.getByRole('button', { name: '请求安全暂停' })
  if (testInfo.project.name === 'mobile-chromium') await expect(pauseButton).toHaveCSS('min-height', '44px')
  await pauseButton.click()

  await expect(page.getByText('安全暂停已请求', { exact: true })).toBeVisible()
  await expect(page.getByText('等待安全暂停', { exact: true })).toBeVisible()
  await expect(page.getByText('人工干预中', { exact: true })).toBeVisible({ timeout: 8_000 })
  await expect(page.getByText('运行已在“架构设计”安全暂停', { exact: true })).toBeVisible()
  await expect(page.getByText('暂停原因：补充数据驻留边界后再继续', { exact: true })).toBeVisible()
  await page.getByLabel('工作流人工反馈').fill('所有数据限定批准区域，并让测试 Agent 验证。')
  await page.getByRole('button', { name: '应用指令并继续' }).click()

  await expect(page.getByText('等待执行', { exact: true })).toBeVisible()
  await expect(page.getByText('人工干预 1 次', { exact: true })).toBeVisible()
  await expect(page.locator('.workflow-events').getByText('已应用恢复指令', { exact: true })).toBeVisible()
  expect(pauseReason).toBe('补充数据驻留边界后再继续')
  expect(resumeInstruction).toBe('所有数据限定批准区域，并让测试 Agent 验证。')
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('restores workflow history and reconnects live progress without duplicate events', async ({ page }) => {
  const runningWorkflow = {
    workflow_id: 99,
    project_id: 2,
    status: 'RUNNING',
    current_node: 'product',
    state: { messages: [], documents: [] },
    attempt_count: 1,
    max_attempts: 3,
    error: '',
    created_at: '2026-07-18T08:00:00Z',
    updated_at: '2026-07-18T08:01:00Z',
    started_at: '2026-07-18T08:00:01Z',
    finished_at: null
  }
  const completedWorkflow = {
    ...runningWorkflow,
    status: 'COMPLETED',
    current_node: 'completed',
    state: { messages: [], documents: [], report: '# 已恢复的项目报告' },
    updated_at: '2026-07-18T08:02:00Z',
    finished_at: '2026-07-18T08:02:00Z'
  }
  const queuedEvent = {
    id: 1,
    workflow_id: 99,
    node: 'requirement',
    event_type: 'QUEUED',
    message: 'Workflow queued',
    payload: {},
    created_at: '2026-07-18T08:00:00Z'
  }
  const completedEvent = {
    id: 2,
    workflow_id: 99,
    node: 'completed',
    event_type: 'COMPLETED',
    message: 'Workflow completed',
    payload: {},
    created_at: '2026-07-18T08:02:00Z'
  }
  const cursors: string[] = []
  let streamAttempts = 0

  await page.route(/\/api\/v1\/workflow\?project_id=2$/, (route) => route.fulfill({ json: [runningWorkflow] }))
  await page.route(/\/api\/v1\/workflow\/99\/events\/history(?:\?.*)?$/, (route) => route.fulfill({ json: [queuedEvent] }))
  await page.route(/\/api\/v1\/workflow\/99\/events$/, async (route) => {
    streamAttempts += 1
    cursors.push(route.request().headers()['last-event-id'] || '')
    if (streamAttempts === 1) {
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'retry: 2000\n\n'
      })
    }
    await new Promise((resolve) => setTimeout(resolve, 300))
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `retry: 500\n\nid: 2\nevent: workflow\ndata: ${JSON.stringify(completedEvent)}\n\n`
    })
  })
  await page.route(/\/api\/v1\/workflow\/99$/, (route) => route.fulfill({ json: completedWorkflow }))

  await page.goto('/projects/2')

  await expect(page.getByRole('alert')).toContainText('实时进度暂时中断')
  await expect(page.getByText('已完成', { exact: true })).toBeVisible({ timeout: 8_000 })
  await expect(page.locator('.workflow-events').getByText('已入队', { exact: true })).toHaveCount(1)
  await expect(page.locator('.workflow-events').getByText('执行完成', { exact: true })).toHaveCount(1)
  expect(streamAttempts).toBe(2)
  expect(cursors).toEqual(['1', '1'])
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('lists index versions and rolls knowledge search back on desktop and mobile', async ({ page }) => {
  await page.goto('/knowledge')

  const documentSurface = page.locator('.knowledge-document-table:visible, .knowledge-document-list:visible')
  await expect(documentSurface).toHaveCount(1)
  await expect(documentSurface.getByText('RAG-production-runbook.md', { exact: true })).toBeVisible()
  await expect(documentSurface.getByText(/索引 v2/)).toBeVisible()
  await page.getByRole('button', { name: '版本', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'RAG-production-runbook.md · 索引版本' })).toBeVisible()
  const versionSurface = page.locator('.version-table-desktop:visible, .version-list-mobile:visible')
  await expect(versionSurface).toHaveCount(1)
  await expect(versionSurface.getByText('v1', { exact: true })).toBeVisible()

  const activate = page.locator('button:enabled:visible').filter({ hasText: '激活' })
  await expect(activate).toHaveCount(1)
  await activate.click()
  await expect(page.getByText('将活动索引切换到 v1，当前版本仍会保留。')).toBeVisible()
  await page.getByRole('button', { name: '确认激活', exact: true }).click()

  await expect(page.getByText('索引 v1 已激活')).toBeVisible()
  await expect(documentSurface.getByText(/索引 v1/)).toBeVisible()
  await expect(documentSurface.getByText(/native-markdown · 2 chunks/)).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('restores live specialist retry states and opens completed handoffs', async ({ page }, testInfo) => {
  const liveWorkflow = {
    workflow_id: 150,
    project_id: 2,
    parent_workflow_id: null,
    retry_from_node: '',
    retry_sequence: 0,
    pause_requested_at: null,
    pause_requested_by_user_id: null,
    pause_reason: '',
    intervention_count: 0,
    status: 'RUNNING',
    current_node: 'specialists',
    state: {
      plan_version: 2,
      execution_plan: {
        objective: '恢复可观察的专业 Agent 执行现场',
        rationale: '运营与测试并行，瞬时失败只重试测试 Agent。',
        assignments: [
          { role: 'operations_analyst', objective: '定义发布和回滚边界', deliverable: '发布运行手册', depends_on: [] },
          { role: 'test_engineer', objective: '验证边界与验收证据', deliverable: '测试与验收清单', depends_on: [] }
        ],
        success_criteria: ['成功分支不重复', '失败分支有界重试']
      },
      specialist_handoffs: [
        {
          role: 'operations_analyst',
          objective: '定义发布和回滚边界',
          deliverable: '发布运行手册',
          content: '已完成发布窗口、监控阈值、失败信号和回滚负责人定义。',
          revision_round: 0,
          plan_version: 2,
          upstream_fingerprints: {},
          input_fingerprint: 'a'.repeat(64),
          output_fingerprint: 'b'.repeat(64)
        }
      ],
      quality_gate: {},
      revision_round: 0,
      documents: [],
      messages: []
    },
    attempt_count: 1,
    max_attempts: 2,
    error: '',
    created_at: '2026-07-19T10:00:00Z',
    updated_at: '2026-07-19T10:00:08Z',
    started_at: '2026-07-19T10:00:01Z',
    finished_at: null
  }
  const events = [
    { id: 1, workflow_id: 150, node: 'specialists', event_type: 'WAVE_STARTED', message: 'wave started', payload: { wave: 1, roles: ['operations_analyst', 'test_engineer'] }, created_at: '2026-07-19T10:00:02Z' },
    { id: 2, workflow_id: 150, node: 'specialists', event_type: 'BRANCH_STARTED', message: 'operations started', payload: { role: 'operations_analyst', branch_attempt: 1 }, created_at: '2026-07-19T10:00:03Z' },
    { id: 3, workflow_id: 150, node: 'specialists', event_type: 'BRANCH_STARTED', message: 'test started', payload: { role: 'test_engineer', branch_attempt: 1 }, created_at: '2026-07-19T10:00:03Z' },
    { id: 4, workflow_id: 150, node: 'specialists', event_type: 'BRANCH_COMPLETED', message: 'operations completed', payload: { role: 'operations_analyst', branch_attempt: 1, lineage_sealed: true, upstream_count: 0, plan_version: 2 }, created_at: '2026-07-19T10:00:07Z' },
    { id: 5, workflow_id: 150, node: 'specialists', event_type: 'BRANCH_FAILED', message: 'test failed', payload: { role: 'test_engineer', branch_attempt: 1, retryable: true, will_retry: true }, created_at: '2026-07-19T10:00:07Z' },
    { id: 6, workflow_id: 150, node: 'specialists', event_type: 'BRANCH_RETRY_SCHEDULED', message: 'test retry scheduled', payload: { role: 'test_engineer', branch_attempt: 1, next_branch_attempt: 2, retry_delay_seconds: 1 }, created_at: '2026-07-19T10:00:08Z' }
  ]
  await page.route(/\/api\/v1\/workflow\?project_id=2$/, (route) => route.fulfill({ json: [liveWorkflow] }))
  await page.route(/\/api\/v1\/workflow\/150$/, (route) => route.fulfill({ json: liveWorkflow }))
  await page.route(/\/api\/v1\/workflow\/150\/saga-steps$/, (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/v1\/workflow\/150\/events\/history(?:\?.*)?$/, (route) => route.fulfill({ json: events }))
  await page.route(/\/api\/v1\/workflow\/150\/events$/, (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }))

  await page.goto('/projects/2')

  await expect(page.getByText('1/2 已交接 · 1 待重试', { exact: true })).toBeVisible()
  const operationsBranch = page.locator('.orchestration-branch-row').filter({ hasText: '运营分析师' })
  const testBranch = page.locator('.orchestration-branch-row').filter({ hasText: '测试工程师' })
  await expect(operationsBranch.getByRole('status')).toContainText('已交接')
  await expect(operationsBranch.getByRole('status')).toContainText('A1 · R0')
  await expect(testBranch.getByRole('status')).toContainText('等待重试')
  await expect(testBranch.getByRole('status')).toContainText('A1 · 1s')
  await operationsBranch.getByRole('button', { name: '查看运营分析师交接' }).click()
  const lineage = page.getByRole('region', { name: 'Handoff 证据链' })
  await expect(lineage.getByText('证据链已封存', { exact: true })).toBeVisible()
  await expect(lineage.getByText('计划 v2 · 修订 R0', { exact: true })).toBeVisible()
  await expect(lineage.getByText('独立根分支', { exact: true })).toBeVisible()
  await expect(lineage.getByText('aaaaaaaaaa → bbbbbbbbbb', { exact: true })).toBeVisible()
  await expect(page.getByText('已完成发布窗口、监控阈值、失败信号和回滚负责人定义。')).toBeVisible()
  if (testInfo.project.name === 'mobile-chromium') {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    for (const viewport of [{ width: 375, height: 812 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(viewport)
      await expect(lineage).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
    }
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('recovers a failed specialist branch from its committed checkpoint', async ({ page }, testInfo) => {
  let recoveryPayload: Record<string, unknown> = {}
  const recoveryWorkflow = {
    workflow_id: 160,
    project_id: 2,
    parent_workflow_id: null,
    retry_from_node: '',
    retry_sequence: 0,
    pause_requested_at: null,
    pause_requested_by_user_id: null,
    pause_reason: '',
    intervention_count: 0,
    status: 'PAUSED',
    current_node: 'specialist_review',
    state: {
      execution_plan: {
        objective: '在保留成功交接的前提下恢复失败专业分支',
        rationale: '运营与测试并行，确定性失败进入人工恢复门禁。',
        assignments: [
          { role: 'operations_analyst', objective: '定义发布和回滚边界', deliverable: '发布运行手册', depends_on: [] },
          { role: 'test_engineer', objective: '验证边界与验收证据', deliverable: '测试与验收清单', depends_on: [] }
        ],
        success_criteria: ['成功分支不重复', '失败分支接受人工修复指令']
      },
      specialist_handoffs: [
        {
          role: 'operations_analyst',
          objective: '定义发布和回滚边界',
          deliverable: '发布运行手册',
          content: '已完成发布窗口、监控阈值、失败信号和回滚负责人定义。',
          revision_round: 0
        }
      ],
      specialist_failures: [
        {
          role: 'test_engineer',
          wave: 1,
          branch_attempt: 1,
          retryable: false,
          category: 'NON_RETRYABLE',
          message: '测试环境配置缺少验收凭据'
        }
      ],
      specialist_recovery_count: 0,
      quality_gate: {},
      revision_round: 0,
      documents: [],
      messages: []
    },
    attempt_count: 1,
    max_attempts: 2,
    error: '',
    created_at: '2026-07-20T10:00:00Z',
    updated_at: '2026-07-20T10:00:08Z',
    started_at: '2026-07-20T10:00:01Z',
    finished_at: null
  }
  const events = [
    { id: 1, workflow_id: 160, node: 'specialists', event_type: 'BRANCH_STARTED', message: 'operations started', payload: { role: 'operations_analyst', branch_attempt: 1 }, created_at: '2026-07-20T10:00:03Z' },
    { id: 2, workflow_id: 160, node: 'specialists', event_type: 'BRANCH_STARTED', message: 'test started', payload: { role: 'test_engineer', branch_attempt: 1 }, created_at: '2026-07-20T10:00:03Z' },
    { id: 3, workflow_id: 160, node: 'specialists', event_type: 'BRANCH_COMPLETED', message: 'operations completed', payload: { role: 'operations_analyst', branch_attempt: 1 }, created_at: '2026-07-20T10:00:07Z' },
    { id: 4, workflow_id: 160, node: 'specialists', event_type: 'BRANCH_FAILED', message: 'test failed', payload: { role: 'test_engineer', branch_attempt: 1, retryable: false, will_retry: false }, created_at: '2026-07-20T10:00:07Z' },
    { id: 5, workflow_id: 160, node: 'specialists', event_type: 'SPECIALIST_REVIEW_REQUIRED', message: 'review required', payload: { roles: ['test_engineer'], failed_count: 1 }, created_at: '2026-07-20T10:00:08Z' },
    { id: 6, workflow_id: 160, node: 'specialist_review', event_type: 'PAUSED', message: 'paused', payload: { approval_gate: 'specialist_review', roles: ['test_engineer'], failed_count: 1 }, created_at: '2026-07-20T10:00:08Z' }
  ]
  await page.route(/\/api\/v1\/workflow\?project_id=2$/, (route) => route.fulfill({ json: [recoveryWorkflow] }))
  await page.route(/\/api\/v1\/workflow\/160$/, (route) => route.fulfill({ json: recoveryWorkflow }))
  await page.route(/\/api\/v1\/workflow\/160\/saga-steps$/, (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/v1\/workflow\/160\/events\/history(?:\?.*)?$/, (route) => route.fulfill({ json: events }))
  await page.route(/\/api\/v1\/workflow\/160\/events$/, (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }))
  await page.route(/\/api\/v1\/workflow\/continue$/, async (route) => {
    recoveryPayload = await route.request().postDataJSON()
    return route.fulfill({
      json: {
        ...recoveryWorkflow,
        status: 'QUEUED',
        current_node: 'specialists',
        state: {
          ...recoveryWorkflow.state,
          specialist_failures: [],
          specialist_recovery_count: 1,
          revision_feedback: recoveryPayload.human_feedback
        }
      }
    })
  })

  await page.goto('/projects/2')

  await expect(page.getByText('专业分支等待人工恢复', { exact: true })).toBeVisible()
  const recovery = page.getByRole('region', { name: '失败分支恢复详情' })
  await expect(recovery.getByText('测试工程师', { exact: true })).toBeVisible()
  await expect(recovery.getByText('不可自动重试', { exact: true })).toBeVisible()
  await expect(recovery.getByText('测试环境配置缺少验收凭据', { exact: true })).toBeVisible()
  const retryButton = page.getByRole('button', { name: '仅重试 1 个失败分支' })
  const replanButton = page.getByRole('button', { name: '返回 Planner 重新规划' })
  await expect(retryButton).toBeDisabled()
  await expect(replanButton).toBeDisabled()
  await page.getByLabel('工作流人工反馈').fill('验收凭据已补齐，请保留运营交接并仅恢复测试分支。')
  await retryButton.click()

  expect(recoveryPayload).toMatchObject({
    workflow_id: 160,
    decision: 'RETRY',
    human_feedback: '验收凭据已补齐，请保留运营交接并仅恢复测试分支。'
  })
  await expect(page.getByText('失败分支已重新入队，成功交接将从检查点恢复')).toBeVisible()
  if (testInfo.project.name === 'mobile-chromium') {
    await page.setViewportSize({ width: 375, height: 812 })
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('shows dynamic specialist handoffs and submits quality revision feedback', async ({ page }, testInfo) => {
  await page.goto('/projects/2')

  await expect(page.getByRole('heading', { name: '质量门禁项目' })).toBeVisible()
  await expect(page.getByText('动态执行计划', { exact: true })).toBeVisible()
  await expect(page.getByText('2 个并行分支', { exact: true })).toBeVisible()
  await expect(page.getByText('Quality Gate 需要修订', { exact: true })).toBeVisible()
  await expect(page.getByText('缺少可复现验收证据', { exact: true })).toBeVisible()
  const reviewerPanel = page.getByRole('region', { name: '独立 Reviewer 仲裁' })
  await expect(reviewerPanel.getByText('1/2 通过', { exact: true })).toBeVisible()
  await expect(reviewerPanel.getByText('quorum 2', { exact: true })).toBeVisible()
  await expect(reviewerPanel.getByText('1 份分歧', { exact: true })).toBeVisible()
  const operationsReviewer = reviewerPanel.getByRole('listitem').filter({ hasText: '运营 Reviewer' })
  await expect(operationsReviewer).toContainText('建议返修')
  await expect(operationsReviewer).toContainText('65 分')
  await expect(operationsReviewer).toContainText('回滚观察窗口缺少明确负责人。')
  const architectReviewer = reviewerPanel.getByRole('listitem').filter({ hasText: '架构 Reviewer' })
  await expect(architectReviewer).toContainText('合同无效')
  await expect(architectReviewer).toContainText('弃权')
  const ledger = page.getByRole('region', { name: '多 Agent 协作决策账本' })
  await expect(ledger.getByText('灰度发布策略', { exact: true })).toBeVisible()
  await expect(ledger.getByText('发布准入条件', { exact: true })).toBeVisible()
  await expect(ledger.getByText('全量回归通过后才能发布。', { exact: true })).toBeVisible()
  await expect(ledger.getByText('由谁确认灰度扩容阈值？', { exact: true })).toBeVisible()
  await expect(ledger.getByText('阻塞中', { exact: true }).first()).toBeVisible()

  const revisionButton = page.getByRole('button', { name: '提交修订意见', exact: true })
  await expect(revisionButton).toBeDisabled()
  await page.getByLabel('工作流人工反馈').fill('补充证据来源、验收负责人和完成时限')
  await revisionButton.click()

  await expect(page.getByText('Quality Gate 已通过', { exact: true })).toBeVisible()
  await expect(reviewerPanel.getByText('3/3 通过', { exact: true })).toBeVisible()
  await expect(reviewerPanel.getByText('1 份分歧', { exact: true })).toHaveCount(0)
  await expect(reviewerPanel.getByText('支持放行', { exact: true })).toHaveCount(3)
  await expect(ledger.getByText('已解决', { exact: true })).toBeVisible()
  await expect(ledger.getByText('核心冒烟通过后启动 10% 灰度，全量回归通过后才能扩容。', { exact: true })).toBeVisible()
  await expect(page.getByText('最终报告等待人工确认', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认并生成报告', exact: true })).toBeEnabled()
  if (testInfo.project.name === 'mobile-chromium') {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    for (const viewport of [{ width: 375, height: 812 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(viewport)
      await expect(reviewerPanel).toBeVisible()
      await expect(ledger).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
    }
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('reviews, replans and approves an execution plan before specialist dispatch', async ({ page }, testInfo) => {
  let workflowStarted = false
  let runPayload: Record<string, unknown> = {}
  const decisions: Array<Record<string, unknown>> = []
  const teamCapabilities = [
    {
      role: 'test_engineer',
      name: 'AI测试工程师',
      capabilities: ['quality_assurance', 'acceptance_evidence', 'boundary_analysis', 'test_case_generation', 'project_context'],
      enabled_tools: ['context_search', 'testcase_create'],
      knowledge_access: true,
      concurrency_limit: 4,
      eligible: true,
      unavailable_reasons: []
    },
    {
      role: 'operations_analyst',
      name: 'AI运营分析师',
      capabilities: ['operational_readiness', 'risk_analysis', 'observability', 'release_recovery', 'project_analytics', 'delivery_reporting', 'project_context'],
      enabled_tools: ['analytics_report', 'context_search', 'report_generate'],
      knowledge_access: true,
      concurrency_limit: 4,
      eligible: true,
      unavailable_reasons: []
    }
  ]
  const initialPlan = {
    objective: '先验证可恢复交付，再启动专业 Agent',
    rationale: '测试先确认验收证据，运营再基于测试结论设计灰度和恢复。',
    assignments: [
      {
        role: 'test_engineer',
        objective: '验证边界场景与验收证据',
        deliverable: '可复现验收清单',
        depends_on: [],
        required_capabilities: ['quality_assurance', 'acceptance_evidence'],
        selection_reason: '该分支需要质量保障与验收证据，冻结工具权限已满足。'
      },
      {
        role: 'operations_analyst',
        objective: '基于测试结论验证灰度发布与故障恢复',
        deliverable: '发布与回滚手册',
        depends_on: ['test_engineer'],
        required_capabilities: ['operational_readiness', 'release_recovery'],
        selection_reason: '该分支需要运营就绪与发布恢复能力，冻结工具权限已满足。'
      }
    ],
    success_criteria: ['核心路径具备可复现证据', '失败场景具备负责人和回滚条件'],
    team_capabilities: teamCapabilities
  }
  let planWorkflow = {
    workflow_id: 140,
    project_id: 2,
    parent_workflow_id: null,
    retry_from_node: '',
    retry_sequence: 0,
    pause_requested_at: null,
    pause_requested_by_user_id: null,
    pause_reason: '',
    intervention_count: 0,
    status: 'PAUSED',
    current_node: 'plan_review',
    state: {
      execution_plan: initialPlan,
      plan_version: 1,
      plan_revisions: [{ version: 1, plan: initialPlan, feedback: '', created_at: '2026-07-19T08:00:30Z' }],
      require_plan_approval: true,
      plan_approved: false,
      plan_revision_count: 0,
      plan_revision_feedback: '',
      specialist_handoffs: [],
      quality_gate: {},
      documents: [],
      messages: []
    },
    attempt_count: 1,
    max_attempts: 2,
    error: '',
    created_at: '2026-07-19T08:00:00Z',
    updated_at: '2026-07-19T08:01:00Z',
    started_at: '2026-07-19T08:00:01Z',
    finished_at: null
  }

  await page.route(/\/api\/v1\/workflow\?project_id=2$/, (route) => route.fulfill({ json: workflowStarted ? [planWorkflow] : [] }))
  await page.route(/\/api\/v1\/workflow\/preflight$/, async (route) => {
    const input = route.request().postDataJSON() as { user_input: string }
    const notificationAvailable = !/通知|邮件|短信|提醒|notification|email/i.test(input.user_input)
    await route.fulfill({ json: workflowPreflightFixture(input.user_input, notificationAvailable) })
  })
  await page.route(/\/api\/v1\/workflow\/run$/, async (route) => {
    runPayload = route.request().postDataJSON() as Record<string, unknown>
    workflowStarted = true
    await route.fulfill({
      json: {
        ...planWorkflow,
        status: 'QUEUED',
        current_node: 'requirement',
        state: { documents: [], messages: [] }
      }
    })
  })
  await page.route(/\/api\/v1\/workflow\/140$/, (route) => route.fulfill({ json: planWorkflow }))
  await page.route(/\/api\/v1\/workflow\/140\/saga-steps$/, (route) => route.fulfill({ json: [] }))
  await page.route(/\/api\/v1\/workflow\/140\/events\/history(?:\?.*)?$/, (route) => route.fulfill({
    json: [
      { id: 1, workflow_id: 140, node: 'planning', event_type: 'PLAN_CREATED', message: 'Plan created', payload: { approval_required: true }, created_at: '2026-07-19T08:00:30Z' },
      { id: 2, workflow_id: 140, node: 'plan_review', event_type: 'PAUSED', message: 'Waiting for approval', payload: { approval_gate: 'plan_review' }, created_at: '2026-07-19T08:01:00Z' }
    ]
  }))
  await page.route(/\/api\/v1\/workflow\/140\/events$/, (route) => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'retry: 10000\n\n'
  }))
  await page.route(/\/api\/v1\/workflow\/continue$/, async (route) => {
    const payload = route.request().postDataJSON() as Record<string, unknown>
    decisions.push(payload)
    if (payload.decision === 'REVISE') {
      const revisedPlan = {
        ...initialPlan,
        objective: '补齐安全边界后的可恢复交付计划',
        rationale: '已根据人工计划意见补充安全验收和负责人。',
        assignments: initialPlan.assignments.map((assignment) => assignment.role === 'test_engineer'
          ? { ...assignment, deliverable: '安全边界与可复现验收清单' }
          : assignment),
        success_criteria: [...initialPlan.success_criteria, '数据安全边界具有明确负责人']
      }
      planWorkflow = {
        ...planWorkflow,
        state: {
          ...planWorkflow.state,
          execution_plan: revisedPlan,
          plan_version: 2,
          plan_revisions: [
            ...planWorkflow.state.plan_revisions,
            {
              version: 2,
              plan: revisedPlan,
              feedback: String(payload.human_feedback),
              created_at: '2026-07-19T08:02:00Z'
            }
          ],
          plan_revision_count: 1,
          plan_revision_feedback: String(payload.human_feedback)
        }
      }
    } else {
      const approvedVersion = Number(payload.plan_version)
      const approvedRevision = planWorkflow.state.plan_revisions.find((revision) => revision.version === approvedVersion)
      planWorkflow = {
        ...planWorkflow,
        status: 'QUEUED',
        current_node: 'specialists',
        state: {
          ...planWorkflow.state,
          execution_plan: approvedRevision?.plan || planWorkflow.state.execution_plan,
          plan_version: approvedVersion,
          plan_approved: true
        }
      }
    }
    await route.fulfill({ json: planWorkflow })
  })

  await page.goto('/projects/2')
  await page.getByRole('button', { name: '运行多 Agent 工作流', exact: true }).click()
  const launchDialog = page.getByRole('dialog')
  await expect(launchDialog.getByRole('heading', { name: '启动工作流', exact: true })).toBeVisible()
  await expect(launchDialog.getByRole('list', { name: '专业 Agent 资格' }).getByRole('listitem')).toHaveCount(4)
  await expect(launchDialog.getByText('可以启动', { exact: true })).toBeVisible()

  const goalInput = launchDialog.getByLabel('多 Agent 工作目标')
  const launchButton = launchDialog.getByRole('button', { name: '启动并进入计划审批', exact: true })
  await goalInput.fill('生成并发送项目邮件通知')
  await expect(launchDialog.getByText('当前团队缺少所需能力：通知投递。', { exact: true })).toBeVisible()
  await expect(launchButton).toBeDisabled()

  if (testInfo.project.name === 'mobile-chromium') {
    for (const viewport of [{ width: 375, height: 812 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(viewport)
      await expect(launchDialog).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
    }
    await page.setViewportSize({ width: 375, height: 812 })
  }

  const editedGoal = '设计可灰度发布并可回滚的会员平台'
  await goalInput.fill(editedGoal)
  await expect(launchDialog.getByText('可以启动', { exact: true })).toBeVisible()
  await expect(launchButton).toBeEnabled()
  await launchButton.click()
  await expect.poll(() => runPayload.user_input).toBe(editedGoal)
  expect(runPayload).toMatchObject({ user_input: editedGoal, require_plan_approval: true })
  const workflowReloaded = page.waitForResponse((response) => (
    response.request().method() === 'GET'
    && /\/api\/v1\/workflow\?project_id=2$/.test(response.url())
  ))
  await page.reload()
  await workflowReloaded

  await expect(page.getByText('执行计划 v1 等待批准', { exact: true })).toBeVisible()
  await expect(page.getByText('测试先确认验收证据，运营再基于测试结论设计灰度和恢复。', { exact: true })).toBeVisible()
  await expect(page.getByText('2 个分支 · 2 波', { exact: true })).toBeVisible()
  const firstWave = page.getByLabel('执行计划第 1 波')
  const secondWave = page.getByLabel('执行计划第 2 波')
  await expect(firstWave.getByText('测试工程师', { exact: true })).toBeVisible()
  await expect(firstWave.getByText('所需能力', { exact: true })).toBeVisible()
  await expect(firstWave.getByText('质量保障 · 验收证据', { exact: true })).toBeVisible()
  const selectionReason = firstWave.locator('.branch-selection-reason')
  await expect(selectionReason).toContainText('组队依据')
  await expect(selectionReason).toContainText('该分支需要质量保障与验收证据，冻结工具权限已满足。')
  await firstWave.getByText('能力匹配 2/5 · 查看冻结配置', { exact: true }).click()
  await expect(firstWave.getByText('项目上下文检索、测试用例生成', { exact: true })).toBeVisible()
  await expect(firstWave.getByText('并发 4 · 知识访问已启用', { exact: true })).toBeVisible()
  await expect(secondWave.getByText('运营分析师', { exact: true })).toBeVisible()
  await expect(secondWave.getByText('依赖', { exact: true })).toBeVisible()
  await expect(secondWave.getByText('测试工程师', { exact: true })).toBeVisible()
  await expect(page.getByText('核心路径具备可复现证据', { exact: true })).toBeVisible()
  await expect(page.getByText('失败场景具备负责人和回滚条件', { exact: true })).toBeVisible()
  const reviseButton = page.getByRole('button', { name: '要求重新规划', exact: true })
  await expect(reviseButton).toBeDisabled()
  await page.getByLabel('工作流人工反馈').fill('补充数据安全边界，并为回滚验收指定负责人')
  await reviseButton.click()
  await expect(page.getByText('补齐安全边界后的可恢复交付计划', { exact: true })).toBeVisible()
  await expect(page.getByText('相较 v1 的变化', { exact: true })).toBeVisible()
  await expect(page.getByText('调整总体目标', { exact: true })).toBeVisible()
  await expect(page.getByText('更新编排理由', { exact: true })).toBeVisible()
  await expect(page.getByText('更新分支：测试工程师', { exact: true })).toBeVisible()
  await expect(page.getByText('新增 1 项成功标准', { exact: true })).toBeVisible()
  await expect(page.getByText('重规划意见：补充数据安全边界，并为回滚验收指定负责人', { exact: true })).toBeVisible()
  expect(decisions[0]).toMatchObject({ decision: 'REVISE', human_feedback: '补充数据安全边界，并为回滚验收指定负责人', plan_version: 1 })

  const versionSelector = page.getByLabel('执行计划版本')
  await expect(versionSelector).toContainText('v1')
  await expect(versionSelector).toContainText('v2')
  await versionSelector.getByText('v1', { exact: true }).click()
  await expect(page.getByText('先验证可恢复交付，再启动专业 Agent', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '批准 v1 并启动 2 个分支', exact: true }).click()
  await expect(page.getByText('已批准', { exact: true })).toBeVisible()
  expect(decisions[1]).toMatchObject({ decision: 'APPROVE', human_feedback: '', plan_version: 1 })
  if (testInfo.project.name === 'mobile-chromium') {
    for (const viewport of [{ width: 375, height: 812 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(viewport)
      await expect(page.getByLabel('多 Agent 执行计划')).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
    }
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})

test('uses the five-screen interactive prototype on desktop and mobile preview', async ({ page }, testInfo) => {
  await page.goto('/prototypes?prototype=41')

  await expect(page.getByRole('heading', { name: 'AI 原型工作室' })).toBeVisible()
  await expect(page.getByText('偶像泡泡 - 手机号注册登录 + 邀请裂变', { exact: true })).toBeVisible()
  await expect(page.locator('.screen-list button')).toHaveCount(5)
  await expect(page.getByText('通过自动门禁')).toBeVisible()

  await page.getByRole('button', { name: '完成注册', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('请先完成必填项')
  await page.getByLabel('手机号').fill('13800138000')
  await page.getByLabel('设置密码').fill('prototype-pass')
  await page.getByRole('button', { name: '完成注册', exact: true }).click()
  await expect(page.getByText('账号登录', { exact: true })).toBeVisible()

  await page.getByText('移动', { exact: true }).click()
  await expect(page.locator('.device-mobile')).toBeVisible()
  await page.getByText('Agent', { exact: true }).click()
  await expect(page.getByText('AI产品经理', { exact: true })).toBeVisible()
  await expect(page.getByText('AI架构师', { exact: true })).toBeVisible()
  await expect(page.getByText('AI测试工程师', { exact: true })).toBeVisible()

  await page.getByRole('tab', { name: '路径 3', exact: true }).click()
  await expect(page.getByLabel('体验路径进度').getByText('新用户注册并查看邀请进度', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '开始体验', exact: true }).click()
  await expect(page.getByText('步骤 1/3', { exact: true })).toBeVisible()
  await expect(page.locator('.journey-target')).toHaveText('完成注册')
  await page.getByLabel('手机号').fill('13800138000')
  await page.getByLabel('设置密码').fill('prototype-pass')
  await page.getByRole('button', { name: '完成注册', exact: true }).click()
  await expect(page.getByText('步骤 2/3', { exact: true })).toBeVisible()
  await expect(page.locator('.journey-target')).toHaveText('登录')
  await page.getByRole('button', { name: '忘记密码？', exact: true }).click()
  await expect(page.locator('.journey-feedback')).toContainText('当前需要在登录页触发“登录”')
  await expect(page.locator('.prototype-runtime').getByRole('heading', { name: '重置密码', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '定位当前步骤', exact: true }).click()
  await expect(page.locator('.prototype-runtime').getByText('账号登录', { exact: true })).toBeVisible()
  await page.getByLabel('手机号').fill('13800138000')
  await page.getByLabel('密码').fill('prototype-pass')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText('步骤 3/3', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '查看全部邀请记录', exact: true }).click()
  await expect(page.locator('.journey-feedback')).toContainText('路径体验完成')
  await expect(page.getByText('3/3 步已完成', { exact: true })).toBeVisible()

  if (testInfo.project.name === 'mobile-chromium') {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    for (const viewport of [{ width: 375, height: 812 }, { width: 844, height: 390 }]) {
      await page.setViewportSize(viewport)
      await expect(page.locator('.prototype-runtime')).toBeVisible()
      await expect(page.locator('.journey-panel')).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
    }
  }

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('generates, regenerates and restores immutable prototype versions', async ({ page }) => {
  await page.goto('/prototypes')

  await page.getByRole('button', { name: '新建原型' }).click()
  await page.getByPlaceholder('例如：手机号注册与邀请增长原型').fill('会员增长产品原型')
  await page.getByPlaceholder('描述目标用户、业务目标、关键页面、核心流程和验收要求').fill('为会员增长团队生成注册、登录、邀请和奖励查询的完整可交互原型。')
  await page.getByRole('button', { name: '开始生成' }).click()
  await expect(page.getByText('会员增长产品原型', { exact: true })).toBeVisible()
  await expect(page.locator('.version-label')).toHaveText('v1')

  await page.getByRole('button', { name: '重新生成' }).click()
  await page.getByPlaceholder('例如：增加邀请奖励状态，并将移动端首要操作固定在底部').fill('增加邀请奖励状态')
  await page.getByRole('button', { name: '生成新版本' }).click()
  await expect(page.locator('.version-label')).toHaveText('v2')
  await expect(page.getByText('历史版本 v1')).toBeVisible()

  await page.getByRole('button', { name: '恢复原型版本' }).click()
  await expect(page.locator('.version-label')).toHaveText('v1')
  await expect(page.getByText('已恢复原型 v1')).toBeVisible()
})

test('restores an active prototype job after refresh and retries a transient failure', async ({ page }) => {
  await page.goto('/prototypes')

  await page.getByRole('button', { name: '新建原型' }).click()
  await page.getByPlaceholder('例如：手机号注册与邀请增长原型').fill('刷新恢复原型')
  await page.getByPlaceholder('描述目标用户、业务目标、关键页面、核心流程和验收要求').fill('生成支持刷新恢复的注册、邀请和奖励查询可交互原型。')
  await page.getByRole('button', { name: '开始生成' }).click()
  await expect(page.getByText('刷新恢复原型 · 等待执行', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('刷新恢复原型', { exact: true })).toBeVisible()
  await expect(page.getByText('产品原型已生成', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '新建原型' }).click()
  await page.getByPlaceholder('例如：手机号注册与邀请增长原型').fill('失败恢复原型')
  await page.getByPlaceholder('描述目标用户、业务目标、关键页面、核心流程和验收要求').fill('生成首次失败后能够保留上下文并继续执行的可交互原型。')
  await page.getByRole('button', { name: '开始生成' }).click()
  await expect(page.getByText('原型生成失败', { exact: true })).toBeVisible()
  await expect(page.locator('.generation-job-error')).toHaveText('模型服务响应超时，已保留当前生成上下文。')
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.getByText('失败恢复原型', { exact: true })).toBeVisible()
  await expect(page.getByText('产品原型已生成', { exact: true })).toBeVisible()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('reviews, approves and converts a prototype into delivery evidence', async ({ page }) => {
  await page.goto('/prototypes?prototype=41')

  await page.getByText('评审 0', { exact: true }).click()
  await page.getByLabel('原型评审评论').fill('请补充手机号格式错误状态')
  await page.getByRole('button', { name: '添加评论', exact: true }).click()
  await expect(page.getByText('请补充手机号格式错误状态', { exact: true })).toBeVisible()
  await expect(page.getByText('评审 1', { exact: true })).toBeVisible()

  await page.locator('.inspector-status .el-select').click()
  await page.getByRole('option', { name: '已批准', exact: true }).click()
  await expect(page.getByText('请先解决当前版本的开放评审评论')).toBeVisible()

  await page.getByRole('button', { name: '标记已解决', exact: true }).click()
  await expect(page.getByText('已解决', { exact: true })).toBeVisible()
  await page.locator('.inspector-status .el-select').click()
  await page.getByRole('option', { name: '已批准', exact: true }).click()
  await expect(page.getByRole('button', { name: '生成交付清单', exact: true })).toBeVisible()

  await page.getByRole('button', { name: '生成交付清单', exact: true }).click()
  const deliveryDialog = page.getByRole('dialog', { name: '原型交付清单' })
  await expect(deliveryDialog).toBeVisible()
  const deliverySummary = deliveryDialog.locator('.materialization-summary')
  await expect(deliverySummary.getByText('实现任务', { exact: true })).toBeVisible()
  await expect(deliverySummary.getByText('验收用例', { exact: true })).toBeVisible()
  await expect(deliveryDialog.getByText('校验注册页必填字段', { exact: true })).toBeVisible()
  await deliveryDialog.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByLabel('原型评审评论').fill('交付后发现新的边界场景')
  await page.getByRole('button', { name: '添加评论', exact: true }).click()
  await expect(page.getByText('评审评论已添加，原型已回到评审中')).toBeVisible()
  await expect(page.getByRole('button', { name: '生成交付清单', exact: true })).toHaveCount(0)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
