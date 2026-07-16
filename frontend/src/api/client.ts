import axios, { type InternalAxiosRequestConfig } from 'axios'
import type { TokenResponse } from './types'


export const apiBaseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const api = axios.create({
  baseURL: apiBaseURL,
  withCredentials: true
})

let refreshPromise: Promise<string> | null = null

function persistSession(data: TokenResponse) {
  localStorage.setItem('token', data.access_token)
  localStorage.setItem('user', JSON.stringify(data.user))
}

export async function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = axios
      .post<TokenResponse>(`${apiBaseURL}/auth/refresh`, {}, { withCredentials: true })
      .then(({ data }) => {
        persistSession(data)
        return data.access_token
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
        localStorage.removeItem('token')
        localStorage.removeItem('user')
        if (window.location.pathname !== '/login') window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  }
)
