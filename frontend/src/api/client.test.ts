import { afterEach, describe, expect, it, vi } from 'vitest'
import axios, { AxiosError, AxiosHeaders } from 'axios'
import { getApiErrorMessage, refreshAccessToken } from './client'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

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

  it('shares one refresh request across concurrent stream and API consumers', async () => {
    const post = vi.spyOn(axios, 'post').mockResolvedValue({
      data: {
        access_token: 'fresh-token',
        user: { id: 1, email: 'owner@example.com', name: 'Owner', role: 'member' }
      }
    })

    const [streamToken, apiToken] = await Promise.all([
      refreshAccessToken(),
      refreshAccessToken()
    ])

    expect(streamToken).toBe('fresh-token')
    expect(apiToken).toBe('fresh-token')
    expect(post).toHaveBeenCalledOnce()
    expect(localStorage.getItem('token')).toBe('fresh-token')
  })

  it('keeps the current session during a temporary refresh network failure', async () => {
    localStorage.setItem('token', 'stale-token')
    vi.spyOn(axios, 'post').mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))

    await expect(refreshAccessToken()).rejects.toThrow('Network Error')

    expect(localStorage.getItem('token')).toBe('stale-token')
  })
})
