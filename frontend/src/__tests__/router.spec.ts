import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'

import App from '../App.vue'
import { createAppRouter, routes } from '../router'
import { useSessionStore } from '../stores/session'

function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory())
  return { pinia, router, session: useSessionStore() }
}

describe('App + router', () => {
  it('renderiza el login (W-01) en /login', async () => {
    const { pinia, router } = setup()
    await router.push('/login')
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Iniciar sesión')
  })

  it('renderiza la página 404 en una ruta desconocida', async () => {
    const { pinia, router } = setup()
    await router.push('/no-existe')
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Página no encontrada')
  })

  it('cada ruta declarada tiene una vista que se renderiza (admin)', async () => {
    const { pinia, router, session } = setup()
    session.setUser('Admin', 'admin')
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    for (const route of routes) {
      const path = route.path.replace(':id', 'abc').replace('/:pathMatch(.*)*', '/x')
      await router.push(path)
      await flushPromises()
      expect(
        wrapper.find('main').exists(),
        `La ruta ${path} no renderizó un elemento <main>.`,
      ).toBe(true)
    }
  })
})

describe('guards del router', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('redirige a /login si no hay sesión en una ruta de usuario', async () => {
    const { router } = setup()
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('un estudiante no entra a /admin', async () => {
    const { router, session } = setup()
    session.setUser('Ana Pérez', 'student')
    await router.push('/admin/users')
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('un administrador entra a /admin', async () => {
    const { router, session } = setup()
    session.setUser('Admin', 'admin')
    await router.push('/admin/users')
    expect(router.currentRoute.value.name).toBe('admin-users')
  })

  it('/s conserva el token del fragmento hasta que la vista lo procese', async () => {
    const { router, session } = setup()
    session.setUser('Ana Pérez', 'student')
    await router.push('/s#token123')
    expect(router.currentRoute.value.name).toBe('confirm')
    expect(router.currentRoute.value.hash).toBe('#token123')
  })
})
