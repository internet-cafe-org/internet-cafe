import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

import { ApiError } from '../errors/problem-details'
import {
  CURRENT_PASSWORD_INCORRECT,
  CURRENT_PASSWORD_INVALID_CODE,
  changeMyPassword,
} from '../services/password'
import ProfileView from '../views/ProfileView.vue'

vi.mock('../composables/useSignOut', () => ({ useSignOut: () => vi.fn() }))
vi.mock('../services/me', () => ({
  fetchMyProfile: vi.fn().mockResolvedValue({
    id: '1',
    full_name: 'Ana Pérez',
    email: 'ana@universidad.example',
    student_code_masked: '2021****34',
    role: 'student',
    status: 'active',
  }),
}))
vi.mock('../services/password', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/password')>()),
  changeMyPassword: vi.fn(),
}))

const changeMock = vi.mocked(changeMyPassword)

async function open() {
  setActivePinia(createPinia())
  const wrapper = mount(ProfileView)
  await flushPromises()
  return wrapper
}

async function fill(wrapper: VueWrapper, actual: string, nueva: string, confirmar: string) {
  await wrapper.get('input#actual').setValue(actual)
  await wrapper.get('input#nueva').setValue(nueva)
  await wrapper.get('input#confirmar').setValue(confirmar)
}

async function submit(wrapper: VueWrapper) {
  await wrapper.get('form.pass').trigger('submit')
  await flushPromises()
}

const value = (wrapper: VueWrapper, selector: string) =>
  (wrapper.get(selector).element as HTMLInputElement).value

beforeEach(() => {
  changeMock.mockReset()
})

describe('Perfil: cambio de contraseña (ST-UI-02)', () => {
  it('éxito: llama a la API, avisa que se cerraron las otras sesiones y vacía los campos', async () => {
    changeMock.mockResolvedValue(undefined)
    const wrapper = await open()

    await fill(wrapper, 'ActualClave-1', 'NuevaClave-2026', 'NuevaClave-2026')
    await submit(wrapper)

    expect(changeMock).toHaveBeenCalledWith('ActualClave-1', 'NuevaClave-2026')
    expect(wrapper.text()).toContain(
      'Contraseña actualizada. Se cerraron tus otras sesiones web; esta sigue abierta.',
    )
    expect(value(wrapper, 'input#actual')).toBe('')
    expect(value(wrapper, 'input#nueva')).toBe('')
    expect(value(wrapper, 'input#confirmar')).toBe('')
    expect(wrapper.text()).not.toContain('aún no está disponible')
  })

  it('las validaciones locales no llaman a la API', async () => {
    const wrapper = await open()

    await fill(wrapper, 'ActualClave-1', 'corta', 'corta')
    await submit(wrapper)
    expect(wrapper.text()).toContain('La contraseña debe tener entre 10 y 128 caracteres.')

    await fill(wrapper, 'ActualClave-1', 'NuevaClave-2026', 'Diferente-12345')
    await submit(wrapper)
    expect(wrapper.text()).toContain('Las contraseñas nuevas no coinciden.')

    await fill(wrapper, 'ActualClave-1', 'ActualClave-1', 'ActualClave-1')
    await submit(wrapper)
    expect(wrapper.text()).toContain('La nueva contraseña debe ser diferente a la actual.')

    expect(changeMock).not.toHaveBeenCalled()
  })

  it('422 contraseña actual incorrecta: error en el campo actual, enfoca y conserva lo escrito', async () => {
    changeMock.mockRejectedValue(
      new ApiError({ status: 422, code: 'VALIDATION_ERROR', detail: CURRENT_PASSWORD_INCORRECT }),
    )
    const wrapper = await open()

    await fill(wrapper, 'mala-clave-1', 'NuevaClave-2026', 'NuevaClave-2026')
    await submit(wrapper)

    const error = wrapper.get('#actual-error')
    expect(error.text()).toBe('La contraseña actual no es correcta. Revísala e inténtalo de nuevo.')
    expect(wrapper.get('input#actual').attributes('aria-invalid')).toBe('true')
    expect(wrapper.get('input#actual').attributes('aria-describedby')).toBe('actual-error')
    expect(wrapper.find('.feedback.error').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Contraseña actualizada')
    expect(value(wrapper, 'input#nueva')).toBe('NuevaClave-2026')

    // al reintentar, el error del campo se limpia
    changeMock.mockResolvedValue(undefined)
    await fill(wrapper, 'ActualClave-1', 'NuevaClave-2026', 'NuevaClave-2026')
    await submit(wrapper)
    expect(wrapper.find('#actual-error').exists()).toBe(false)
    expect(wrapper.get('input#actual').attributes('aria-invalid')).toBeUndefined()
  })

  it('401 contraseña actual incorrecta: mismo error en el campo actual', async () => {
    changeMock.mockRejectedValue(
      new ApiError({
        status: 401,
        code: CURRENT_PASSWORD_INVALID_CODE,
        detail: CURRENT_PASSWORD_INCORRECT,
      }),
    )
    const wrapper = await open()

    await fill(wrapper, 'mala-clave-1', 'NuevaClave-2026', 'NuevaClave-2026')
    await submit(wrapper)

    expect(wrapper.get('#actual-error').text()).toBe(
      'La contraseña actual no es correcta. Revísala e inténtalo de nuevo.',
    )
    expect(wrapper.find('.feedback.error').exists()).toBe(false)
    expect(value(wrapper, 'input#nueva')).toBe('NuevaClave-2026')
  })

  it('otro 422: aviso del formulario sin marcar el campo actual', async () => {
    changeMock.mockRejectedValue(
      new ApiError({
        status: 422,
        code: 'VALIDATION_ERROR',
        detail: 'La nueva contraseña debe ser distinta de la actual.',
      }),
    )
    const wrapper = await open()

    await fill(wrapper, 'ActualClave-1', 'NuevaClave-2026', 'NuevaClave-2026')
    await submit(wrapper)

    expect(wrapper.get('.feedback.error').text()).toContain('entre 10 y 128 caracteres')
    expect(wrapper.find('#actual-error').exists()).toBe(false)
    expect(value(wrapper, 'input#nueva')).toBe('NuevaClave-2026')
  })

  it('429: pide esperar', async () => {
    changeMock.mockRejectedValue(new ApiError({ status: 429, code: 'RATE_LIMITED' }))
    const wrapper = await open()

    await fill(wrapper, 'ActualClave-1', 'NuevaClave-2026', 'NuevaClave-2026')
    await submit(wrapper)

    expect(wrapper.text()).toContain('Demasiados intentos')
  })

  it('error de red: aviso general', async () => {
    changeMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const wrapper = await open()

    await fill(wrapper, 'ActualClave-1', 'NuevaClave-2026', 'NuevaClave-2026')
    await submit(wrapper)

    expect(wrapper.text()).toContain('No pudimos cambiar la contraseña. Inténtalo de nuevo.')
  })

  it('mientras envía deshabilita el botón y no permite un segundo envío', async () => {
    let resolve: () => void = () => {}
    changeMock.mockReturnValue(new Promise<void>((r) => (resolve = r)))
    const wrapper = await open()

    await fill(wrapper, 'ActualClave-1', 'NuevaClave-2026', 'NuevaClave-2026')
    await wrapper.get('form.pass').trigger('submit')
    await wrapper.get('form.pass').trigger('submit')

    expect(changeMock).toHaveBeenCalledTimes(1)
    expect(wrapper.get('button.change').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button.change').text()).toBe('Cambiando contraseña...')

    resolve()
    await flushPromises()
    expect(wrapper.get('button.change').attributes('disabled')).toBeUndefined()
  })
})
