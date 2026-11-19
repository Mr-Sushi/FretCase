import type { Catalog, CardStyle, SeedCard, SeedInput, SharePage, Song, SpaceId, TimeOfDay, TrackId } from '../types'

export type KnobControl = 'brightness' | 'complexity' | 'density'
export type CardPatch = Partial<{
  style: CardStyle; line: string; message: string; photoAssetIds: string[]; coverAssetId: string
  showPhoto: boolean; city: string; showCity: boolean
}>
export type NoteInput = { start: number; duration: number; pitch: number; velocity?: number }
export type LeadTrack = 'vocal' | 'melody' | 'guitar'

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
  | { op: 'setRegion'; track: TrackId; section: string; play?: boolean; complexity?: number; intensity?: number; style?: string }
  | { op: 'copyRegion'; track: TrackId; section: string }
  | { op: 'setLead'; section: string; track: LeadTrack | null }
  | { op: 'shiftRegister'; track: TrackId; section: string; direction: 'up' | 'down' }
  | { op: 'revertMelody'; section: string }
  | { op: 'setMaster'; volume?: number; space?: SpaceId }

export type AssetRole = 'hum' | 'ambience' | 'photo' | 'vocal_take'

export interface Health { ok: boolean; online: boolean; version: string; panel: boolean }
export interface SongListItem { id: string; title: string; updatedAt: string; card?: unknown }
export interface PrinterStatus { kind: 'instax' | 'thermal' | 'dry_run'; connected: boolean; paper: 'ok' | 'out' | 'unknown'; remaining: number | null }
export interface LyricsRequest { themes?: string[]; tone?: 'plain' | 'subtle' | 'playful'; rhyme?: boolean }
export interface LyricsRewriteRequest extends LyricsRequest { sections?: string[]; keep?: Record<string, number[]> }
export interface LyricsAlternative { text: string; note?: string }
export interface LyricsTheme { text: string; source: 'photo' | 'text' | 'sound' | 'hum' }
export interface CandidateRequest { bars?: number; timeOfDay?: TimeOfDay; previousGroupId?: string }

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
  candidates(seed: SeedCard, req?: CandidateRequest): Promise<Song[]>
  choose(id: string): Promise<Song>
  listSongs(): Promise<SongListItem[]>
  getSong(id: string): Promise<Song>
  edit(id: string, baseRevision: number, ops: EditOp[]): Promise<Song>
  another(id: string, baseRevision: number, section: string, track?: TrackId): Promise<Song>
  rehum(id: string, baseRevision: number, section: string, assetId: string): Promise<Song>
  undo(id: string, baseRevision: number): Promise<Song>
  lyricsRewrite(id: string, baseRevision: number, req: LyricsRewriteRequest): Promise<Song>
  lyricsAlternatives(id: string, req: LyricsRequest & { section: string; line: number }): Promise<LyricsAlternative[]>
  lyricsThemes(id: string): Promise<LyricsTheme[]>
  cardPreview(id: string, baseRevision: number): Promise<Song>
  cardPrint(id: string, baseRevision: number): Promise<Song>
  printer(): Promise<PrinterStatus>
  resolveShare(shareId: string): Promise<string>
  sharePage(shareId: string): Promise<{ page: SharePage; song: Song }>
  getLocation(): Promise<{ city: string | null; source: 'gps' | 'manual' | 'none' }>
  putLocation(city: string): Promise<void>
  studyLog(events: { at: string; type: string; detail?: unknown }[]): Promise<void>
}
