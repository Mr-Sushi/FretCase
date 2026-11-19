import { HttpApi } from './http'
import { MockApi } from './mock'
import type { Api } from './types'

export * from './types'
export { HttpApi, MockApi }

/** Mock mode: build with VITE_MOCK=1 or open the app with ?mock=1. */
export function isMockMode(): boolean {
  if (import.meta.env.VITE_MOCK === '1') return true
  return typeof location !== 'undefined' && new URLSearchParams(location.search).get('mock') === '1'
}

export function createApi(): Api {
  return isMockMode() ? new MockApi(150, typeof location !== 'undefined' && new URLSearchParams(location.search).get('lyrics') === 'online') : new HttpApi('')
}
