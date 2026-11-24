import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import { createAppRouter, routes } from '@/router'

const APP_TITLE = 'Registro de acceso a equipos'

describe('títulos de página por ruta (WCAG 2.4.2)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.title = APP_TITLE
  })

  it('cada ruta tiene un título propio y distinto', () => {
    const titles = routes.map((route) => route.meta?.title)

    expect(titles.every((title) => typeof title === 'string' && title.length > 0)).toBe(true)
    expect(new Set(titles).size).toBe(routes.length)
  })

  it('document.title refleja la ruta actual', async () => {
    const router = createAppRouter(createMemoryHistory())

    await router.push('/login')
    expect(document.title).toBe(`Iniciar sesión · ${APP_TITLE}`)

    await router.push('/ruta-que-no-existe')
    expect(document.title).toBe(`Página no encontrada · ${APP_TITLE}`)
  })
})
