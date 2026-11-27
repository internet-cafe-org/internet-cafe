import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  requestPasswordReset,
  resendCode,
  resetPassword,
  verifyEmail,
} from '../services/auth'

function stubFetch(status: number, body?: unknown) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(body === undefined ? null : JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastCall(fetchMock: ReturnType<typeof stubFetch>) {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
  return { url, method: init.method, body: JSON.parse(String(init.body)) }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('llamadas de verificación y recuperación (ST-SEC-01)', () => {
  it('verifyEmail envía el correo y el código', async () => {
    const fetchMock = stubFetch(204)
    await verifyEmail('ana@universidad.example', '123456')
    expect(lastCall(fetchMock)).toEqual({
      url: '/api/v1/auth/verify-email',
      method: 'POST',
      body: { email: 'ana@universidad.example', code: '123456' },
    })
  })

  it('resendCode pide otro código', async () => {
    const fetchMock = stubFetch(202)
    await resendCode('ana@universidad.example')
    expect(lastCall(fetchMock)).toEqual({
      url: '/api/v1/auth/resend-code',
      method: 'POST',
      body: { email: 'ana@universidad.example' },
    })
  })

  it('requestPasswordReset pide el código de recuperación', async () => {
    const fetchMock = stubFetch(202)
    await requestPasswordReset('ana@universidad.example')
    expect(lastCall(fetchMock)).toEqual({
      url: '/api/v1/auth/password/forgot',
      method: 'POST',
      body: { email: 'ana@universidad.example' },
    })
  })

  it('resetPassword envía el código y la contraseña nueva', async () => {
    const fetchMock = stubFetch(204)
    await resetPassword('ana@universidad.example', '654321', 'una-contraseña-larga')
    expect(lastCall(fetchMock)).toEqual({
      url: '/api/v1/auth/password/reset',
      method: 'POST',
      body: {
        email: 'ana@universidad.example',
        code: '654321',
        new_password: 'una-contraseña-larga',
      },
    })
  })

  it('un error de la API llega como ApiError con su estado y código', async () => {
    stubFetch(410, { code: 'OTP_EXPIRED' })
    await expect(verifyEmail('ana@universidad.example', '123456')).rejects.toMatchObject({
      status: 410,
      code: 'OTP_EXPIRED',
    })
    expect(ApiError).toBeDefined()
  })
})
