/**
 * Llamadas del flujo QR (UI-06). Contrato: SRS §10.3-10.5.
 * TODO: reemplazar por el cliente de src/api (#84) cuando #135 publique
 * /scan/preview y /scan/claim. Hoy usa fetch con el token en memoria.
 */
import { getAuthHeader } from '@/api/client'
import { ApiError } from '@/services/auth'

const API_BASE = '/api/v1'

export interface ScanMachine {
  code: string
  lab: string
  /** El SRS no define un nombre amigable; si el backend lo envía, se muestra. */
  name?: string
}

export interface ScanPreview {
  machine: ScanMachine
  expires_at: string
  active_session?: { machine_code: string } | null
}

export interface ScanClaim {
  session: {
    id: string
    status: string
    started_at: string
    machine: ScanMachine & { id: string }
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR')
  }

  const data = (await response.json().catch(() => null)) as { code?: string } | null
  if (!response.ok) throw new ApiError(response.status, data?.code ?? 'UNKNOWN')
  return data as T
}

/** Vista previa: no consume el QR (RF-QR-06). */
export function previewScan(token: string): Promise<ScanPreview> {
  return post<ScanPreview>('/scan/preview', { token })
}

/** Confirmación: crea la sesión de acceso (RF-QR-07). 201 o 200 si es idempotente. */
export function claimScan(token: string): Promise<ScanClaim> {
  return post<ScanClaim>('/scan/claim', { token })
}
