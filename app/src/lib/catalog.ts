import type { Catalog, TrackId } from '../types'

/** Used until /api/catalog answers, and in mock mode. Same content as the example in docs/api.md. */
export const DEFAULT_CATALOG: Catalog = {
  instruments: {
    vocal: [{ id: 'synth-male', label: 'Male voice' }, { id: 'synth-female', label: 'Female voice' }, { id: 'synth-soft', label: 'Soft voice' }],
    melody: [{ id: 'harmonica', label: 'Harmonica' }, { id: 'piano', label: 'Piano' }, { id: 'whistle', label: 'Whistle' }, { id: 'flute', label: 'Flute' }],
    guitar: [{ id: 'steel', label: 'Steel-string guitar' }, { id: 'nylon', label: 'Nylon guitar' }, { id: 'electric-clean', label: 'Electric guitar (clean)' }, { id: 'ukulele', label: 'Ukulele' }],
    bass: [{ id: 'finger-bass', label: 'Finger bass' }, { id: 'upright-bass', label: 'Upright bass' }, { id: 'synth-bass', label: 'Synth bass' }],
    drums: [{ id: 'jazz-kit', label: 'Jazz kit' }, { id: 'pop-kit', label: 'Pop kit' }, { id: 'hand-drum', label: 'Hand drum' }],
    ambience: [{ id: 'recording', label: 'As recorded' }],
  },
  styles: {
    vocal: [{ id: 'plain', label: 'Melody only' }, { id: 'harmony', label: 'Add a harmony' }],
    melody: [{ id: 'follow', label: 'Follow the voice' }, { id: 'answer', label: 'Answer when the voice rests' }],
    guitar: [{ id: 'strum', label: 'Strum' }, { id: 'arpeggio', label: 'Picked chords' }, { id: 'muted', label: 'Muted strum' }, { id: 'sustain', label: 'Long notes only' }],
    bass: [{ id: 'sustain', label: 'Long notes' }, { id: 'groove', label: 'With the drums' }, { id: 'walking', label: 'Walking' }],
    drums: [{ id: 'brush', label: 'Brushes' }, { id: 'sticks', label: 'Sticks' }, { id: 'hand', label: 'Hand drum only' }],
    ambience: [{ id: 'recording', label: 'As recorded' }, { id: 'soft', label: 'Softer' }],
  },
  spaces: [{ id: 'dry', label: 'Dry' }, { id: 'room', label: 'Room' }, { id: 'hall', label: 'Hall' }],
  cardStyles: ['ink', 'comic', 'xieyi', 'original', 'text'],
}

export const labelOf = (list: { id: string; label: string }[] | undefined, id: string) => list?.find((x) => x.id === id)?.label ?? ''
export const instrumentLabel = (cat: Catalog, track: TrackId, id: string) => labelOf(cat.instruments[track], id) || labelOf(DEFAULT_CATALOG.instruments[track], id) || 'Default sound'
export const styleLabel = (cat: Catalog, track: TrackId, id: string) => labelOf(cat.styles[track], id) || labelOf(DEFAULT_CATALOG.styles[track], id) || ''

/** What the pad's edges mean for each player, in plain words: [soft, loud, simple, busy]. */
export const PAD_WORDS: Record<TrackId, [string, string, string, string]> = {
  vocal: ['soft', 'strong', 'plain', 'ornate'],
  melody: ['soft', 'loud', 'simple', 'decorated'],
  guitar: ['soft', 'loud', 'simple', 'busy'],
  bass: ['soft', 'loud', 'simple', 'walking'],
  drums: ['soft', 'loud', 'simple', 'busy'],
  ambience: ['far', 'near', 'steady', 'rolling'],
}
export const STYLE_TITLE: Record<TrackId, string> = { vocal: 'Voice', melody: 'How it plays', guitar: 'Playing style', bass: 'Playing style', drums: 'Drumming', ambience: 'Sound' }
