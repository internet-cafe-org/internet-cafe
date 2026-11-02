import { describe, expect, it } from 'vitest'

import {
  consentError,
  loginEmailError,
  loginPasswordError,
  parseAllowedDomains,
  registerEmailError,
  registerPasswordError,
  requiredError,
} from '../utils/validation'

describe('validación de formularios', () => {
  it('login: correo obligatorio y con formato válido', () => {
    expect(loginEmailError('')).toBe('Ingresa tu correo institucional.')
    expect(loginEmailError('estudiante@')).toBe('Ingresa un correo con formato válido.')
    expect(loginEmailError('estudiante@universidad.example')).toBe('')
    expect(loginPasswordError('')).toBe('Ingresa tu contraseña.')
    expect(loginPasswordError('x')).toBe('')
  })

  it('registro: dominio institucional solo si hay lista configurada', () => {
    const domains = parseAllowedDomains(' Universidad.example , otra.edu ,')
    expect(domains).toEqual(['universidad.example', 'otra.edu'])
    expect(registerEmailError('ana@correo.example', domains)).toBe(
      'Utiliza el dominio institucional autorizado.',
    )
    expect(registerEmailError('ana@Universidad.example', domains)).toBe('')
    expect(registerEmailError('ana@correo.example', [])).toBe('')
    expect(registerEmailError('', domains)).toBe('Ingresa tu correo institucional.')
    expect(registerEmailError('ana', domains)).toBe('Ingresa un correo con formato válido.')
  })

  it('registro: contraseña de 10 a 128 caracteres (RF-AUT-11)', () => {
    expect(registerPasswordError('')).toBe('Ingresa una contraseña de 10 a 128 caracteres.')
    expect(registerPasswordError('123456789')).toBe(
      'La contraseña debe tener entre 10 y 128 caracteres.',
    )
    expect(registerPasswordError('1234567890')).toBe('')
    expect(registerPasswordError('a'.repeat(128))).toBe('')
    expect(registerPasswordError('a'.repeat(129))).not.toBe('')
  })

  it('registro: campos obligatorios y consentimiento', () => {
    expect(requiredError('  ', 'falta')).toBe('falta')
    expect(requiredError('Ana', 'falta')).toBe('')
    expect(consentError(false)).toBe('Debes autorizar el tratamiento de datos para continuar.')
    expect(consentError(true)).toBe('')
  })
})
