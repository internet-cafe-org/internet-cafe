
import { setupServer } from 'msw/node'
import { apiHandlers } from './handlers/api'
import { authHandlers } from './handlers/auth'

export const server = setupServer(
  ...apiHandlers,
  ...authHandlers,
)
