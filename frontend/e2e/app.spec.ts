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

  await page.route('**/api/v1/**', async (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const method = request.method()
    let body: unknown = {}

    if (method === 'GET' && path === '/projects') body = projects
    else if (method === 'GET' && path === '/projects/1') body = baseProject
    else if (method === 'GET' && path === '/projects/1/tasks') body = []
    else if (method === 'GET' && path === '/projects/1/members') body = [{ id: 1, user_id: 1, role: 'owner', ...user }]
    else if (method === 'GET' && path === '/projects/1/activity') body = []
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
    else if (method === 'GET' && path === '/workflow') body = [workflow]
    else if (method === 'GET' && path === '/workflow/88') body = workflow
    else if (method === 'GET' && path === '/workflow/88/saga-steps') body = sagaSteps
    else if (method === 'GET' && path === '/workflow/88/events') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
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
