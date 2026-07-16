import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { TokenResponse, User } from '../api/types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: JSON.parse(localStorage.getItem('user') || 'null') as User | null
  }),
  actions: {
    async login(email: string, password: string) {
      const { data } = await api.post<TokenResponse>('/auth/login', { email, password })
      this.setSession(data)
    },
    async register(email: string, name: string, password: string) {
      const { data } = await api.post<TokenResponse>('/auth/register', { email, name, password })
      this.setSession(data)
    },
    async fetchMe() {
      if (!this.token) return null
      const { data } = await api.get<User>('/users/me')
      this.user = data
      localStorage.setItem('user', JSON.stringify(data))
      return data
    },
    hasRole(role: 'admin' | 'member') {
      return this.user?.role === role
    },
    hasPermission(permission: string) {
      if (this.user?.role === 'admin') return true
      return (this.user?.permissions || '').split(',').map((item) => item.trim()).includes(permission)
    },
    setSession(data: TokenResponse) {
      this.token = data.access_token
      this.user = data.user
      localStorage.setItem('token', data.access_token)
      localStorage.setItem('user', JSON.stringify(data.user))
    },
    setTokenBalance(balance: number) {
      if (!this.user) return
      this.user.ai_token_balance = balance
      localStorage.setItem('user', JSON.stringify(this.user))
    },
    async logout() {
      try {
        await api.post('/auth/logout')
      } finally {
        this.token = ''
        this.user = null
        localStorage.removeItem('token')
        localStorage.removeItem('user')
      }
    }
  }
})
