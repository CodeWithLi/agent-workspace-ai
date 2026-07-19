import { describe, expect, it } from 'vitest'
import { specialistCapabilityLabel, specialistRoleLabel, specialistToolLabel } from './specialists'

describe('specialist labels', () => {
  it('maps governed specialist metadata and preserves unknown values', () => {
    expect(specialistRoleLabel('test_engineer')).toBe('测试工程师')
    expect(specialistCapabilityLabel('knowledge_retrieval')).toBe('知识检索')
    expect(specialistToolLabel('notification_create')).toBe('通知投递')
    expect(specialistCapabilityLabel('future_capability')).toBe('future_capability')
  })
})
