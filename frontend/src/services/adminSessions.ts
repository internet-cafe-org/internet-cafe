import { api, API_BASE_URL, fetchWithTokenRefresh, getAuthHeader } from '@/api/client'
import { normalizeApiError } from '@/errors/problem-details'
import type { components } from '@/api/schema'

export type AdminSession = components['schemas']['AdminSession']
export type AdminSessionsPage = components['schemas']['AdminSessionsPage']
export type SessionEndReason = components['schemas']['SessionEndReason']
export type LabItem = components['schemas']['Lab']

export interface AdminSessionsQuery {
  machine_code?: string
  lab_id?: string
  state?: 'active' | 'ended'
  started_from?: string
  started_to?: string
  limit?: number
  offset?: number
}

/**
 * Consulta la lista paginada de accesos con filtros según contrato v0.2.1 (RF-ADM-05).
 */
export async function getAdminSessions(query?: AdminSessionsQuery): Promise<AdminSessionsPage> {
  const { data } = await api.GET('/api/v1/admin/sessions', {
    params: {
      query: {
        machine_code: query?.machine_code || undefined,
        lab_id: query?.lab_id || undefined,
        state: query?.state || undefined,
        started_from: query?.started_from || undefined,
        started_to: query?.started_to || undefined,
        limit: query?.limit ?? 20,
        offset: query?.offset ?? 0,
      },
    },
  })

  if (!data) {
    throw new Error('No se recibieron datos de sesiones.')
  }

  return data
}

/**
 * Forzar el cierre de una sesión activa (RF-ADM-07, RF-SES-08).
 * Cierra con motivo `admin_forced`. Idempotente.
 */
export async function forceEndSession(sessionId: string): Promise<AdminSession> {
  const { data } = await api.POST('/api/v1/admin/sessions/{id}/end', {
    params: {
      path: {
        id: sessionId,
      },
    },
  })

  if (!data?.session) {
    throw new Error('No se recibió la información de la sesión cerrada.')
  }

  return data.session
}

/**
 * Obtiene el listado de salas para alimentar el filtro de selección.
 */
export async function getAdminLabs(): Promise<LabItem[]> {
  const { data } = await api.GET('/api/v1/admin/labs', {
    params: {
      query: {
        limit: 100,
        offset: 0,
      },
    },
  })

  return data?.items ?? []
}

export interface AdminSessionsExportQuery {
  machine_code?: string
  lab_id?: string
  state?: 'active' | 'ended'
  started_from?: string
  started_to?: string
  student?: string
}

export interface ExportSessionsResult {
  blob: Blob
  filename: string
  truncated: boolean
}

/**
 * Construye la URL completa con parámetros de búsqueda para la exportación CSV.
 */
export function buildExportSessionsUrl(query?: AdminSessionsExportQuery): string {
  const params = new URLSearchParams()
  if (query?.machine_code?.trim()) {
    params.set('machine_code', query.machine_code.trim())
  }
  if (query?.lab_id?.trim()) {
    params.set('lab_id', query.lab_id.trim())
  }
  if (query?.state) {
    params.set('state', query.state)
  }
  if (query?.started_from?.trim()) {
    params.set('started_from', query.started_from.trim())
  }
  if (query?.started_to?.trim()) {
    params.set('started_to', query.started_to.trim())
  }
  if (query?.student?.trim()) {
    params.set('student', query.student.trim())
  }

  const queryString = params.toString()
  const base = `${API_BASE_URL}/api/v1/admin/sessions/export`
  return queryString ? `${base}?${queryString}` : base
}

/**
 * Exporta el historial de accesos filtrados a un archivo CSV en formato Blob (HU-33 / ST-UI-05).
 * Envía credenciales y cabecera Bearer, comprueba el estado HTTP y gestiona errores RFC 9457.
 */
export async function exportAdminSessionsCsv(
  query?: AdminSessionsExportQuery,
): Promise<ExportSessionsResult> {
  const url = buildExportSessionsUrl(query)
  const headers = new Headers({
    Accept: 'text/csv, application/problem+json',
    ...getAuthHeader(),
  })

  const response = await fetchWithTokenRefresh(url, {
    method: 'GET',
    headers,
    credentials: 'include',
  })

  if (!response.ok) {
    let errorData: unknown = null
    try {
      errorData = await response.json()
    } catch {
      // Si el cuerpo de respuesta no es JSON
    }
    throw normalizeApiError(response.status, errorData)
  }

  const blob = await response.blob()

  // Extraer nombre de archivo de la cabecera Content-Disposition si existe
  let filename = 'accesos.csv'
  const disposition = response.headers.get('Content-Disposition')
  if (disposition) {
    const filenameMatch = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i)
    if (filenameMatch && filenameMatch[1]) {
      filename = decodeURIComponent(filenameMatch[1].trim())
    }
  }

  const truncated = response.headers.get('X-Export-Truncated') === 'true'

  return { blob, filename, truncated }
}

/**
 * Inicia la descarga en el navegador a partir de un Blob y libera la URL temporal.
 */
export function downloadBlob(blob: Blob, filename = 'accesos.csv'): void {
  const url = window.URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  } finally {
    window.URL.revokeObjectURL(url)
  }
}
