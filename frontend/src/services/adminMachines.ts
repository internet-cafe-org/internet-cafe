/**
 * Código de enrolamiento y revocación de clave de un equipo (UI-11, RF-ADM-02).
 *
 * TODO: reemplazar por llamadas tipadas a `api` cuando BE-13 (#130) publique estos
 * endpoints en Backend/openapi.yaml y se regenere src/api/schema.d.ts (`npm run gen:api`).
 * Las rutas son una PROPUESTA: confírmalas con quien tiene BE-13.
 *
 * Se usa el mismo cliente `api` (con refresh de token y normalización de errores RFC 9457),
 * por eso los fallos llegan como ApiError y no hace falta revisar `error` aquí.
 */
import { api } from '@/api/client'
import { normalizeApiError } from '@/errors/problem-details'

export interface EnrollmentCode {
  /** Código de un solo uso. Solo se recibe en esta respuesta. */
  code: string
  /** Vence a las 24 h de generarse (contrato.md). */
  expires_at: string
}

// Los paths aún no existen en `paths`, así que se tipa solo lo que se usa.
type PostInit = { params: { path: { id: string } } }
type LooseClient = { POST: (url: string, init: PostInit) => Promise<{ data?: unknown }> }

const client = api as unknown as LooseClient

export async function createEnrollmentCode(machineId: string): Promise<EnrollmentCode> {
  const { data } = await client.POST('/api/v1/admin/machines/{id}/enrollment-code', {
    params: { path: { id: machineId } },
  })
  const body = data as Partial<EnrollmentCode> | undefined

  if (!body?.code || !body.expires_at) {
    throw normalizeApiError(502, {
      type: 'about:blank',
      title: 'Respuesta inválida',
      status: 502,
      detail: 'El servidor no devolvió un código de enrolamiento válido.',
      code: 'ENROLLMENT_CODE_INVALID_RESPONSE',
    })
  }

  return { code: body.code, expires_at: body.expires_at }
}

export async function revokeMachineKey(machineId: string): Promise<void> {
  await client.POST('/api/v1/admin/machines/{id}/revoke-key', {
    params: { path: { id: machineId } },
  })
}
