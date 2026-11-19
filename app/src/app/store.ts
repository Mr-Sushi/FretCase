import { useSyncExternalStore } from 'react'
import type { Catalog, SeedCard, Song, TimeOfDay, TrackId } from '../types'
import type { LyricsAlternative, LyricsTheme, PrinterStatus } from '../api'
import { DEFAULT_CATALOG } from '../lib/catalog'

export type View = 'capture' | 'pick' | 'shape' | 'detail' | 'lyrics' | 'card'
export type CaptureMode = 'photo' | 'hum' | 'sound' | 'text'
export const MAX_PHOTOS = 9

export interface CapturedInput {
  id: string
  kind: 'hum' | 'sound' | 'photo' | 'text'
  label: string
  /** Set once the file has been uploaded (when "做成歌" is pressed). */
  assetId?: string
  text?: string
  /** Local preview URL of the recording or photo. */
  url?: string
  blob?: Blob
  durationSec?: number
}

export interface Toast { text: string; kind: 'info' | 'error'; id: number }
export interface PreviewState { index: number; fromTick: number; toTick: number }
export interface LyricsUi {
  themes: LyricsTheme[]
  themeSel: string[]
  tone: 'plain' | 'subtle' | 'playful'
  rhyme: boolean
  /** Lines to keep when rewriting: section id to line indexes. Held in the app, sent with the rewrite request. */
  keeps: Record<string, number[]>
  selected: { section: string; index: number } | null
  alternatives: LyricsAlternative[] | null
  /** The last wording or rewrite call failed. Typing stays available. */
  offline: boolean
  /** Why it failed, from the server's error.detail.reason (or "network" when the server could not be reached). */
  offlineReason: string | null
  /** A rewrite is running. */
  writing: boolean
  loading: boolean
  /** Lines the server or the app found not to fit: "section:index" keys. */
  misfit: string[]
}

export interface AppState {
  view: View
  song: Song | null
  seed: SeedCard | null
  inputs: CapturedInput[]
  captureMode: CaptureMode
  photoSel: string | null
  recentSongs: { id: string; title: string }[]
  candidates: Song[] | null
  timeOfDay: TimeOfDay
  focus: number
  preview: PreviewState | null
  /** Track selected on the track screen (and by the panel's track keys). */
  selectedTrack: TrackId | null
  /** Section selected on the shape and track screens. */
  editSection: string | null
  /** Loop the selected section while playing. */
  looping: boolean
  solo: TrackId | null
  takes: Record<string, number>
  lyrics: LyricsUi
  printer: PrinterStatus | null
  cardBusy: boolean
  positionTick: number
  playing: boolean
  recording: null | 'hum' | 'sound'
  busy: string | null
  toast: Toast | null
  serverOnline: boolean | null
  netOnline: boolean
  /** The server has a text model for lyrics (GET /health `lyrics`). */
  lyricsAvailable: boolean
  panelConnected: boolean
  panelAttached: boolean
  catalog: Catalog
  city: string
  /** Card fields (and title) as last previewed. */
  previewSig: string | null
  scanning: boolean
  showSongs: boolean
  mock: boolean
}

export const initialLyrics = (): LyricsUi => ({ themes: [], themeSel: [], tone: 'plain', rhyme: true, keeps: {}, selected: null, alternatives: null, offline: false, offlineReason: null, writing: false, loading: false, misfit: [] })

export const initialState = (mock: boolean): AppState => ({
  view: 'capture', song: null, seed: null, inputs: [], captureMode: 'photo', photoSel: null, recentSongs: [],
  candidates: null, timeOfDay: 'dusk', focus: 0, preview: null,
  selectedTrack: null, editSection: null, looping: false, solo: null, takes: {}, lyrics: initialLyrics(), printer: null, cardBusy: false,
  positionTick: 0, playing: false, recording: null, busy: null, toast: null, serverOnline: null, netOnline: false, lyricsAvailable: false,
  panelConnected: false, panelAttached: false, catalog: DEFAULT_CATALOG, city: '', previewSig: null, scanning: false, showSongs: false, mock,
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
