import { describe, expect, it } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import { getApiErrorMessage } from './client'

describe('getApiErrorMessage', () => {
  it('uses FastAPI detail and gives conflict errors a recovery hint', () => {
    const error = new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
      data: { detail: '版本已过期' },
      status: 409,
      statusText: 'Conflict',
      headers: {},
      config: { headers: new AxiosHeaders() }
    })

    expect(getApiErrorMessage(error)).toBe('版本已过期，请刷新后重试')
  })

  it('handles validation detail arrays without exposing raw objects', () => {
    const error = new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
      data: { detail: [{ loc: ['body', 'title'], msg: 'Field required' }] },
      status: 422,
      statusText: 'Unprocessable Entity',
      headers: {},
      config: { headers: new AxiosHeaders() }
    })

    expect(getApiErrorMessage(error)).toBe('title: Field required')
  })

  it('returns an actionable offline message for network failures', () => {
    expect(getApiErrorMessage(new AxiosError('Network Error', 'ERR_NETWORK'))).toBe('网络连接失败，请检查网络后重试')
  })
})
