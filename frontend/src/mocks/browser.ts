
import { setupWorker } from 'msw/browser'
import { apiHandlers } from './handlers/api'
import { authHandlers } from './handlers/auth'

export const worker = setupWorker(
  ...apiHandlers,
  ...authHandlers,
)
