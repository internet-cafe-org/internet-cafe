import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'

import { clearAccessToken, setAccessToken, setAuthFailureHandler } from '../api/client'
import { ApiError } from '../errors/problem-details'
import { server } from '../mocks/server'
import {
  CURRENT_PASSWORD_INCORRECT,
  CURRENT_PASSWORD_INVALID_CODE,
  changeMyPassword,
  passwordChangeFailure,
} from '../services/password'

const URL = 'http://localhost:8000/api/v1/me/password'

const problem = (status: number, code: string, detail?: string) =>
  HttpResponse.json(
    { type: 'about:blank', title: 'Error', status, code, detail },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )

describe('changeMyPassword', () => {
  it('envía PATCH con el token en memoria y los dos campos del contrato; 204 no devuelve nada', async () => {
    setAccessToken('token-en-memoria')
    let seen: { method: string; auth: string | null; body: unknown } | undefined
    server.use(
      http.patch(URL, async ({ request }) => {
        seen = {
          method: request.method,
          auth: request.headers.get('Authorization'),
          body: await request.json(),
        }
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await expect(changeMyPassword('ActualClave-1', 'NuevaClave-2026')).resolves.toBeUndefined()

    expect(seen).toEqual({
      method: 'PATCH',
      auth: 'Bearer token-en-memoria',
      body: { current_password: 'ActualClave-1', new_password: 'NuevaClave-2026' },
    })
    clearAccessToken()
  })

  it('422 VALIDATION_ERROR: lanza ApiError con el detail y NO se confunde con una sesión vencida', async () => {
    server.use(http.patch(URL, () => problem(422, 'VALIDATION_ERROR', CURRENT_PASSWORD_INCORRECT)))

    const error = await changeMyPassword('mala', 'NuevaClave-2026').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: CURRENT_PASSWORD_INCORRECT,
    })
  })

  it('401 por contraseña actual incorrecta: lanza ApiError sin renovar el token ni cerrar la sesión', async () => {
    setAccessToken('token-en-memoria')
    const onAuthFailure = vi.fn()
    setAuthFailureHandler(onAuthFailure)
    let refreshCalls = 0
    server.use(
      http.patch(URL, () =>
        problem(401, CURRENT_PASSWORD_INVALID_CODE, CURRENT_PASSWORD_INCORRECT),
      ),
      http.post('http://localhost:8000/api/v1/auth/refresh', () => {
        refreshCalls += 1
        return problem(401, 'AUTH_TOKEN_EXPIRED')
      }),
    )

    const error = await changeMyPassword('mala', 'NuevaClave-2026').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 401, code: CURRENT_PASSWORD_INVALID_CODE })
    expect(refreshCalls).toBe(0)
    expect(onAuthFailure).not.toHaveBeenCalled()
    setAuthFailureHandler(null)
    clearAccessToken()
  })

  it('429 RATE_LIMITED: lanza ApiError', async () => {
    server.use(http.patch(URL, () => problem(429, 'RATE_LIMITED')))

    await expect(changeMyPassword('a', 'b')).rejects.toMatchObject({
      status: 429,
      code: 'RATE_LIMITED',
    })
  })
})

describe('passwordChangeFailure', () => {
  it('422 con "contraseña actual no es correcta": error del campo actual', () => {
    const error = new ApiError({
      status: 422,
      code: 'VALIDATION_ERROR',
      detail: CURRENT_PASSWORD_INCORRECT,
    })
    expect(passwordChangeFailure(error)).toEqual({
      field: 'actual',
      message: 'La contraseña actual no es correcta. Revísala e inténtalo de nuevo.',
    })
  })

  it('401 con el code propio: error del campo actual', () => {
    const error = new ApiError({
      status: 401,
      code: CURRENT_PASSWORD_INVALID_CODE,
      detail: CURRENT_PASSWORD_INCORRECT,
    })
    expect(passwordChangeFailure(error)).toEqual({
      field: 'actual',
      message: 'La contraseña actual no es correcta. Revísala e inténtalo de nuevo.',
    })
  })

  it('401 de token vencido u otro 401: mensaje general (lo resuelve el cliente)', () => {
    const error = new ApiError({
      status: 401,
      code: 'AUTH_TOKEN_EXPIRED',
      detail: 'Token vencido.',
    })
    expect(passwordChangeFailure(error)).toEqual({
      field: null,
      message: 'No pudimos cambiar la contraseña. Inténtalo de nuevo.',
    })
  })

  it('otro 422 (nueva fuera de rango o igual a la actual): error del formulario', () => {
    const error = new ApiError({
      status: 422,
      code: 'VALIDATION_ERROR',
      detail: 'La nueva contraseña debe ser distinta de la actual.',
    })
    const failure = passwordChangeFailure(error)
    expect(failure.field).toBeNull()
    expect(failure.message).toContain('entre 10 y 128 caracteres')
  })

  it('429: pide esperar', () => {
    const failure = passwordChangeFailure(new ApiError({ status: 429, code: 'RATE_LIMITED' }))
    expect(failure.field).toBeNull()
    expect(failure.message).toContain('Demasiados intentos')
  })

  it.each([
    ['otro ApiError', new ApiError({ status: 500, code: 'INTERNAL_ERROR' })],
    ['fallo de red', new TypeError('Failed to fetch')],
    ['valor desconocido', 'boom'],
  ])('%s: mensaje general', (_nombre, error) => {
    expect(passwordChangeFailure(error)).toEqual({
      field: null,
      message: 'No pudimos cambiar la contraseña. Inténtalo de nuevo.',
    })
  })
})
