import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'

import App from '../App.vue'
import { createAppRouter } from '../router'
import { ApiError, login, register, type LoginResponse } from '../services/auth'
import { setPendingScanToken, takePendingScanToken } from '../services/pendingScan'
import { previewScan } from '../services/scan'
import { useSessionStore } from '../stores/session'

vi.mock('../services/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/auth')>()
  return { ...actual, login: vi.fn(), register: vi.fn() }
})

vi.mock('../services/scan', () => ({ previewScan: vi.fn(), claimScan: vi.fn() }))

const loginMock = vi.mocked(login)
const registerMock = vi.mocked(register)

const ANA: LoginResponse = {
  access_token: 'token-en-memoria',
  token_type: 'Bearer',
  expires_in: 600,
  user: { id: '1', full_name: 'Ana Pérez', role: 'student' },
}

async function open(path: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(App, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router, session: useSessionStore() }
}

type Wrapper = Awaited<ReturnType<typeof open>>['wrapper']

async function fillLogin(wrapper: Wrapper, email: string, password: string) {
  await wrapper.get('#login-email').setValue(email)
  await wrapper.get('#login-password').setValue(password)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

async function fillRegister(wrapper: Wrapper, password = 'contraseña-larga') {
  await wrapper.get('#register-name').setValue('Andrea Martínez López')
  await wrapper.get('#register-code').setValue('202610248')
  await wrapper.get('#register-email').setValue('andrea@universidad.example')
  await wrapper.get('#register-password').setValue(password)
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

beforeEach(() => {
  loginMock.mockReset()
  registerMock.mockReset()
  takePendingScanToken()
})

describe('LoginView (W-01)', () => {
  it('camino feliz: inicia sesión y va al destino provisional', async () => {
    loginMock.mockResolvedValue(ANA)
    const { wrapper, router, session } = await open('/login')

    await fillLogin(wrapper, 'ana@universidad.example', 'contraseña-larga')

    expect(loginMock).toHaveBeenCalledWith('ana@universidad.example', 'contraseña-larga')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('redirecting'))
    expect(session.fullName).toBe('Ana Pérez')
    expect(session.role).toBe('student')
  })

  it('muestra errores locales si se envía vacío o con correo mal formado', async () => {
    const { wrapper } = await open('/login')

    await fillLogin(wrapper, '', '')
    expect(wrapper.text()).toContain('Error: Ingresa tu correo institucional.')
    expect(wrapper.text()).toContain('Error: Ingresa tu contraseña.')

    await fillLogin(wrapper, 'estudiante@', 'x')
    expect(wrapper.text()).toContain('Error: Ingresa un correo con formato válido.')
    expect(loginMock).not.toHaveBeenCalled()
  })

  it('credenciales incorrectas: mensaje genérico', async () => {
    loginMock.mockRejectedValue(new ApiError(401, 'AUTH_INVALID_CREDENTIALS'))
    const { wrapper } = await open('/login')

    await fillLogin(wrapper, 'ana@universidad.example', 'mala-contraseña')

    expect(wrapper.text()).toContain('No pudimos iniciar sesión.')
    expect(wrapper.text()).toContain('El correo o la contraseña son incorrectos.')
  })

  it('bloqueo temporal (423): avisa y deshabilita el formulario', async () => {
    loginMock.mockRejectedValue(new ApiError(423, 'AUTH_ACCOUNT_LOCKED'))
    const { wrapper } = await open('/login')

    await fillLogin(wrapper, 'ana@universidad.example', 'x')

    expect(wrapper.text()).toContain('Acceso bloqueado temporalmente.')
    expect(wrapper.get('#login-email').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('sin conexión con el servicio: aviso distinto al de credenciales', async () => {
    loginMock.mockRejectedValue(new ApiError(0, 'NETWORK_ERROR'))
    const { wrapper } = await open('/login')

    await fillLogin(wrapper, 'ana@universidad.example', 'contraseña-larga')

    expect(wrapper.text()).toContain('No pudimos conectar con el servicio.')
  })

  it('el botón del ojo muestra y oculta la contraseña', async () => {
    const { wrapper } = await open('/login')
    expect(wrapper.get('#login-password').attributes('type')).toBe('password')
    await wrapper.get('button[aria-label="Mostrar contraseña"]').trigger('click')
    expect(wrapper.get('#login-password').attributes('type')).toBe('text')
  })
})

describe('RegisterView (W-02)', () => {
  it('camino feliz: registra e inicia sesión automáticamente', async () => {
    registerMock.mockResolvedValue(undefined)
    loginMock.mockResolvedValue(ANA)
    const { wrapper, router } = await open('/register')

    await fillRegister(wrapper)

    expect(registerMock).toHaveBeenCalledWith({
      email: 'andrea@universidad.example',
      student_code: '202610248',
      full_name: 'Andrea Martínez López',
      password: 'contraseña-larga',
      privacy_consent: true,
    })
    expect(loginMock).toHaveBeenCalledWith('andrea@universidad.example', 'contraseña-larga')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('redirecting'))
  })

  it('valida campos obligatorios y consentimiento sin llamar a la API', async () => {
    const { wrapper } = await open('/register')

    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Error: Ingresa tu nombre completo.')
    expect(wrapper.text()).toContain('Error: Ingresa tu código estudiantil.')
    expect(wrapper.text()).toContain('Error: Ingresa una contraseña de 10 a 128 caracteres.')
    expect(wrapper.text()).toContain(
      'Error: Debes autorizar el tratamiento de datos para continuar.',
    )
    expect(registerMock).not.toHaveBeenCalled()
  })

  it('contraseña corta: error de longitud', async () => {
    const { wrapper } = await open('/register')
    await fillRegister(wrapper, '123456')
    expect(wrapper.text()).toContain('La contraseña debe tener entre 10 y 128 caracteres.')
    expect(registerMock).not.toHaveBeenCalled()
  })

  it('si el registro falla muestra el mensaje genérico', async () => {
    registerMock.mockRejectedValue(new ApiError(422, 'VALIDATION_ERROR'))
    const { wrapper } = await open('/register')

    await fillRegister(wrapper)

    expect(wrapper.text()).toContain('No pudimos completar el registro.')
    expect(loginMock).not.toHaveBeenCalled()
  })
})

describe('RedirectingView (destino provisional)', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  async function openSignedIn(role: 'student' | 'admin') {
    const pinia = createPinia()
    setActivePinia(pinia)
    useSessionStore().setUser('Ana Pérez', role)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/redirigiendo')
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()
    return { wrapper, router }
  }

  it('sin QR pendiente va al destino del rol', async () => {
    const { wrapper, router } = await openSignedIn('student')
    expect(wrapper.text()).toContain('Iniciaste sesión correctamente')
    await vi.advanceTimersByTimeAsync(1300)
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('home'))
  })

  it('un administrador va al panel de equipos', async () => {
    const { router } = await openSignedIn('admin')
    await vi.advanceTimersByTimeAsync(1300)
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('admin-machines'))
  })

  it('con QR pendiente continúa en Confirmar acceso y usa el token', async () => {
    vi.mocked(previewScan).mockRejectedValue(new Error('sin API en la prueba'))
    setPendingScanToken('tok123')
    const { router } = await openSignedIn('student')
    await vi.advanceTimersByTimeAsync(1300)
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('confirm'))
    await vi.waitFor(() => expect(previewScan).toHaveBeenCalledWith('tok123'))
  })
})

describe('continuidad del QR sin sesión', () => {
  it('escanear /s#token sin sesión lleva al login y conserva el token en memoria', async () => {
    setActivePinia(createPinia())
    const router = createAppRouter(createMemoryHistory())
    await router.push('/s#abc123')
    expect(router.currentRoute.value.name).toBe('login')
    expect(takePendingScanToken()).toBe('abc123')
    expect(takePendingScanToken()).toBeNull()
  })
})
