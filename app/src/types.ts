// Re-exports of the generated schema types under the names the app uses.
export type {
  Song, SeedCard, SeedInput, Note, VocalNote, Section, ChordEvent, Lock, Asset, Card, Controls, Key, Meter,
  GuitarTrack, AmbienceTrack, VocalTrack, NoteTrack, Mix, Capo, Region, Master, Candidate,
} from './generated/song'
export type { TrackId } from './generated/song'
export type { KnobId, KeyId, PanelMessage } from './generated/panel'

export interface RhythmPreset {
  family: 'strumming' | 'arpeggio'
  id: string
  label: string
  description: string
  subdivisions: number
  steps: string[]
  meter: string
  level: 'start' | 'next' | 'challenge'
}

export type CardStyle = 'ink' | 'comic' | 'xieyi' | 'original' | 'text'
export type TimeOfDay = 'day' | 'dusk' | 'night'
export type SpaceId = 'dry' | 'room' | 'hall'

export interface CatalogItem { id: string; label: string }

/** GET /api/catalog. The app shows `label`, never `id`. */
export interface Catalog {
  instruments: Record<string, CatalogItem[]>
  styles: Record<string, CatalogItem[]>
  spaces: CatalogItem[]
  rhythmPresets?: unknown
  cardStyles: CardStyle[]
}

/** GET /api/share/{shareId}/page */
export interface SharePage {
  title: string
  subtitle?: string
  line?: string
  city?: string
  date?: string
  message?: string
  photos: string[]
  card?: string
  lyrics: { section: string; lines: string[] }[]
  /** The studio version, when the song has one: its audio and the lyrics it sang. */
  render?: { audio: string; lyrics: { section: string; lines: string[] }[] }
}
