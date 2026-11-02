import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'

import { clearAccessToken, getAuthHeader, setAccessToken } from '../api/client'
import { useSignOut } from '../composables/useSignOut'
import { createAppRouter } from '../router'
import { useSessionStore } from '../stores/session'

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    clearAccessToken()
  })

  it('guarda solo nombre y rol', () => {
    const session = useSessionStore()
    session.setUser('Ana Pérez', 'student')
    expect(session.isAuthenticated).toBe(true)
    expect(session.isAdmin).toBe(false)
    expect(session.fullName).toBe('Ana Pérez')
    expect(session.role).toBe('student')
    expect(Object.keys(session.$state).sort()).toEqual(['fullName', 'role'])
  })

  it('soporta rol de administrador sin exponer datos adicionales', () => {
    const session = useSessionStore()
    session.setUser('Admin General', 'admin')
    expect(session.isAuthenticated).toBe(true)
    expect(session.isAdmin).toBe(true)
    expect(Object.keys(session.$state).sort()).toEqual(['fullName', 'role'])
  })

  it('el cierre de sesión con clear() limpia Pinia y destruye el token privado del módulo HTTP', () => {
    const session = useSessionStore()
    setAccessToken('token-secreto-estudiante')
    session.setUser('Carlos Ruiz', 'student')

    expect(session.isAuthenticated).toBe(true)
    expect(getAuthHeader()).toEqual({ Authorization: 'Bearer token-secreto-estudiante' })

    session.clear()

    expect(session.isAuthenticated).toBe(false)
    expect(session.fullName).toBeNull()
    expect(session.role).toBeNull()
    expect(getAuthHeader()).toEqual({})
    expect(Object.keys(session.$state).sort()).toEqual(['fullName', 'role'])
  })

  it('logout() es un alias que limpia la sesión en Pinia y el token privado en memoria', () => {
    const session = useSessionStore()
    setAccessToken('token-admin')
    session.setUser('Admin', 'admin')

    expect(session.isAuthenticated).toBe(true)
    expect(getAuthHeader()).toEqual({ Authorization: 'Bearer token-admin' })

    session.logout()

    expect(session.isAuthenticated).toBe(false)
    expect(session.fullName).toBeNull()
    expect(session.role).toBeNull()
    expect(getAuthHeader()).toEqual({})
  })

  it('no almacena el access token en localStorage ni sessionStorage', () => {
    const mockStorage = {
      getItem: vi.fn(),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      length: 0,
      key: vi.fn(),
    }

    const originalLocalStorage = globalThis.localStorage
    const originalSessionStorage = globalThis.sessionStorage

    Object.defineProperty(globalThis, 'localStorage', {
      value: mockStorage,
      configurable: true,
      writable: true,
    })
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: mockStorage,
      configurable: true,
      writable: true,
    })

    try {
      const session = useSessionStore()
      setAccessToken('jwt-en-memoria')
      session.setUser('Ana Pérez', 'student')

      expect(mockStorage.setItem).not.toHaveBeenCalled()

      session.clear()

      expect(mockStorage.setItem).not.toHaveBeenCalled()
    } finally {
      Object.defineProperty(globalThis, 'localStorage', {
        value: originalLocalStorage,
        configurable: true,
        writable: true,
      })
      Object.defineProperty(globalThis, 'sessionStorage', {
        value: originalSessionStorage,
        configurable: true,
        writable: true,
      })
    }
  })
})

describe('api client', () => {
  beforeEach(() => {
    clearAccessToken()
  })

  it('arma el header Authorization solo si hay token en memoria', () => {
    expect(getAuthHeader()).toEqual({})
    setAccessToken('abc')
    expect(getAuthHeader()).toEqual({ Authorization: 'Bearer abc' })
    setAccessToken(null)
    expect(getAuthHeader()).toEqual({})
  })

  it('clearAccessToken() destruye el token privado en memoria', () => {
    setAccessToken('token-prueba-limpieza')
    expect(getAuthHeader()).toEqual({ Authorization: 'Bearer token-prueba-limpieza' })

    clearAccessToken()
    expect(getAuthHeader()).toEqual({})
  })
})

describe('useSignOut', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    clearAccessToken()
  })

  it('cierra la sesión en Pinia, limpia el token privado y redirige al login', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createAppRouter(createMemoryHistory())
    const session = useSessionStore()
    setAccessToken('token-para-salir')
    session.setUser('Ana Pérez', 'student')

    await router.push('/')
    expect(session.isAuthenticated).toBe(true)
    expect(getAuthHeader()).toEqual({ Authorization: 'Bearer token-para-salir' })

    let signOut!: ReturnType<typeof useSignOut>
    mount(
      defineComponent({
        setup() {
          signOut = useSignOut()
          return () => null
        },
      }),
      {
        global: {
          plugins: [pinia, router],
        },
      },
    )

    await signOut()

    expect(session.isAuthenticated).toBe(false)
    expect(session.fullName).toBeNull()
    expect(session.role).toBeNull()
    expect(getAuthHeader()).toEqual({})
    expect(router.currentRoute.value.name).toBe('login')
  })
})
