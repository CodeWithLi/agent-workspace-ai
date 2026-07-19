const roleLabels: Record<string, string> = {
  test_engineer: '测试工程师',
  operations_analyst: '运营分析师',
  knowledge_admin: '知识库管理员',
  notification_secretary: '通知秘书'
}

const capabilityLabels: Record<string, string> = {
  quality_assurance: '质量保障',
  acceptance_evidence: '验收证据',
  boundary_analysis: '边界分析',
  test_case_generation: '测试用例生成',
  operational_readiness: '运营就绪',
  risk_analysis: '风险分析',
  observability: '可观测性',
  release_recovery: '发布与恢复',
  project_analytics: '项目分析',
  delivery_reporting: '交付报告',
  knowledge_governance: '知识治理',
  source_traceability: '来源追溯',
  knowledge_retrieval: '知识检索',
  notification_design: '通知设计',
  delivery_reliability: '触达可靠性',
  audience_governance: '受众治理',
  notification_delivery: '通知投递',
  project_context: '项目上下文'
}

const toolLabels: Record<string, string> = {
  context_search: '项目上下文检索',
  testcase_create: '测试用例生成',
  analytics_report: '项目分析报告',
  report_generate: '交付报告生成',
  knowledge_search: '知识库检索',
  notification_create: '通知投递'
}

export function specialistRoleLabel(role: string) {
  return roleLabels[role] || role
}

export function specialistCapabilityLabel(capability: string) {
  return capabilityLabels[capability] || capability
}

export function specialistToolLabel(tool: string) {
  return toolLabels[tool] || tool
}
