import { setupServer } from 'msw/node'
import { apiHandlers } from './handlers/api'

export const server = setupServer(...apiHandlers)
