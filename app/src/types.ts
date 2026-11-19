// Re-exports of the generated schema types under the names the app uses.
export type {
  Song, SeedCard, SeedInput, Note, VocalNote, Section, ChordEvent, Lock, Asset, Card, Controls, Key, Meter,
  GuitarTrack, AmbienceTrack, VocalTrack, NoteTrack, Mix, Capo,
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

export interface Catalog {
  instruments: Record<string, string[]>
  rhythmPresets: { presets: RhythmPreset[] } | RhythmPreset[]
  cardStyles: CardStyle[]
}
