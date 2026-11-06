import { defineStore } from 'pinia'

import { clearAccessToken } from '@/api/client'

export type UserRole = 'student' | 'admin'

/**
 * Solo nombre y rol (SRS 12.2). El access token NO se guarda aquí:
 * vive en una variable privada del módulo cliente HTTP (src/api).
 */
export const useSessionStore = defineStore('session', {
  state: () => ({
    fullName: null as string | null,
    role: null as UserRole | null,
  }),
  getters: {
    isAuthenticated: (state) => state.role !== null,
    isAdmin: (state) => state.role === 'admin',
  },
  actions: {
    setUser(fullName: string, role: UserRole) {
      this.fullName = fullName
      this.role = role
    },
    clear() {
      this.fullName = null
      this.role = null
      clearAccessToken()
    },
    logout() {
      this.clear()
    },
  },
})
