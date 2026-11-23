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
/** What each playing style does, in one plain line (the labels come from the catalogue). */
export const STYLE_HELP: Record<TrackId, Record<string, string>> = {
  vocal: { plain: 'One voice sings the tune', harmony: 'A second voice joins the tune' },
  melody: { follow: 'Plays the tune along with the voice', answer: 'Plays in the gaps, when the voice rests' },
  guitar: { strum: 'All the strings together, in a steady rhythm', arpeggio: 'The notes of each chord, one string at a time', muted: 'Short, damped strums, almost like a drum', sustain: 'Each chord played once and left to ring' },
  bass: { sustain: 'One long low note under each chord', groove: 'Short notes that move with the drums', walking: 'Steps from note to note, beat by beat' },
  drums: { brush: 'Soft, brushed strokes', sticks: 'A fuller beat, played with sticks', hand: 'Only a hand drum and a shaker' },
  ambience: { recording: 'The sound you recorded, as it is', soft: 'The same sound, quieter' },
}
/** Titles of the two "how much" choices for each player: [how many notes, how hard]. */
export const AXIS_TITLE: Record<TrackId, [string, string]> = {
  vocal: ['How fancy', 'How strong'], melody: ['How busy', 'How loud'], guitar: ['How busy', 'How loud'],
  bass: ['How busy', 'How loud'], drums: ['How busy', 'How loud'], ambience: ['Movement', 'How close'],
}
export const STYLE_TITLE: Record<TrackId, string> = { vocal: 'Voice', melody: 'How it plays', guitar: 'Playing style', bass: 'Playing style', drums: 'Drumming', ambience: 'Sound' }
