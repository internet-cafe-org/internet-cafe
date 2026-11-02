import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, clearAccessToken, setAccessToken } from '../api/client'

afterEach(() => {
  clearAccessToken()
})

describe('Integración del cliente API con MSW', () => {
  it('crea correctamente un desafío para una máquina', async () => {
    const { data, error } = await api.POST('/api/v1/machine/challenges', {
      params: {
        header: {
          'x-machine-code': 'PC-001',
        },
      },
    })

    expect(error).toBeUndefined()
    expect(data).toBeDefined()
    expect(data?.challenge_id).toBe('123e4567-e89b-12d3-a456-426614174000')
    expect(data?.rotate_after_s).toBe(30)
  })

  it('consulta correctamente la información de un escaneo', async () => {
    const { data, error } = await api.POST('/api/v1/scan/preview', {
      body: {
        token: 'demo-token',
      },
    })

    expect(error).toBeUndefined()
    expect(data?.machine.code).toBe('PC-001')
    expect(data?.machine.lab).toBe('Laboratorio 1')
    expect(data?.active_session).toBeNull()
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
          'x-machine-code': 'PC-001',
        },
      },
    })

    expect(data?.challenge_id).toBe('123e4567-e89b-12d3-a456-426614174000')
  })

  it('al limpiar el token con clearAccessToken() las peticiones posteriores no envían Authorization', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')

    try {
      setAccessToken('token-temporal')
      await api.POST('/api/v1/machine/challenges', {
        params: {
          header: {
            'x-machine-code': 'PC-001',
          },
        },
      })

      const authenticatedCall = fetchSpy.mock.calls[fetchSpy.mock.calls.length - 1]
      const authenticatedRequest =
        authenticatedCall?.[0] instanceof Request
          ? authenticatedCall[0]
          : new Request(authenticatedCall?.[0] as string, authenticatedCall?.[1])
      expect(authenticatedRequest.headers.get('Authorization')).toBe('Bearer token-temporal')

      clearAccessToken()

      await api.POST('/api/v1/machine/challenges', {
        params: {
          header: {
            'x-machine-code': 'PC-001',
          },
        },
      })

      const unauthenticatedCall = fetchSpy.mock.calls[fetchSpy.mock.calls.length - 1]
      const unauthenticatedRequest =
        unauthenticatedCall?.[0] instanceof Request
          ? unauthenticatedCall[0]
          : new Request(unauthenticatedCall?.[0] as string, unauthenticatedCall?.[1])
      expect(unauthenticatedRequest.headers.get('Authorization')).toBeNull()
    } finally {
      fetchSpy.mockRestore()
    }
  })
})
