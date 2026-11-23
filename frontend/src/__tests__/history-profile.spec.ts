import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { http, HttpResponse } from 'msw'
import { createMemoryHistory } from 'vue-router'

import App from '../App.vue'
import { clearAccessToken, getAuthHeader, setAccessToken } from '../api/client'
import { server } from '../mocks/server'
import { createAppRouter } from '../router'
import { useSessionStore } from '../stores/session'

async function openRoute(path: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  setAccessToken('token-estudiante')
  session.setUser('Ana Pérez', 'student')

  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(App, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router, session }
}

beforeEach(() => {
  clearAccessToken()
})

describe('HistoryView (W-08)', () => {
  it('muestra el historial de sesiones y pagina con Cargar más', async () => {
    const requestedOffsets: string[] = []

    server.use(
      http.get('*/api/v1/me/sessions', ({ request }) => {
        const url = new URL(request.url)
        const offset = url.searchParams.get('offset') ?? '0'
        requestedOffsets.push(offset)

        if (offset === '0') {
          return HttpResponse.json({
            items: [
              {
                id: 'ses-1',
                machine_code: 'LAB3-PC12',
                lab: 'Sala 3',
                started_at: '2026-10-28T14:00:00Z',
                ended_at: '2026-10-28T15:30:00Z',
                end_reason: 'user_logout_pc',
                duration_s: 5400,
              },
              {
                id: 'ses-2',
                machine_code: 'LAB2-PC08',
                lab: 'Sala 2',
                started_at: '2026-10-29T10:00:00Z',
                ended_at: null,
                end_reason: null,
                duration_s: null,
              },
            ],
            total: 3,
            limit: 20,
            offset: 0,
          })
        }

        return HttpResponse.json({
          items: [
            {
              id: 'ses-3',
              machine_code: 'LAB1-PC05',
              lab: 'Sala 1',
              started_at: '2026-10-27T08:00:00Z',
              ended_at: '2026-10-27T08:45:00Z',
              end_reason: 'user_logout_web',
              duration_s: 2700,
            },
          ],
          total: 3,
          limit: 20,
          offset: 2,
        })
      }),
    )

    const { wrapper } = await openRoute('/history')

    expect(requestedOffsets).toEqual(['0'])
    expect(wrapper.text()).toContain('LAB3-PC12')
    expect(wrapper.text()).toContain('Sala 3')
    expect(wrapper.text()).toContain('1 h 30 min')
    expect(wrapper.text()).toContain('LAB2-PC08')
    expect(wrapper.text()).toContain('En curso')
    expect(wrapper.text()).toContain('Mostrando 2 de 3 registros')

    const loadMoreBtn = wrapper.findAll('button').find((b) => b.text() === 'Cargar más')
    expect(loadMoreBtn).toBeDefined()

    await loadMoreBtn?.trigger('click')
    await flushPromises()

    expect(requestedOffsets).toEqual(['0', '2'])
    expect(wrapper.text()).toContain('LAB1-PC05')
    expect(wrapper.text()).toContain('45 min')
    expect(wrapper.text()).toContain('Mostrando 3 de 3 registros')
    expect(wrapper.findAll('button').find((b) => b.text() === 'Cargar más')).toBeUndefined()
  })

  it('muestra estado vacío cuando el estudiante no tiene accesos', async () => {
    const { wrapper } = await openRoute('/history')

    expect(wrapper.text()).toContain('Aún no tienes accesos registrados.')
  })

  it('muestra mensaje de error y permite reintentar si falla la carga', async () => {
    let fail = true
    server.use(
      http.get('*/api/v1/me/sessions', () => {
        if (fail) {
          return HttpResponse.json(
            { type: 'about:blank', title: 'Error', status: 500, detail: 'Fallo interno' },
            { status: 500 },
          )
        }
        return HttpResponse.json({
          items: [
            {
              id: 'ses-ok',
              machine_code: 'LAB1-PC01',
              lab: 'Sala 1',
              started_at: '2026-10-28T14:00:00Z',
              ended_at: '2026-10-28T15:00:00Z',
              end_reason: 'user_logout_pc',
              duration_s: 3600,
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        })
      }),
    )

    const { wrapper } = await openRoute('/history')
    expect(wrapper.text()).toContain('No pudimos cargar tu historial de accesos.')

    fail = false
    const retryBtn = wrapper.findAll('button').find((b) => b.text() === 'Reintentar')
    await retryBtn?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('LAB1-PC01')
    expect(wrapper.text()).toContain('1 h')
  })
})

describe('ProfileView (W-09)', () => {
  it('muestra los datos del perfil con código enmascarado y cierra la sesión web', async () => {
    let logoutCalled = false
    server.use(
      http.post('*/api/v1/auth/logout', () => {
        logoutCalled = true
        return new HttpResponse(null, { status: 204 })
      }),
    )

    const { wrapper, router, session } = await openRoute('/profile')

    expect(wrapper.text()).toContain('Ana Pérez')
    expect(wrapper.text()).toContain('ana.perez@universidad.edu.co')
    expect(wrapper.text()).toContain('2021****34')
    expect(wrapper.find('input#codigo').attributes('readonly')).toBeDefined()

    const logoutBtn = wrapper.findAll('button').find((b) => b.text().includes('Cerrar sesión web'))
    expect(logoutBtn).toBeDefined()

    await logoutBtn?.trigger('click')
    await vi.waitFor(() => {
      expect(router.currentRoute.value.name).toBe('login')
    })

    expect(logoutCalled).toBe(true)
    expect(session.isAuthenticated).toBe(false)
    expect(getAuthHeader()).toEqual({})
  })

  it('valida la longitud, diferencia y confirmación en el formulario de cambio de contraseña', async () => {
    const { wrapper } = await openRoute('/profile')

    await wrapper.find('input#actual').setValue('ContrasenaActual123')
    await wrapper.find('input#nueva').setValue('corta')
    await wrapper.find('input#confirmar').setValue('corta')
    await wrapper.find('form.pass').trigger('submit')

    expect(wrapper.text()).toContain('La contraseña debe tener entre 10 y 128 caracteres.')

    await wrapper.find('input#nueva').setValue('NuevaContrasena123')
    await wrapper.find('input#confirmar').setValue('Diferente12345')
    await wrapper.find('form.pass').trigger('submit')

    expect(wrapper.text()).toContain('Las contraseñas nuevas no coinciden.')

    await wrapper.find('input#nueva').setValue('ContrasenaActual123')
    await wrapper.find('input#confirmar').setValue('ContrasenaActual123')
    await wrapper.find('form.pass').trigger('submit')

    expect(wrapper.text()).toContain('La nueva contraseña debe ser diferente a la actual.')
  })

  it('permite reintentar si falla la carga inicial del perfil', async () => {
    let fail = true
    server.use(
      http.get('*/api/v1/me', () => {
        if (fail) {
          return HttpResponse.json(
            { type: 'about:blank', title: 'Error', status: 500, detail: 'Fallo interno' },
            { status: 500 },
          )
        }
        return HttpResponse.json({
          id: '0192f0c4-0000-7000-8000-000000000001',
          full_name: 'Ana Pérez',
          email: 'ana.perez@universidad.edu.co',
          student_code_masked: '2021****34',
          role: 'student',
          status: 'active',
        })
      }),
    )

    const { wrapper } = await openRoute('/profile')
    expect(wrapper.text()).toContain('No pudimos cargar los datos de tu perfil.')

    fail = false
    const retryBtn = wrapper.findAll('button').find((b) => b.text() === 'Reintentar')
    await retryBtn?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Ana Pérez')
    expect(wrapper.text()).toContain('2021****34')
  })
})
