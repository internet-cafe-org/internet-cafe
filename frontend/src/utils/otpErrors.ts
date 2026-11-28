import { ApiError } from '@/services/auth'

export type OtpErrorKind =
  'invalid' | 'used' | 'expired' | 'attempts' | 'rate' | 'validation' | 'service'

export interface OtpErrorMessage {
  title: string
  text: string
}

export const OTP_ERROR_MESSAGES: Record<OtpErrorKind, OtpErrorMessage> = {
  invalid: {
    title: 'El código no es correcto.',
    text: 'Revisa los 6 dígitos o solicita un código nuevo.',
  },
  used: { title: 'Este código ya se usó.', text: 'Solicita un código nuevo para continuar.' },
  expired: {
    title: 'El código venció.',
    text: 'Los códigos duran 10 minutos. Solicita uno nuevo.',
  },
  attempts: {
    title: 'Superaste los 5 intentos.',
    text: 'Solicita un código nuevo para continuar.',
  },
  rate: {
    title: 'Demasiadas solicitudes.',
    text: 'Espera unos minutos antes de intentarlo de nuevo.',
  },
  validation: { title: 'Revisa los datos.', text: 'Alguno no tiene el formato esperado.' },
  service: {
    title: 'No pudimos conectar con el servicio.',
    text: 'Inténtalo de nuevo en unos minutos.',
  },
}

/** Traduce el error de la API a un aviso. Nunca se muestra el código ni el correo. */
export function otpErrorKind(error: unknown): OtpErrorKind {
  if (!(error instanceof ApiError)) return 'service'
  if (error.status === 0 || error.status >= 500) return 'service'
  if (error.status === 409) return 'used'
  if (error.status === 410) return 'expired'
  if (error.status === 429) return error.code === 'OTP_MAX_ATTEMPTS' ? 'attempts' : 'rate'
  if (error.status === 422) return 'validation'
  return 'invalid'
}
