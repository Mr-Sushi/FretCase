import type { Catalog, Song, SeedCard, SeedInput, TrackId } from '../types'

export type KnobControl = 'brightness' | 'complexity' | 'density'
export type CardPatch = Partial<{
  style: string; line: string; message: string; photoAssetId: string; showPhoto: boolean; city: string; showCity: boolean
}>
export type NoteInput = { start: number; duration: number; pitch: number; velocity?: number }

export type EditOp =
  | { op: 'setControl'; control: KnobControl; value: number }
  | { op: 'setTempo'; tempo: number }
  | { op: 'setTrackVolume'; track: TrackId; volume: number }
  | { op: 'setTrackMute'; track: TrackId; muted: boolean }
  | { op: 'setInstrument'; track: TrackId; instrument: string }
  | { op: 'replaceNotes'; track: TrackId; from: number; to: number; notes: NoteInput[] }
  | { op: 'setLyrics'; section: string; text: string }
  | { op: 'setRhythm'; family: 'strumming' | 'arpeggio'; presetId: string }
  | { op: 'lock'; track?: TrackId; section?: string }
  | { op: 'unlock'; track?: TrackId; section?: string }
  | { op: 'setSections'; sections: { id: string; label: string; startBar: number; endBar: number }[] }
  | { op: 'setTitle'; title: string }
  | ({ op: 'setCard' } & CardPatch)

export type AssetRole = 'hum' | 'ambience' | 'photo' | 'vocal_take'

export interface Health { ok: boolean; online: boolean; version: string; panel: boolean }
export interface SongListItem { id: string; title: string; updatedAt: string; card?: unknown }

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public song?: Song,
    public detail?: Record<string, unknown>,
  ) {
    super(message)
  }
}

/** Everything the app asks of the server. The real client and the mock both implement it. */
export interface Api {
  readonly mock: boolean
  health(): Promise<Health>
  catalog(): Promise<Catalog>
  uploadAsset(file: Blob, role: AssetRole): Promise<{ id: string; role: string; mime: string; durationSec?: number }>
  assetUrl(id: string): string
  createSeed(inputs: SeedInput[]): Promise<SeedCard>
  createSong(seed: SeedCard, bars?: number): Promise<Song>
  listSongs(): Promise<SongListItem[]>
  getSong(id: string): Promise<Song>
  edit(id: string, baseRevision: number, ops: EditOp[]): Promise<Song>
  another(id: string, baseRevision: number, section: string, track?: TrackId): Promise<Song>
  rehum(id: string, baseRevision: number, section: string, assetId: string): Promise<Song>
  undo(id: string, baseRevision: number): Promise<Song>
  cardPreview(id: string, baseRevision: number): Promise<Song>
  cardPrint(id: string, baseRevision: number): Promise<Song>
  resolveShare(shareId: string): Promise<string>
  getLocation(): Promise<{ city: string; source: 'gps' | 'manual' | 'none' }>
  putLocation(city: string): Promise<void>
  studyLog(events: { at: string; type: string; detail?: unknown }[]): Promise<void>
}
