import axios, { type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/es/components/message/style/css.mjs'
import type { TokenResponse } from './types'

declare module 'axios' {
  export interface AxiosRequestConfig {
    suppressErrorToast?: boolean
  }
}


export const apiBaseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const api = axios.create({
  baseURL: apiBaseURL,
  withCredentials: true
})

let refreshPromise: Promise<string> | null = null

interface ValidationErrorDetail {
  loc?: Array<string | number>
  msg?: string
}

export function getApiErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error) || !error.response) {
    return '网络连接失败，请检查网络后重试'
  }
  const detail = error.response.data?.detail
  if (Array.isArray(detail)) {
    const first = detail[0] as ValidationErrorDetail | undefined
    const field = first?.loc?.[first.loc.length - 1]
    if (field && first?.msg) return `${field}: ${first.msg}`
  }
  if (typeof detail === 'string') {
    return error.response.status === 409 ? `${detail}，请刷新后重试` : detail
  }
  const statusMessages: Record<number, string> = {
    403: '当前账号没有执行此操作的权限',
    404: '请求的资源不存在或已被删除',
    409: '数据已发生变化，请刷新后重试',
    422: '提交内容有误，请检查后重试',
    429: '操作过于频繁，请稍后重试',
    500: '服务暂时不可用，请稍后重试'
  }
  return statusMessages[error.response.status] || '请求失败，请稍后重试'
}

function persistSession(data: TokenResponse) {
  localStorage.setItem('token', data.access_token)
  localStorage.setItem('user', JSON.stringify(data.user))
}

function expireSession() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  if (window.location.pathname !== '/login') window.location.assign('/login')
}

function isRejectedRefresh(error: unknown): boolean {
  return axios.isAxiosError(error) && [401, 403].includes(error.response?.status || 0)
}

export async function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = axios
      .post<TokenResponse>(`${apiBaseURL}/auth/refresh`, {}, { withCredentials: true })
      .then(({ data }) => {
        persistSession(data)
        return data.access_token
      })
      .catch((error) => {
        if (isRejectedRefresh(error)) expireSession()
        throw error
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined
    const url = String(config?.url || '')
    const isAuthRequest = ['/auth/login', '/auth/register', '/auth/refresh'].some((path) => url.includes(path))
    if (error.response?.status === 401 && config && !config._retry && !isAuthRequest) {
      config._retry = true
      try {
        const token = await refreshAccessToken()
        config.headers.Authorization = `Bearer ${token}`
        return api.request(config)
      } catch {
        return Promise.reject(error)
      }
    }
    if (!config?.suppressErrorToast && error.response?.status !== 401) {
      ElMessage.error(getApiErrorMessage(error))
    }
    return Promise.reject(error)
  }
)
