import { useSyncExternalStore } from 'react'
import type { Catalog, SeedCard, Song, TrackId } from '../types'

export type View = 'capture' | 'song' | 'track' | 'card'

export interface CapturedInput {
  id: string
  kind: 'hum' | 'sound' | 'photo' | 'text'
  label: string
  assetId?: string
  text?: string
  url?: string
}

export interface Toast { text: string; kind: 'info' | 'error'; id: number }

export interface AppState {
  view: View
  song: Song | null
  seed: SeedCard | null
  inputs: CapturedInput[]
  recentSongs: { id: string; title: string }[]
  selectedTrack: TrackId | null
  /** Section being edited in the track view (looped while editing). */
  editSection: string | null
  positionTick: number
  playing: boolean
  recording: null | 'hum' | 'sound'
  busy: string | null
  toast: Toast | null
  serverOnline: boolean | null
  netOnline: boolean
  panelConnected: boolean
  panelAttached: boolean
  catalog: Catalog | null
  city: string
  /** Card fields as last previewed; print is only offered while they still match. */
  previewSig: string | null
  scanning: boolean
  mock: boolean
}

export const initialState = (mock: boolean): AppState => ({
  view: 'capture', song: null, seed: null, inputs: [], recentSongs: [], selectedTrack: null, editSection: null,
  positionTick: 0, playing: false, recording: null, busy: null, toast: null, serverOnline: null, netOnline: false,
  panelConnected: false, panelAttached: false, catalog: null, city: '', previewSig: null, scanning: false, mock,
})

/** Minimal external store: one immutable state object, listeners notified on every set. */
export class Store {
  private listeners = new Set<() => void>()
  constructor(public state: AppState) {}
  get = () => this.state
  set = (patch: Partial<AppState>) => {
    this.state = { ...this.state, ...patch }
    this.listeners.forEach((l) => l())
  }
  subscribe = (l: () => void) => { this.listeners.add(l); return () => { this.listeners.delete(l) } }
}

export function useStore<T>(store: Store, select: (s: AppState) => T): T {
  return useSyncExternalStore(store.subscribe, () => select(store.state))
}
