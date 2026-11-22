import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'

import App from '../App.vue'
import { createAppRouter } from '../router'
import {
  endMySession,
  getActiveSession,
  getRecentSessions,
  type MySession,
} from '../services/mySessions'
import { useSessionStore } from '../stores/session'

vi.mock('../services/mySessions', () => ({
  getActiveSession: vi.fn(),
  getRecentSessions: vi.fn(),
  endMySession: vi.fn(),
}))

const active: MySession = {
  id: 'active-1',
  machine_code: 'LAB3-PC12',
  lab: 'Sala 3 · Bloque B',
  started_at: '2026-11-12T14:04:21Z',
  ended_at: null,
}

const past = (id: string, machine: string): MySession => ({
  id,
  machine_code: machine,
  lab: 'Sala 1',
  started_at: '2026-11-11T09:00:00Z',
  ended_at: '2026-11-11T10:00:00Z',
  end_reason: 'user_logout_pc',
  duration_s: 3600,
})

async function open() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useSessionStore().setUser('Ana Pérez', 'student')
  const router = createAppRouter(createMemoryHistory())
  await router.push('/')
  const wrapper = mount(App, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

const button = (wrapper: VueWrapper, text: string) =>
  wrapper.findAll('button').find((b) => b.text() === text)

beforeEach(() => {
  vi.resetAllMocks()
})

describe('HomeView (W-05)', () => {
  it('con sesión activa muestra el equipo, la sala y "Terminar acceso"', async () => {
    vi.mocked(getActiveSession).mockResolvedValue(active)
    vi.mocked(getRecentSessions).mockResolvedValue([active, past('p1', 'LAB1-PC03')])
    const { wrapper } = await open()

    expect(wrapper.text()).toContain('LAB3-PC12')
    expect(wrapper.text()).toContain('Sala 3 · Bloque B')
    expect(button(wrapper, 'Terminar acceso')).toBeTruthy()
    expect(wrapper.text()).toContain('¿Cómo registrar un acceso?')
  })

  it('muestra solo 3 accesos y no repite la sesión activa', async () => {
    vi.mocked(getActiveSession).mockResolvedValue(active)
    vi.mocked(getRecentSessions).mockResolvedValue([
      active,
      past('p1', 'PC-A'),
      past('p2', 'PC-B'),
      past('p3', 'PC-C'),
    ])
    const { wrapper } = await open()

    const rows = wrapper.findAll('.list li')
    expect(rows).toHaveLength(3)
    expect(wrapper.find('.list').text()).not.toContain('LAB3-PC12')
  })

  it('sin sesión activa no muestra "Terminar acceso" y avisa que no hay accesos', async () => {
    vi.mocked(getActiveSession).mockResolvedValue(null)
    vi.mocked(getRecentSessions).mockResolvedValue([])
    const { wrapper } = await open()

    expect(button(wrapper, 'Terminar acceso')).toBeUndefined()
    expect(wrapper.text()).toContain('Aún no tienes accesos')
  })

  it('"Terminar acceso" cierra la sesión, avisa y refresca los últimos accesos', async () => {
    vi.mocked(getActiveSession).mockResolvedValue(active)
    vi.mocked(getRecentSessions)
      .mockResolvedValueOnce([active])
      .mockResolvedValueOnce([{ ...active, ended_at: '2026-11-12T15:00:00Z', duration_s: 3300 }])
    vi.mocked(endMySession).mockResolvedValue()
    const { wrapper } = await open()

    await button(wrapper, 'Terminar acceso')!.trigger('click')
    await flushPromises()

    expect(endMySession).toHaveBeenCalledWith('active-1')
    expect(button(wrapper, 'Terminar acceso')).toBeUndefined()
    expect(wrapper.text()).toContain('Terminaste tu acceso')
    expect(wrapper.findAll('.list li')).toHaveLength(1)
  })

  it('si falla el cierre muestra el error y conserva la sesión', async () => {
    vi.mocked(getActiveSession).mockResolvedValue(active)
    vi.mocked(getRecentSessions).mockResolvedValue([active])
    vi.mocked(endMySession).mockRejectedValue(new Error('network'))
    const { wrapper } = await open()

    await button(wrapper, 'Terminar acceso')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('No pudimos terminar tu acceso')
    expect(button(wrapper, 'Terminar acceso')).toBeTruthy()
  })

  it('si falla la carga muestra el error y permite reintentar', async () => {
    vi.mocked(getActiveSession).mockRejectedValue(new Error('network'))
    vi.mocked(getRecentSessions).mockRejectedValue(new Error('network'))
    const { wrapper } = await open()

    expect(wrapper.text()).toContain('No pudimos cargar tu información')

    vi.mocked(getActiveSession).mockResolvedValue(null)
    vi.mocked(getRecentSessions).mockResolvedValue([])
    await button(wrapper, 'Reintentar')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('No pudimos cargar tu información')
    expect(wrapper.text()).toContain('¿Cómo registrar un acceso?')
  })
})
