import { describe, expect, it } from 'vitest'
import { containsQuery, paginate } from './collection'

describe('collection helpers', () => {
  it('matches case-insensitively across optional values', () => {
    expect(containsQuery('API', '接入 api 网关', undefined)).toBe(true)
    expect(containsQuery('不存在', '接入 API 网关')).toBe(false)
  })

  it('returns the requested page and clamps invalid page values', () => {
    expect(paginate([1, 2, 3, 4, 5], 2, 2)).toEqual([3, 4])
    expect(paginate([1, 2, 3], 0, 2)).toEqual([1, 2])
  })
})
