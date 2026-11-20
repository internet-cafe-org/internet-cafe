import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'

import { clearAccessToken, getAuthHeader } from '../api/client'
import { server } from '../mocks/server'
import { decodeJwtPayload, refresh, restoreSession } from '../services/auth'
import { useSessionStore } from '../stores/session'

function createFakeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'ES256', typ: 'JWT' }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
  const body = btoa(unescape(encodeURIComponent(JSON.stringify(payload))))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
  const signature = 'fake-signature'
  return `${header}.${body}.${signature}`
}

describe('HU-31: Recuperación de sesión al arrancar (UI-04c)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    clearAccessToken()
  })

  afterEach(() => {
    server.resetHandlers()
    clearAccessToken()
  })

  describe('decodeJwtPayload', () => {
    it('decodifica el rol y nombre del access token', () => {
      const token = createFakeJwt({
        sub: 'user-123',
        role: 'student',
        full_name: 'Ana Pérez',
        exp: 1700000000,
      })
      const payload = decodeJwtPayload(token)
      expect(payload).not.toBeNull()
      expect(payload?.role).toBe('student')
      expect(payload?.full_name).toBe('Ana Pérez')
      expect(payload?.sub).toBe('user-123')
    })

    it('devuelve null ante un token malformado', () => {
      expect(decodeJwtPayload('token-invalido')).toBeNull()
      expect(decodeJwtPayload('')).toBeNull()
      expect(decodeJwtPayload('a.b')).toBeNull()
    })
  })

  describe('Camino feliz: recuperación de sesión', () => {
    it('recupera la sesión de un estudiante con /auth/refresh', async () => {
      const token = createFakeJwt({
        sub: 'student-uuid',
        role: 'student',
        full_name: 'Carlos Ruiz',
      })

      server.use(
        http.post('*/api/v1/auth/refresh', () => {
          return HttpResponse.json({
            access_token: token,
            token_type: 'Bearer',
            expires_in: 600,
          })
        }),
      )

      const session = useSessionStore()
      expect(session.isAuthenticated).toBe(false)
      expect(getAuthHeader()).toEqual({})

      const recovered = await restoreSession()

      expect(recovered).toBe(true)
      expect(session.isAuthenticated).toBe(true)
      expect(session.isAdmin).toBe(false)
      expect(session.role).toBe('student')
      expect(session.fullName).toBe('Carlos Ruiz')
      expect(getAuthHeader()).toEqual({ Authorization: `Bearer ${token}` })
    })

    it('recupera la sesión de un administrador con /auth/refresh', async () => {
      const token = createFakeJwt({
        sub: 'admin-uuid',
        role: 'admin',
        full_name: 'Admin General',
      })

      server.use(
        http.post('*/api/v1/auth/refresh', () => {
          return HttpResponse.json({
            access_token: token,
            token_type: 'Bearer',
            expires_in: 600,
          })
        }),
      )

      const session = useSessionStore()
      const recovered = await restoreSession()

      expect(recovered).toBe(true)
      expect(session.isAuthenticated).toBe(true)
      expect(session.isAdmin).toBe(true)
      expect(session.role).toBe('admin')
      expect(session.fullName).toBe('Admin General')
      expect(getAuthHeader()).toEqual({ Authorization: `Bearer ${token}` })
    })
  })

  describe('Sesión no recuperable y casos negativos', () => {
    it('maneja 401 AUTH_INVALID_CREDENTIALS dejando la sesión limpia', async () => {
      server.use(
        http.post('*/api/v1/auth/refresh', () => {
          return HttpResponse.json(
            {
              type: 'about:blank',
              title: 'No autorizado',
              status: 401,
              detail: 'Credenciales inválidas.',
              code: 'AUTH_INVALID_CREDENTIALS',
            },
            { status: 401 },
          )
        }),
      )

      const session = useSessionStore()
      const recovered = await restoreSession()

      expect(recovered).toBe(false)
      expect(session.isAuthenticated).toBe(false)
      expect(session.role).toBeNull()
      expect(session.fullName).toBeNull()
      expect(getAuthHeader()).toEqual({})
    })

    it('maneja 401 AUTH_TOKEN_EXPIRED dejando la sesión limpia', async () => {
      server.use(
        http.post('*/api/v1/auth/refresh', () => {
          return HttpResponse.json(
            {
              type: 'about:blank',
              title: 'Token expirado',
              status: 401,
              detail: 'El token ha expirado.',
              code: 'AUTH_TOKEN_EXPIRED',
            },
            { status: 401 },
          )
        }),
      )

      const session = useSessionStore()
      const recovered = await restoreSession()

      expect(recovered).toBe(false)
      expect(session.isAuthenticated).toBe(false)
      expect(getAuthHeader()).toEqual({})
    })

    it('maneja fallos de red sin lanzar excepciones no controladas', async () => {
      server.use(
        http.post('*/api/v1/auth/refresh', () => {
          return HttpResponse.error()
        }),
      )

      const session = useSessionStore()
      const recovered = await restoreSession()

      expect(recovered).toBe(false)
      expect(session.isAuthenticated).toBe(false)
      expect(getAuthHeader()).toEqual({})
    })

    it('descarta la sesión si el token no contiene un rol válido', async () => {
      const token = createFakeJwt({
        sub: 'user-uuid',
        role: 'rol_inexistente',
      })

      server.use(
        http.post('*/api/v1/auth/refresh', () => {
          return HttpResponse.json({
            access_token: token,
            token_type: 'Bearer',
            expires_in: 600,
          })
        }),
      )

      const session = useSessionStore()
      const recovered = await restoreSession()

      expect(recovered).toBe(false)
      expect(session.isAuthenticated).toBe(false)
      expect(getAuthHeader()).toEqual({})
    })
  })

  describe('Control de concurrencia y duplicaciones', () => {
    it('no duplica llamadas al endpoint si se ejecutan refrescos simultáneos', async () => {
      let callCount = 0
      const token = createFakeJwt({ role: 'student', full_name: 'Ana Pérez' })

      server.use(
        http.post('*/api/v1/auth/refresh', () => {
          callCount++
          return HttpResponse.json({
            access_token: token,
            token_type: 'Bearer',
            expires_in: 600,
          })
        }),
      )

      const [res1, res2, res3] = await Promise.all([
        restoreSession(),
        restoreSession(),
        restoreSession(),
      ])

      expect(res1).toBe(true)
      expect(res2).toBe(true)
      expect(res3).toBe(true)
      expect(callCount).toBe(1)
    })

    it('no realiza petición de refresh si el usuario ya está autenticado', async () => {
      let callCount = 0
      server.use(
        http.post('*/api/v1/auth/refresh', () => {
          callCount++
          return HttpResponse.json({})
        }),
      )

      const session = useSessionStore()
      session.setUser('Usuario Existente', 'student')

      const recovered = await restoreSession()

      expect(recovered).toBe(true)
      expect(callCount).toBe(0)
    })
  })

  describe('refresh directo', () => {
    it('refresh() realiza la petición POST /auth/refresh y devuelve los datos', async () => {
      server.use(
        http.post('*/api/v1/auth/refresh', () => {
          return HttpResponse.json({
            access_token: 'nuevo-token',
            token_type: 'Bearer',
            expires_in: 600,
          })
        }),
      )

      const data = await refresh()
      expect(data.access_token).toBe('nuevo-token')
      expect(data.token_type).toBe('Bearer')
      expect(data.expires_in).toBe(600)
    })
  })
})
