import { createContext, useContext } from 'react'
import type { Controller } from './controller'
import { useStore, type AppState, type Store } from './store'

export const AppContext = createContext<{ c: Controller; store: Store } | null>(null)

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('AppContext missing')
  return ctx
}
/** Select one primitive or stable reference from the state. */
export function useSel<T>(select: (s: AppState) => T): T {
  const { store } = useApp()
  return useStore(store, select)
}
