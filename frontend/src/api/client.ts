import createClient from 'openapi-fetch'
import type { paths } from './schema'
import { normalizeApiError } from '../errors/problem-details'

/**
 * Cliente HTTP tipado a partir del contrato OpenAPI.
 * El access token se mantiene únicamente en memoria.
 */
let accessToken: string | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function clearAccessToken(): void {
  accessToken = null
}

export function getAuthHeader(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {}
}

/**
 * Cliente HTTP generado a partir del contrato OpenAPI.
 */
export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  fetch: (...args) => globalThis.fetch(...args),
  headers: {
    Accept: 'application/json, application/problem+json',
  },
})

// Agrega el token automáticamente a las solicitudes.
api.use({
  onRequest({ request }) {
    if (accessToken) {
      request.headers.set('Authorization', `Bearer ${accessToken}`)
    }

    return request
  },
})

api.use({
  async onResponse({ response }) {
    if (!response.ok) {
      let data: unknown

      try {
        data = await response.clone().json()
      } catch {
        data = null
      }

      throw normalizeApiError(response.status, data)
    }

    return response
  },
})
