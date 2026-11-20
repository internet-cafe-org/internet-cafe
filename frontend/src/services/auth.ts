import { getActivePinia } from 'pinia'

import { setAccessToken } from '@/api/client'
import { useSessionStore } from '@/stores/session'

/**
 * Llamadas de autenticación (UI-05, HU-31 / UI-04c).
 * TODO: reemplazar `post` por el cliente openapi-fetch de UI-04a (#84).
 * Rutas del SRS §10.3, relativas al mismo origen (rewrite /api/* de Vercel).
 */
const API_BASE = '/api/v1'

export type Role = 'student' | 'admin'

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: { id: string; full_name: string; role: Role }
}

export interface RefreshResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface RegisterPayload {
  email: string
  student_code: string
  full_name: string
  password: string
  privacy_consent: boolean
}

/** Error de la API (RFC 9457) o de red (status 0). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string) {
    super(code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: 'same-origin',
    })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR')
  }

  const data = (await response.json().catch(() => null)) as { code?: string } | null
  if (!response.ok) throw new ApiError(response.status, data?.code ?? 'UNKNOWN')
  return data as T
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return post<LoginResponse>('/auth/login', { email, password })
}

export function register(payload: RegisterPayload): Promise<void> {
  return post<void>('/auth/register', payload)
}

/**
 * Rota el refresh token y devuelve un access token nuevo (SEC-03a).
 * La cookie HttpOnly __Secure-rt se envía automáticamente por el navegador.
 */
export function refresh(): Promise<RefreshResponse> {
  return post<RefreshResponse>('/auth/refresh')
}

export interface JwtPayload {
  sub?: string
  role?: Role
  full_name?: string
  [key: string]: unknown
}

/**
 * Extrae de forma segura el payload del access token (JWT ES256).
 * No expone datos sensibles ni realiza comprobaciones criptográficas en cliente.
 */
export function decodeJwtPayload(token: string): JwtPayload | null {
  try {
    const parts = token.split('.')
    if (parts.length < 2 || !parts[1]) return null
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
    const binary = atob(padded)
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0))
    const json = new TextDecoder().decode(bytes)
    return JSON.parse(json) as JwtPayload
  } catch {
    return null
  }
}

let activeRefreshPromise: Promise<boolean> | null = null

/**
 * Recupera la sesión al arrancar o recargar la aplicación (HU-31 / UI-04c).
 * Invoca /auth/refresh con la cookie __Secure-rt.
 * Coordina llamadas concurrentes para evitar duplicaciones y actualiza
 * el access token en memoria privada y el store de sesión de Pinia.
 */
export async function restoreSession(): Promise<boolean> {
  if (activeRefreshPromise) {
    return activeRefreshPromise
  }

  if (!getActivePinia()) {
    return false
  }

  const session = useSessionStore()
  if (session.isAuthenticated) {
    return true
  }

  activeRefreshPromise = (async () => {
    try {
      const data = await refresh()
      setAccessToken(data.access_token)
      const payload = decodeJwtPayload(data.access_token)
      const role = payload?.role
      if (role === 'student' || role === 'admin') {
        const name = typeof payload?.full_name === 'string' ? payload.full_name : ''
        session.setUser(name, role)
        return true
      }
      session.clear()
      return false
    } catch {
      session.clear()
      return false
    } finally {
      activeRefreshPromise = null
    }
  })()

  return activeRefreshPromise
}
