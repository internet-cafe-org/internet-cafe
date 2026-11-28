import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { otpErrorKind } from '../utils/otpErrors'
import App from '../App.vue'
import { createAppRouter } from '../router'
import {
  ApiError,
  register,
  requestPasswordReset,
  resendCode,
  resetPassword,
  verifyEmail,
} from '../services/auth'
import {
  clearPendingVerificationEmail,
  getPendingVerificationEmail,
  setPendingVerificationEmail,
} from '../services/pendingVerification'
import { confirmPasswordError, otpCodeError } from '../utils/validation'
import ForgotPasswordView from '../views/ForgotPasswordView.vue'

vi.mock('../services/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/auth')>()
  return {
    ...actual,
    register: vi.fn(),
    verifyEmail: vi.fn(),
    resendCode: vi.fn(),
    requestPasswordReset: vi.fn(),
    resetPassword: vi.fn(),
  }
})

const registerMock = vi.mocked(register)
const verifyEmailMock = vi.mocked(verifyEmail)
const resendCodeMock = vi.mocked(resendCode)
const requestResetMock = vi.mocked(requestPasswordReset)
const resetPasswordMock = vi.mocked(resetPassword)

const EMAIL = 'ana@universidad.example'

async function open(path: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(App, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

type Wrapper = Awaited<ReturnType<typeof open>>['wrapper']

async function submit(wrapper: Wrapper) {
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

beforeEach(() => {
  for (const mock of [
    registerMock,
    verifyEmailMock,
    resendCodeMock,
    requestResetMock,
    resetPasswordMock,
  ]) {
    mock.mockReset()
  }
  clearPendingVerificationEmail()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllEnvs()
  clearPendingVerificationEmail()
})

describe('validaciones del OTP y de la confirmación', () => {
  it('otpCodeError acepta 6 dígitos y rechaza el resto', () => {
    expect(otpCodeError('123456')).toBe('')
    expect(otpCodeError(' 123 456 ')).toBe('')
    expect(otpCodeError('')).toBe('Ingresa el código de 6 dígitos.')
    expect(otpCodeError('12a456')).toBe('El código debe tener 6 dígitos numéricos.')
  })

  it('confirmPasswordError exige que coincida', () => {
    expect(confirmPasswordError('abcdefghij', 'abcdefghij')).toBe('')
    expect(confirmPasswordError('abcdefghij', 'otra')).toBe('Las contraseñas no coinciden.')
  })
})

describe('VerifyEmailView', () => {
  it('camino feliz: verifica el código y muestra la cuenta activa', async () => {
    verifyEmailMock.mockResolvedValue(undefined)
    setPendingVerificationEmail(EMAIL)
    const { wrapper } = await open('/verify-email')

    await wrapper.get('#verify-code').setValue('123 456')
    await submit(wrapper)

    expect(verifyEmailMock).toHaveBeenCalledWith(EMAIL, '123456')
    expect(wrapper.text()).toContain('Correo verificado')
    expect(getPendingVerificationEmail()).toBeNull()
  })

  it('código vencido muestra el aviso correspondiente', async () => {
    verifyEmailMock.mockRejectedValue(new ApiError(410, 'OTP_EXPIRED'))
    setPendingVerificationEmail(EMAIL)
    const { wrapper } = await open('/verify-email')

    await wrapper.get('#verify-code').setValue('123456')
    await submit(wrapper)

    expect(wrapper.text()).toContain('El código venció.')
  })

  it('reenviar pide otro código con el correo pendiente', async () => {
    resendCodeMock.mockResolvedValue(undefined)
    setPendingVerificationEmail(EMAIL)
    const { wrapper } = await open('/verify-email')

    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Reenviar'))!
      .trigger('click')
    await flushPromises()

    expect(resendCodeMock).toHaveBeenCalledWith(EMAIL)
    expect(wrapper.text()).toContain('te enviamos un código nuevo')
  })
})

describe('ForgotPasswordView', () => {
  it('camino feliz: pide el código y cambia la contraseña', async () => {
    requestResetMock.mockResolvedValue(undefined)
    resetPasswordMock.mockResolvedValue(undefined)
    const { wrapper } = await open('/forgot-password')

    await wrapper.get('#forgot-email').setValue(EMAIL)
    await submit(wrapper)
    expect(requestResetMock).toHaveBeenCalledWith(EMAIL)

    await wrapper.get('#reset-code').setValue('654321')
    await wrapper.get('#reset-password').setValue('una-contraseña-larga')
    await wrapper.get('#reset-confirmation').setValue('una-contraseña-larga')
    await submit(wrapper)

    expect(resetPasswordMock).toHaveBeenCalledWith(EMAIL, '654321', 'una-contraseña-larga')
    expect(wrapper.text()).toContain('Contraseña actualizada')
  })
})

describe('RegisterView → verificar correo', () => {
  it('con VITE_REQUIRE_EMAIL_VERIFICATION=true pasa a «Verificar correo»', async () => {
    vi.stubEnv('VITE_REQUIRE_EMAIL_VERIFICATION', 'true')
    registerMock.mockResolvedValue(undefined)
    const { wrapper, router } = await open('/register')

    await wrapper.get('#register-name').setValue('Andrea Martínez López')
    await wrapper.get('#register-code').setValue('202610248')
    await wrapper.get('#register-email').setValue(EMAIL)
    await wrapper.get('#register-password').setValue('contraseña-larga')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await submit(wrapper)

    expect(registerMock).toHaveBeenCalled()
    expect(router.currentRoute.value.name).toBe('verify-email')
    expect(getPendingVerificationEmail()).toBe(EMAIL)
  })
})
function resendButton(wrapper: Wrapper) {
  return wrapper.findAll('button').find((b) => b.text().includes('Reenviar'))!
}

describe('otpErrorKind', () => {
  it('traduce cada estado de la API a su aviso', () => {
    expect(otpErrorKind(new Error('x'))).toBe('service')
    expect(otpErrorKind(new ApiError(0, 'NETWORK_ERROR'))).toBe('service')
    expect(otpErrorKind(new ApiError(503, 'UNKNOWN'))).toBe('service')
    expect(otpErrorKind(new ApiError(400, 'OTP_INVALID'))).toBe('invalid')
    expect(otpErrorKind(new ApiError(409, 'OTP_ALREADY_USED'))).toBe('used')
    expect(otpErrorKind(new ApiError(410, 'OTP_EXPIRED'))).toBe('expired')
    expect(otpErrorKind(new ApiError(429, 'OTP_MAX_ATTEMPTS'))).toBe('attempts')
    expect(otpErrorKind(new ApiError(429, 'RATE_LIMITED'))).toBe('rate')
    expect(otpErrorKind(new ApiError(422, 'VALIDATION_ERROR'))).toBe('validation')
  })
})

describe('VerifyEmailView: casos adicionales', () => {
  it('sin correo pendiente pide el correo y lo valida', async () => {
    verifyEmailMock.mockResolvedValue(undefined)
    const { wrapper } = await open('/verify-email')

    await wrapper.get('#verify-code').setValue('123456')
    await submit(wrapper)
    expect(wrapper.text()).toContain('Error: Ingresa tu correo institucional.')
    expect(verifyEmailMock).not.toHaveBeenCalled()

    await wrapper.get('#verify-email').setValue(` ${EMAIL} `)
    await submit(wrapper)
    expect(verifyEmailMock).toHaveBeenCalledWith(EMAIL, '123456')
  })

  it('un código mal formado no llama a la API', async () => {
    setPendingVerificationEmail(EMAIL)
    const { wrapper } = await open('/verify-email')

    await wrapper.get('#verify-code').setValue('12a456')
    await submit(wrapper)

    expect(wrapper.text()).toContain('Error: El código debe tener 6 dígitos numéricos.')
    expect(verifyEmailMock).not.toHaveBeenCalled()
  })

  it('si reenviar falla muestra el aviso', async () => {
    resendCodeMock.mockRejectedValue(new ApiError(429, 'RATE_LIMITED'))
    setPendingVerificationEmail(EMAIL)
    const { wrapper } = await open('/verify-email')

    await resendButton(wrapper).trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Demasiadas solicitudes.')
  })

  it('tras reenviar, el botón se bloquea 60 s y luego se libera', async () => {
    vi.useFakeTimers()
    resendCodeMock.mockResolvedValue(undefined)
    setPendingVerificationEmail(EMAIL)
    const { wrapper } = await open('/verify-email')

    await resendButton(wrapper).trigger('click')
    await flushPromises()
    expect(resendButton(wrapper).attributes('disabled')).toBeDefined()
    expect(resendButton(wrapper).text()).toContain('60 s')

    await vi.advanceTimersByTimeAsync(60_000)
    await flushPromises()
    expect(resendButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('mientras verifica no permite reenviar', async () => {
    let finish!: () => void
    verifyEmailMock.mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve
      }),
    )
    setPendingVerificationEmail(EMAIL)
    const { wrapper } = await open('/verify-email')
    await wrapper.get('#verify-code').setValue('123456')
    await submit(wrapper)

    expect(resendButton(wrapper).attributes('disabled')).toBeDefined()
    await resendButton(wrapper).trigger('click')
    expect(resendCodeMock).not.toHaveBeenCalled()

    finish()
    await flushPromises()
  })
})

describe('ForgotPasswordView: casos adicionales', () => {
  async function goToResetStep() {
    requestResetMock.mockResolvedValue(undefined)
    const opened = await open('/forgot-password')
    await opened.wrapper.get('#forgot-email').setValue(EMAIL)
    await submit(opened.wrapper)
    return opened
  }

  it('valida el correo antes de pedir el código', async () => {
    const { wrapper } = await open('/forgot-password')

    await submit(wrapper)

    expect(wrapper.text()).toContain('Error: Ingresa tu correo institucional.')
    expect(requestResetMock).not.toHaveBeenCalled()
  })

  it('si pedir el código falla muestra el aviso y no avanza', async () => {
    requestResetMock.mockRejectedValue(new ApiError(429, 'RATE_LIMITED'))
    const { wrapper } = await open('/forgot-password')

    await wrapper.get('#forgot-email').setValue(EMAIL)
    await submit(wrapper)

    expect(wrapper.text()).toContain('Demasiadas solicitudes.')
    expect(wrapper.find('#reset-code').exists()).toBe(false)
  })

  it('valida el código, la contraseña y la confirmación', async () => {
    const { wrapper } = await goToResetStep()

    await submit(wrapper)

    expect(wrapper.text()).toContain('Error: Ingresa el código de 6 dígitos.')
    expect(wrapper.text()).toContain('Error: Ingresa una contraseña de 10 a 128 caracteres.')
    expect(wrapper.text()).toContain('Error: Confirma tu nueva contraseña.')
    expect(resetPasswordMock).not.toHaveBeenCalled()
  })

  it('contraseñas distintas: no llama a la API', async () => {
    const { wrapper } = await goToResetStep()

    await wrapper.get('#reset-code').setValue('654321')
    await wrapper.get('#reset-password').setValue('una-contraseña-larga')
    await wrapper.get('#reset-confirmation').setValue('otra-contraseña-larga')
    await submit(wrapper)

    expect(wrapper.text()).toContain('Error: Las contraseñas no coinciden.')
    expect(resetPasswordMock).not.toHaveBeenCalled()
  })

  it('un código ya usado muestra el aviso y sigue en el paso 2', async () => {
    resetPasswordMock.mockRejectedValue(new ApiError(409, 'OTP_ALREADY_USED'))
    const { wrapper } = await goToResetStep()

    await wrapper.get('#reset-code').setValue('654321')
    await wrapper.get('#reset-password').setValue('una-contraseña-larga')
    await wrapper.get('#reset-confirmation').setValue('una-contraseña-larga')
    await submit(wrapper)

    expect(wrapper.text()).toContain('Este código ya se usó.')
    expect(wrapper.find('#reset-code').exists()).toBe(true)
  })

  it('reenviar pide otro código cuando termina la cuenta regresiva', async () => {
    vi.useFakeTimers()
    const { wrapper } = await goToResetStep()
    expect(resendButton(wrapper).attributes('disabled')).toBeDefined()

    await vi.advanceTimersByTimeAsync(60_000)
    await flushPromises()
    await resendButton(wrapper).trigger('click')
    await flushPromises()

    expect(requestResetMock).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('te enviamos un código nuevo')
  })

  it('usar otro correo vuelve al paso 1', async () => {
    const { wrapper } = await goToResetStep()

    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Usar otro correo'))!
      .trigger('click')

    expect(wrapper.find('#forgot-email').exists()).toBe(true)
    expect(wrapper.find('#reset-code').exists()).toBe(false)
  })

  it('usar otro correo borra el código y las contraseñas escritas', async () => {
    const { wrapper } = await goToResetStep()
    await wrapper.get('#reset-code').setValue('654321')
    await wrapper.get('#reset-password').setValue('una-contraseña-larga')
    await wrapper.get('#reset-confirmation').setValue('una-contraseña-larga')

    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Usar otro correo'))!
      .trigger('click')
    // El correo sigue escrito, así que volver a enviar lleva otra vez al paso 2.
    await submit(wrapper)

    const value = (id: string) => (wrapper.get(id).element as HTMLInputElement).value
    expect(value('#reset-code')).toBe('')
    expect(value('#reset-password')).toBe('')
    expect(value('#reset-confirmation')).toBe('')
  })

  it('al cambiar la contraseña no queda nada sensible en memoria', async () => {
    resetPasswordMock.mockResolvedValue(undefined)
    const { wrapper } = await goToResetStep()
    await wrapper.get('#reset-code').setValue('654321')
    await wrapper.get('#reset-password').setValue('una-contraseña-larga')
    await wrapper.get('#reset-confirmation').setValue('una-contraseña-larga')
    await submit(wrapper)

    expect(wrapper.text()).toContain('Contraseña actualizada')
    const vm = wrapper.findComponent(ForgotPasswordView).vm as unknown as {
      form: { code: string; password: string; confirmation: string }
    }
    expect(vm.form.code).toBe('')
    expect(vm.form.password).toBe('')
    expect(vm.form.confirmation).toBe('')
  })

  it('el aviso de reenvío desaparece al intentar cambiar la contraseña', async () => {
    vi.useFakeTimers()
    const { wrapper } = await goToResetStep()
    await vi.advanceTimersByTimeAsync(60_000)
    await flushPromises()
    await resendButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('te enviamos un código nuevo')

    await submit(wrapper)

    expect(wrapper.text()).not.toContain('te enviamos un código nuevo')
  })

  it('mientras cambia la contraseña no deja usar otro correo', async () => {
    let finish!: () => void
    resetPasswordMock.mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve
      }),
    )
    const { wrapper } = await goToResetStep()
    await wrapper.get('#reset-code').setValue('654321')
    await wrapper.get('#reset-password').setValue('una-contraseña-larga')
    await wrapper.get('#reset-confirmation').setValue('una-contraseña-larga')
    await submit(wrapper)

    const other = wrapper.findAll('button').find((b) => b.text().includes('Usar otro correo'))!
    expect(other.attributes('disabled')).toBeDefined()

    finish()
    await flushPromises()
  })
})
