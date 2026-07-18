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
        summary: '测试交接需要补充证据来源与负责人。'
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
    } else if (method === 'GET' && path === '/agents') body = discussionAgents
    else if (method === 'GET' && path === '/agents/conversations') body = []
    else if (method === 'POST' && path === '/agents/discussion/stream') {
      await new Promise((resolve) => setTimeout(resolve, 300))
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: discussionEventStream() })
    }
    else if (method === 'GET' && path === '/dashboard/stats') {
      body = { projects: projects.length, agents: 0, tasks: { TODO: 2, RUNNING: 1, DONE: 3, FAILED: 0 }, documents: 4, recent_activities: ['完成灰度检查'] }
    } else if (method === 'GET' && path === '/requirements') body = requirements
    else if (method === 'GET' && path === '/workflow') body = url.searchParams.get('project_id') === '2' ? [qualityWorkflow] : [workflow]
    else if (method === 'GET' && path === '/workflow/88') body = workflow
    else if (method === 'GET' && path === '/workflow/99') body = qualityWorkflow
    else if (method === 'GET' && path === '/workflow/88/saga-steps') body = sagaSteps
    else if (method === 'GET' && path === '/workflow/99/saga-steps') body = []
    else if (method === 'GET' && /^\/workflow\/(88|99)\/events$/.test(path)) {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    } else if (method === 'POST' && path === '/workflow/continue') {
      qualityWorkflow = {
        ...qualityWorkflow,
        status: 'PAUSED',
        current_node: 'report',
        state: {
          ...qualityWorkflow.state,
          quality_gate: { ...qualityWorkflow.state.quality_gate, score: 95, passed: true, issues: [], summary: '质量门禁已通过。' },
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

test('shows dynamic specialist handoffs and submits quality revision feedback', async ({ page }) => {
  await page.goto('/projects/2')

  await expect(page.getByRole('heading', { name: '质量门禁项目' })).toBeVisible()
  await expect(page.getByText('动态执行计划', { exact: true })).toBeVisible()
  await expect(page.getByText('2 个并行分支', { exact: true })).toBeVisible()
  await expect(page.getByText('Quality Gate 需要修订', { exact: true })).toBeVisible()
  await expect(page.getByText('缺少可复现验收证据', { exact: true })).toBeVisible()

  const revisionButton = page.getByRole('button', { name: '提交修订意见', exact: true })
  await expect(revisionButton).toBeDisabled()
  await page.getByLabel('工作流人工反馈').fill('补充证据来源、验收负责人和完成时限')
  await revisionButton.click()

  await expect(page.getByText('Quality Gate 已通过', { exact: true })).toBeVisible()
  await expect(page.getByText('最终报告等待人工确认', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认并生成报告', exact: true })).toBeEnabled()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('uses the five-screen interactive prototype on desktop and mobile preview', async ({ page }) => {
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
