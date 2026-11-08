import { afterEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'

import {
  api,
  clearAccessToken,
  getAuthHeader,
  setAccessToken,
  setAuthFailureHandler,
} from '../api/client'
import { server } from '../mocks/server'

const API_URL = 'http://localhost:8000'

afterEach(() => {
  clearAccessToken()
  setAuthFailureHandler(null)
})

describe('Integración del cliente API con MSW', () => {
  it('crea correctamente un desafío para una máquina', async () => {
    const { data, error } = await api.POST('/api/v1/machine/challenges', {
      params: {
        header: {
          'x-machine-code': 'TEST-MACHINE-001',
        },
      },
    })

    expect(error).toBeUndefined()
    expect(data).toBeDefined()
    expect(data?.challenge_id).toBe('123e4567-e89b-12d3-a456-426614174000')
    expect(data?.rotate_after_s).toBe(30)
  })

  it('devuelve 404 cuando no hay equipos registrados en la simulación', async () => {
    await expect(
      api.POST('/api/v1/scan/preview', {
        body: {
          token: 'demo-token',
        },
      }),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      code: 'CHALLENGE_NOT_FOUND',
    })
  })

  it('convierte un error 401 en ApiError', async () => {
    await expect(
      api.POST('/api/v1/machine/challenges', {
        params: {
          header: {
            'x-machine-code': 'INVALID',
          },
        },
      }),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
      code: 'MACHINE_SIGNATURE_INVALID',
    })
  })

  it('convierte un error 403 en ApiError', async () => {
    await expect(
      api.POST('/api/v1/machine/challenges', {
        params: {
          header: {
            'x-machine-code': 'DISABLED',
          },
        },
      }),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 403,
      code: 'MACHINE_DISABLED',
    })
  })

  it('convierte un error 404 en ApiError', async () => {
    await expect(
      api.POST('/api/v1/scan/preview', {
        body: {
          token: 'NOT_FOUND',
        },
      }),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      code: 'CHALLENGE_NOT_FOUND',
    })
  })

  it('convierte un error 410 en ApiError', async () => {
    await expect(
      api.POST('/api/v1/scan/preview', {
        body: {
          token: 'EXPIRED',
        },
      }),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 410,
      code: 'CHALLENGE_EXPIRED',
    })
  })

  it('convierte un error 409 en ApiError', async () => {
    await expect(
      api.POST('/api/v1/scan/preview', {
        body: {
          token: 'USED',
        },
      }),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      code: 'CHALLENGE_ALREADY_USED',
    })
  })

  it('agrega el token de autorización desde memoria', async () => {
    setAccessToken('token-prueba')

    const { data } = await api.POST('/api/v1/machine/challenges', {
      params: {
        header: {
          'x-machine-code': 'TEST-MACHINE-001',
        },
      },
    })

    expect(data?.challenge_id).toBe('123e4567-e89b-12d3-a456-426614174000')
  })

  it('al limpiar el token las peticiones posteriores no envían Authorization', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')

    try {
      setAccessToken('token-temporal')

      await api.POST('/api/v1/machine/challenges', {
        params: {
          header: {
            'x-machine-code': 'TEST-MACHINE-001',
          },
        },
      })

      const authenticatedCall =
        fetchSpy.mock.calls[fetchSpy.mock.calls.length - 1]

      const authenticatedRequest =
        authenticatedCall?.[0] instanceof Request
          ? authenticatedCall[0]
          : new Request(
              authenticatedCall?.[0] as string,
              authenticatedCall?.[1],
            )

      expect(authenticatedRequest.headers.get('Authorization')).toBe(
        'Bearer token-temporal',
      )

      clearAccessToken()

      await api.POST('/api/v1/machine/challenges', {
        params: {
          header: {
            'x-machine-code': 'TEST-MACHINE-001',
          },
        },
      })

      const unauthenticatedCall =
        fetchSpy.mock.calls[fetchSpy.mock.calls.length - 1]

      const unauthenticatedRequest =
        unauthenticatedCall?.[0] instanceof Request
          ? unauthenticatedCall[0]
          : new Request(
              unauthenticatedCall?.[0] as string,
              unauthenticatedCall?.[1],
            )

      expect(unauthenticatedRequest.headers.get('Authorization')).toBeNull()
    } finally {
      fetchSpy.mockRestore()
    }
  })
})

// ============================================================
// UTILIDADES PARA LAS PRUEBAS DE RENOVACIÓN
// ============================================================

function expiredTokenResponse() {
  return HttpResponse.json(
    {
      type: 'about:blank',
      title: 'Token vencido',
      status: 401,
      detail: 'El token de acceso venció.',
      code: 'AUTH_TOKEN_EXPIRED',
    },
    {
      status: 401,
      headers: {
        'Content-Type': 'application/problem+json',
      },
    },
  )
}

function successfulChallengeResponse() {
  return HttpResponse.json(
    {
      challenge_id: '123e4567-e89b-12d3-a456-426614174000',
      qr_url: 'http://localhost:5173/scan?token=demo-token',
      expires_at: '2026-10-29T18:00:00Z',
      rotate_after_s: 30,
    },
    { status: 201 },
  )
}

function createChallenge() {
  return api.POST('/api/v1/machine/challenges', {
    params: {
      header: {
        'x-machine-code': 'TEST-MACHINE-001',
      },
    },
  })
}

// ============================================================
// RENOVACIÓN AUTOMÁTICA DEL ACCESS TOKEN
// ============================================================

describe('Renovación automática del access token', () => {
  it('renueva el token y reintenta la petición', async () => {
    let refreshCalls = 0
    let protectedCalls = 0
    let refreshCredentials = ''

    server.use(
      http.post(`${API_URL}/api/v1/auth/refresh`, ({ request }) => {
        refreshCalls++
        refreshCredentials = request.credentials

        return HttpResponse.json({
          access_token: 'token-renovado',
          token_type: 'bearer',
          expires_in: 600,
        })
      }),

      http.post(
        `${API_URL}/api/v1/machine/challenges`,
        ({ request }) => {
          protectedCalls++

          const authorization = request.headers.get('Authorization')

          if (authorization === 'Bearer token-vencido') {
            return expiredTokenResponse()
          }

          return successfulChallengeResponse()
        },
      ),
    )

    setAccessToken('token-vencido')

    const { data, error } = await createChallenge()

    expect(error).toBeUndefined()
    expect(data?.challenge_id).toBe(
      '123e4567-e89b-12d3-a456-426614174000',
    )

    expect(refreshCalls).toBe(1)
    expect(protectedCalls).toBe(2)
    expect(refreshCredentials).toBe('include')
  })

  it('comparte una renovación entre varias peticiones simultáneas', async () => {
    let refreshCalls = 0
    let protectedCalls = 0

    server.use(
      http.post(`${API_URL}/api/v1/auth/refresh`, async () => {
        refreshCalls++

        await new Promise((resolve) => setTimeout(resolve, 30))

        return HttpResponse.json({
          access_token: 'token-renovado',
          token_type: 'bearer',
          expires_in: 600,
        })
      }),

      http.post(
        `${API_URL}/api/v1/machine/challenges`,
        ({ request }) => {
          protectedCalls++

          if (
            request.headers.get('Authorization') ===
            'Bearer token-vencido'
          ) {
            return expiredTokenResponse()
          }

          return successfulChallengeResponse()
        },
      ),
    )

    setAccessToken('token-vencido')

    const [first, second] = await Promise.all([
      createChallenge(),
      createChallenge(),
    ])

    expect(first.error).toBeUndefined()
    expect(second.error).toBeUndefined()

    expect(protectedCalls).toBe(4)
    expect(refreshCalls).toBe(1)
  })

  it('utiliza Web Locks para coordinar la renovación', async () => {
    const previousLocks = Object.getOwnPropertyDescriptor(
      navigator,
      'locks',
    )

    const lockRequest = vi.fn(
      async (
        _name: string,
        _options: { mode: 'exclusive' },
        callback: () => Promise<string>,
      ) => callback(),
    )

    Object.defineProperty(navigator, 'locks', {
      configurable: true,
      value: {
        request: lockRequest,
      } as unknown as LockManager,
    })

    try {
      server.use(
        http.post(`${API_URL}/api/v1/auth/refresh`, () => {
          return HttpResponse.json({
            access_token: 'token-renovado',
            token_type: 'bearer',
            expires_in: 600,
          })
        }),

        http.post(
          `${API_URL}/api/v1/machine/challenges`,
          ({ request }) => {
            if (
              request.headers.get('Authorization') ===
              'Bearer token-vencido'
            ) {
              return expiredTokenResponse()
            }

            return successfulChallengeResponse()
          },
        ),
      )

      setAccessToken('token-vencido')

      await createChallenge()

      expect(lockRequest).toHaveBeenCalledTimes(1)

      expect(lockRequest).toHaveBeenCalledWith(
        'internet-cafe-auth-refresh',
        { mode: 'exclusive' },
        expect.any(Function),
      )
    } finally {
      if (previousLocks) {
        Object.defineProperty(navigator, 'locks', previousLocks)
      } else {
        Reflect.deleteProperty(navigator, 'locks')
      }
    }
  })
})

// ============================================================
// CIERRE DE SESIÓN CUANDO FALLA LA RENOVACIÓN
// ============================================================

describe('Fallos de renovación de sesión', () => {
  it('cierra la sesión cuando el refresh token es inválido', async () => {
    const onAuthFailure = vi.fn(() => clearAccessToken())

    setAuthFailureHandler(onAuthFailure)

    server.use(
      http.post(`${API_URL}/api/v1/auth/refresh`, () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Credenciales inválidas',
            status: 401,
            detail: 'La sesión ya no es válida.',
            code: 'AUTH_INVALID_CREDENTIALS',
          },
          {
            status: 401,
            headers: {
              'Content-Type': 'application/problem+json',
            },
          },
        ),
      ),

      http.post(`${API_URL}/api/v1/machine/challenges`, () =>
        expiredTokenResponse(),
      ),
    )

    setAccessToken('token-vencido')

    await expect(createChallenge()).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
      code: 'AUTH_INVALID_CREDENTIALS',
    })

    expect(onAuthFailure).toHaveBeenCalledTimes(1)
    expect(getAuthHeader()).toEqual({})
  })

  it('no cierra la sesión cuando el servidor devuelve error 500', async () => {
    const onAuthFailure = vi.fn()

    setAuthFailureHandler(onAuthFailure)

    server.use(
      http.post(`${API_URL}/api/v1/auth/refresh`, () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Error interno',
            status: 500,
            detail: 'Error temporal del servidor.',
            code: 'INTERNAL_SERVER_ERROR',
          },
          {
            status: 500,
            headers: {
              'Content-Type': 'application/problem+json',
            },
          },
        ),
      ),

      http.post(`${API_URL}/api/v1/machine/challenges`, () =>
        expiredTokenResponse(),
      ),
    )

    setAccessToken('token-vencido')

    await expect(createChallenge()).rejects.toMatchObject({
      name: 'ApiError',
      status: 500,
      code: 'INTERNAL_SERVER_ERROR',
    })

    expect(onAuthFailure).not.toHaveBeenCalled()

    expect(getAuthHeader()).toEqual({
      Authorization: 'Bearer token-vencido',
    })
  })
})