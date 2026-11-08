
import createClient from 'openapi-fetch'
import type { paths } from './schema'
import { ApiError, normalizeApiError } from '../errors/problem-details'

/**
 * Cliente HTTP tipado.
 * El access token permanece exclusivamente en memoria.
 */
const API_BASE_URL = (
  import.meta.env.VITE_API_URL || 'http://localhost:8000'
).replace(/\/+$/, '')

const REFRESH_URL = `${API_BASE_URL}/api/v1/auth/refresh`
const REFRESH_LOCK_NAME = 'internet-cafe-auth-refresh'

let accessToken: string | null = null
let authStateVersion = 0
let refreshInFlight: Promise<string> | null = null

let authFailureHandler: (() => void) | null = null
let authFailureHandled = false

/**
 * Guarda el access token únicamente en memoria.
 */
export function setAccessToken(token: string | null): void {
  accessToken = token
  authStateVersion++

  if (token !== null) {
    authFailureHandled = false
  }
}

/**
 * Elimina el access token de memoria.
 */
export function clearAccessToken(): void {
  accessToken = null
  authStateVersion++
}

/**
 * Devuelve la cabecera Authorization.
 */
export function getAuthHeader(): Record<string, string> {
  return accessToken
    ? { Authorization: `Bearer ${accessToken}` }
    : {}
}

/**
 * Registra la función que cerrará la sesión cuando
 * el refresh token deje de ser válido.
 */
export function setAuthFailureHandler(
  handler: (() => void) | null,
): void {
  authFailureHandler = handler
  authFailureHandled = false
}

/**
 * Notifica un fallo definitivo de autenticación.
 * Los errores de red y del servidor no cierran la sesión.
 */
function notifyAuthFailure(error: unknown): void {
  if (!(error instanceof ApiError)) {
    return
  }

  const invalidCredentials =
    error.status === 401 &&
    ['AUTH_TOKEN_EXPIRED', 'AUTH_INVALID_CREDENTIALS'].includes(error.code)

  if (!invalidCredentials || !authFailureHandler || authFailureHandled) {
    return
  }

  authFailureHandled = true
  authFailureHandler()
}

/**
 * Extrae el token Bearer enviado en una petición.
 */
function getBearerToken(request: Request): string | null {
  const authorization = request.headers.get('Authorization')

  if (!authorization?.startsWith('Bearer ')) {
    return null
  }

  return authorization.slice(7)
}

/**
 * Comprueba si el error corresponde específicamente
 * a la expiración del access token.
 */
async function isAccessTokenExpired(
  response: Response,
): Promise<boolean> {
  if (response.status !== 401) {
    return false
  }

  let data: unknown

  try {
    data = await response.clone().json()
  } catch {
    return false
  }

  return (
    typeof data === 'object' &&
    data !== null &&
    'code' in data &&
    data.code === 'AUTH_TOKEN_EXPIRED'
  )
}

/**
 * Normaliza una respuesta de error HTTP utilizando RFC 9457.
 */
async function getResponseApiError(
  response: Response,
): Promise<ApiError> {
  let data: unknown

  try {
    data = await response.clone().json()
  } catch {
    data = null
  }

  return normalizeApiError(response.status, data)
}

/**
 * Ejecuta una renovación utilizando la cookie HttpOnly.
 * JavaScript nunca lee directamente esa cookie.
 */
async function requestNewAccessToken(): Promise<string> {
  const response = await globalThis.fetch(REFRESH_URL, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Accept: 'application/json, application/problem+json',
    },
  })

  let data: unknown

  try {
    data = await response.json()
  } catch {
    data = null
  }

  if (!response.ok) {
    throw normalizeApiError(response.status, data)
  }

  if (
    typeof data !== 'object' ||
    data === null ||
    !('access_token' in data) ||
    typeof data.access_token !== 'string' ||
    !data.access_token
  ) {
    throw normalizeApiError(502, {
      type: 'about:blank',
      title: 'Respuesta inválida',
      status: 502,
      detail: 'El servidor no devolvió un access token válido.',
      code: 'AUTH_REFRESH_INVALID_RESPONSE',
    })
  }

  return data.access_token
}

/**
 * Ejecuta una operación bajo un bloqueo exclusivo.
 *
 * Si Web Locks no está disponible, ejecuta la operación
 * sin bloqueo. En ese caso no se garantiza la coordinación
 * entre pestañas.
 */
function withRefreshLock<T>(
  callback: () => Promise<T>,
): Promise<T> {
  if (typeof navigator === 'undefined' || !navigator.locks) {
    return callback()
  }

  return navigator.locks.request(
    REFRESH_LOCK_NAME,
    { mode: 'exclusive' },
    callback,
  )
}

/**
 * Genera un error cuando la sesión cambia durante la renovación.
 */
function createRefreshCancelledError(): Error {
  return normalizeApiError(401, {
    type: 'about:blank',
    title: 'Sesión modificada',
    status: 401,
    detail: 'La sesión cambió mientras se renovaba el token.',
    code: 'AUTH_REFRESH_CANCELLED',
  })
}

/**
 * Renueva el access token.
 *
 * refreshInFlight evita renovaciones simultáneas dentro
 * de una misma pestaña.
 *
 * Web Locks coordina las renovaciones entre pestañas.
 */
export function refreshAccessToken(): Promise<string> {
  if (refreshInFlight) {
    return refreshInFlight
  }

  const versionAtStart = authStateVersion

  const operation = withRefreshLock(async () => {
    // Comprueba si la sesión cambió mientras esperaba el bloqueo.
    if (versionAtStart !== authStateVersion) {
      if (accessToken) {
        return accessToken
      }

      throw createRefreshCancelledError()
    }

    const newToken = await requestNewAccessToken()

    // Evita recuperar un token después de cerrar la sesión.
    if (versionAtStart !== authStateVersion) {
      if (accessToken) {
        return accessToken
      }

      throw createRefreshCancelledError()
    }

    setAccessToken(newToken)

    return newToken
  })

  const sharedOperation = operation.finally(() => {
    if (refreshInFlight === sharedOperation) {
      refreshInFlight = null
    }
  })

  refreshInFlight = sharedOperation

  return sharedOperation
}

/**
 * Cliente fetch que renueva y reintenta una petición
 * cuando recibe AUTH_TOKEN_EXPIRED.
 *
 * La petición original solamente se reintenta una vez.
 */
async function fetchWithTokenRefresh(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const request = new Request(input, init)
  const requestToRetry = request.clone()
  const tokenSent = getBearerToken(request)

  const response = await globalThis.fetch(request)

  if (!tokenSent || !(await isAccessTokenExpired(response))) {
    return response
  }

  // Si se cerró la sesión, no intentamos recuperarla.
  if (!accessToken) {
    return response
  }

  const currentToken = accessToken

  let tokenToUse: string

  try {
    // Puede existir un token nuevo por otra petición de esta pestaña.
    tokenToUse =
      currentToken !== tokenSent
        ? currentToken
        : await refreshAccessToken()
  } catch (error) {
    notifyAuthFailure(error)
    throw error
  }

  const headers = new Headers(requestToRetry.headers)
  headers.set('Authorization', `Bearer ${tokenToUse}`)

  const retryRequest = new Request(requestToRetry, { headers })
  const retryResponse = await globalThis.fetch(retryRequest)

  // Si el token renovado también es rechazado,
  // se comprueba si corresponde a un fallo definitivo.
  if (retryResponse.status === 401) {
    const retryError = await getResponseApiError(retryResponse)
    notifyAuthFailure(retryError)
  }

  return retryResponse
}

/**
 * Cliente HTTP generado a partir del contrato OpenAPI.
 */
export const api = createClient<paths>({
  baseUrl: API_BASE_URL,
  fetch: fetchWithTokenRefresh,
  headers: {
    Accept: 'application/json, application/problem+json',
  },
})

// Agrega automáticamente el token desde memoria.
api.use({
  onRequest({ request }) {
    if (accessToken) {
      request.headers.set('Authorization', `Bearer ${accessToken}`)
    }

    return request
  },
})

// Normaliza los errores HTTP utilizando RFC 9457.
api.use({
  async onResponse({ response }) {
    if (!response.ok) {
      throw await getResponseApiError(response)
    }

    return response
  },
})
