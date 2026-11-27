/** Validaciones locales de los formularios (SRS RF-AUT-01, RF-AUT-11). */

export const PASSWORD_MIN = 10
export const PASSWORD_MAX = 128

const EMAIL_FORMAT = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function parseAllowedDomains(raw: string): string[] {
  return raw
    .split(',')
    .map((d) => d.trim().toLowerCase())
    .filter(Boolean)
}

export function requiredError(value: string, message: string): string {
  return value.trim() === '' ? message : ''
}

/** Login: solo formato; la existencia de la cuenta nunca se revela. */
export function loginEmailError(value: string): string {
  const email = value.trim()
  if (email === '') return 'Ingresa tu correo institucional.'
  if (!EMAIL_FORMAT.test(email)) return 'Ingresa un correo con formato válido.'
  return ''
}

export function loginPasswordError(value: string): string {
  return value === '' ? 'Ingresa tu contraseña.' : ''
}

/** Registro: formato y, si hay lista configurada, dominio institucional. */
export function registerEmailError(value: string, allowedDomains: string[]): string {
  const email = value.trim()
  if (email === '') return 'Ingresa tu correo institucional.'
  if (!EMAIL_FORMAT.test(email)) return 'Ingresa un correo con formato válido.'
  if (allowedDomains.length > 0) {
    const domain = email.split('@')[1]?.toLowerCase() ?? ''
    if (!allowedDomains.includes(domain)) return 'Utiliza el dominio institucional autorizado.'
  }
  return ''
}

export function registerPasswordError(value: string): string {
  if (value === '') return 'Ingresa una contraseña de 10 a 128 caracteres.'
  if (value.length < PASSWORD_MIN || value.length > PASSWORD_MAX) {
    return 'La contraseña debe tener entre 10 y 128 caracteres.'
  }
  return ''
}

export function consentError(accepted: boolean): string {
  return accepted ? '' : 'Debes autorizar el tratamiento de datos para continuar.'
}

export const OTP_LENGTH = 6
const OTP_FORMAT = /^\d{6}$/

/** Quita los espacios del código (suele pegarse como «123 456»). */
export function normalizeOtp(value: string): string {
  return value.replace(/\s+/g, '')
}

export function otpCodeError(value: string): string {
  const code = normalizeOtp(value)
  if (code === '') return `Ingresa el código de ${OTP_LENGTH} dígitos.`
  if (!OTP_FORMAT.test(code)) return `El código debe tener ${OTP_LENGTH} dígitos numéricos.`
  return ''
}

export function confirmPasswordError(password: string, confirmation: string): string {
  if (confirmation === '') return 'Confirma tu nueva contraseña.'
  if (password !== confirmation) return 'Las contraseñas no coinciden.'
  return ''
}
