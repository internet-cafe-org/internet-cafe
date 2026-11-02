/**
 * Llamadas de autenticación (UI-05).
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

async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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
