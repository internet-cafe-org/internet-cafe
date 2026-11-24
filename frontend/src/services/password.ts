/**
 * Cambio de contraseña propia (ST-UI-02). Contrato: PATCH /api/v1/me/password responde 204 sin cuerpo.
 * Al cambiarla se cierran las demás sesiones web; la actual sigue abierta.
 *
 * Contraseña actual incorrecta (RF-AUT-10): backend responde 401 con un `code` propio y detail
 * "La contraseña actual no es correcta." (hasta que despliegue ese cambio responde 422 con el mismo
 * detail; se aceptan ambos). api/client.ts solo renueva el token con AUTH_TOKEN_EXPIRED y solo
 * cierra la sesión con AUTH_TOKEN_EXPIRED / AUTH_INVALID_CREDENTIALS tras un reintento, así que el
 * código propio no dispara refresh ni logout.
 * - Otro 422: la nueva no cumple (10 a 128 caracteres) o es igual a la actual.
 * - Otro 401: token inválido; lo resuelve el flujo normal de refresh/logout del cliente.
 * - 429 RATE_LIMITED: demasiados intentos.
 */
import { api } from '@/api/client'
import { ApiError } from '@/errors/problem-details'

export const CURRENT_PASSWORD_INCORRECT = 'La contraseña actual no es correcta.'
/** Provisional: confirmar con backend el code definitivo del 401 por contraseña actual incorrecta. */
export const CURRENT_PASSWORD_INVALID_CODE = 'AUTH_CURRENT_PASSWORD_INVALID'

/**
 * Tipo local mínimo del contrato PATCH /api/v1/me/password (openapi.yaml, SEC-02).
 * El schema.d.ts generado todavía no incluye la ruta y el equipo de UI no modifica contratos ni
 * archivos generados. Es el mismo cliente (`api`): conserva el token Bearer, el refresh y el
 * manejo de errores. TODO: quitar este tipo cuando se regenere schema.d.ts y usar `api.PATCH`.
 */
interface ChangePasswordClient {
  PATCH(
    path: '/api/v1/me/password',
    init: { body: { current_password: string; new_password: string } },
  ): Promise<unknown>
}

const passwordApi = api as unknown as ChangePasswordClient

export async function changeMyPassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await passwordApi.PATCH('/api/v1/me/password', {
    body: { current_password: currentPassword, new_password: newPassword },
  })
}

export interface PasswordChangeFailure {
  /** 'actual' si el error pertenece al campo de la contraseña actual; null si es del formulario. */
  field: 'actual' | null
  message: string
}

export function passwordChangeFailure(error: unknown): PasswordChangeFailure {
  if (error instanceof ApiError) {
    const isCurrentPasswordError =
      (error.status === 401 || error.status === 422) &&
      (error.code === CURRENT_PASSWORD_INVALID_CODE ||
        error.message.trim() === CURRENT_PASSWORD_INCORRECT)
    if (isCurrentPasswordError) {
      return {
        field: 'actual',
        message: `${CURRENT_PASSWORD_INCORRECT} Revísala e inténtalo de nuevo.`,
      }
    }
    if (error.status === 422) {
      return {
        field: null,
        message:
          'La nueva contraseña no cumple los requisitos: debe tener entre 10 y 128 caracteres y ser distinta de la actual.',
      }
    }
    if (error.status === 429) {
      return {
        field: null,
        message: 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.',
      }
    }
  }
  return { field: null, message: 'No pudimos cambiar la contraseña. Inténtalo de nuevo.' }
}
