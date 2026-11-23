import exampleSong from '../generated/example-song.json'
import type { Note, Region, SeedCard, Song, TimeOfDay, TrackId, VocalNote } from '../types'
import { barTicks, clamp, isLocked, sectionRange, snapToKey } from '../lib/song'
import { instrumentLabel, DEFAULT_CATALOG } from '../lib/catalog'
import { syllables } from '../lib/lyrics'

/** Mock-mode song generator: builds a six-track song with one region per track and section. Not musically clever, but consistent. */

export const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))
export const rid = (n = 6) => Array.from({ length: n }, () => 'abcdefghjkmnpqrstuvwxyz23456789'[Math.floor(Math.random() * 31)]).join('')

const OPEN = [40, 45, 50, 55, 59, 64]
export const MOCK_LYRICS: Record<string, string[]> = {
  's-verse': ['The sea wind blows across the shore', 'And one by one the lights come on'],
  's-chorus': ['I sing my longing to the sea', 'The wind sings it back to me'],
  's-outro': ['Far away the lamps light', 'And I walk home tonight'],
}
/** Same-length wordings for the mock's "other wordings" and rewrites; keyed by syllable count. */
export const MOCK_POOL: Record<number, { text: string; note: string }[]> = {
  8: [{ text: 'The salty wind along the shore', note: 'smoother' }, { text: 'The tide comes in across the shore', note: 'more images' }, { text: 'I tell the sea I miss my home', note: 'more direct' }, { text: 'I fold the wind into a boat', note: 'a new image' }],
  7: [{ text: 'And the lamps slowly come on', note: 'softer' }, { text: 'The sea sends it back to me', note: 'echoes the line before' }, { text: 'The wind keeps the answer now', note: 'more open' }, { text: 'It is the wind that answers', note: 'plainer' }],
  6: [{ text: 'Far away a light glows', note: 'a new ending' }, { text: 'The sea lights are on now', note: 'back to the sea' }, { text: 'It is time to go home', note: 'lands on home' }, { text: 'The wind blows me back home', note: 'rhymes on -ome' }],
}

export function defaultRegion(track: TrackId, section: string, play: boolean): Region {
  const style = { vocal: 'plain', melody: 'follow', guitar: 'strum', bass: 'sustain', drums: 'brush', ambience: 'recording' }[track]
  return { section, play, complexity: 0.5, intensity: 0.5, style }
}

function motifPitches(song: Song): number[] {
  const m = song.seed?.motif?.map((n) => n.pitch)
  return m && m.length ? m : [74, 76, 78, 76, 74, 71]
}

/** Notes of one track in one section, from its region. `take` varies the result for "another". */
export function genNotes(song: Song, track: TrackId, sectionId: string, take = 0): Note[] {
  const sec = song.sections.find((s) => s.id === sectionId)
  const region = song.tracks[track].regions.find((r) => r.section === sectionId)
  if (!sec || !region || !region.play || track === 'ambience') return []
  const { from, to } = sectionRange(song, sec)
  const bt = barTicks(song.meter)
  const vel = Math.round(50 + region.intensity * 60)
  const out: Note[] = []
  const chords = song.harmony.filter((h) => h.start >= from && h.start < to)
  const m = motifPitches(song)
  const degShift = [0, 2, -2, 4][take % 4]
  if (track === 'vocal' || track === 'melody') {
    const lyr = MOCK_LYRICS[sectionId]
    const lines = lyr ? lyr.map((t) => syllables(t)) : [Array(8).fill('la'), Array(7).fill('la')]
    const existing = track === 'melody' ? null : song.tracks.vocal.notes.filter((n) => n.start >= from && n.start < to)
    lines.forEach((chars, li) => {
      const t0 = from + li * 2 * bt
      chars.forEach((ch, i) => {
        const pitch = snapToKey(clamp(m[(i + li * 3) % m.length] + degShift + (track === 'melody' ? 0 : 0), 40, 100), song.key)
        const start = t0 + i * 480
        if (track === 'melody') {
          const answer = region.style === 'answer'
          if (answer && li === 0) return
          out.push({ start, duration: 480, pitch: pitch + (answer ? 12 : 0), velocity: vel })
        } else {
          const prior = existing?.[li * 8 + i]
          const n: VocalNote = { start, duration: 480, pitch, velocity: vel, lyric: prior?.lyric ?? ch }
          if (i === chars.length - 1) n.lineEnd = true
          out.push(n)
        }
      })
    })
    return out
  }
  for (const ch of chords) {
    const v = ch.voicing
    const pitches = v ? v.frets.map((f, i) => (f >= 0 ? OPEN[i] + f : -1)).filter((p) => p >= 0) : [50, 57, 62]
    if (track === 'guitar') {
      if (region.style === 'sustain') pitches.forEach((p, i) => out.push({ start: ch.start + i * 15, duration: ch.duration, pitch: p, velocity: vel }))
      else if (region.style === 'arpeggio') {
        const step = region.complexity < 0.5 ? 480 : 240
        for (let t = 0, k = take; t < ch.duration; t += step, k++) out.push({ start: ch.start + t, duration: step * 2, pitch: pitches[k % pitches.length], velocity: vel })
      } else {
        const step = region.complexity < 0.33 ? 960 : region.complexity < 0.67 ? 480 : 240
        for (let t = 0; t < ch.duration; t += step) pitches.forEach((p, i) => out.push({ start: ch.start + t + i * 12, duration: region.style === 'muted' ? 90 : step, pitch: p, velocity: Math.round(vel * (t % 960 === 0 ? 1 : 0.8)) }))
      }
    } else if (track === 'bass') {
      let root = Math.min(...pitches)
      while (root > 55) root -= 12
      while (root < 28) root += 12
      const fifth = root + 7
      if (region.style === 'sustain') out.push({ start: ch.start, duration: ch.duration, pitch: root, velocity: vel })
      else if (region.style === 'groove') for (let t = 0; t < ch.duration; t += 960) { out.push({ start: ch.start + t, duration: 720, pitch: root, velocity: vel }); if (region.complexity > 0.5) out.push({ start: ch.start + t + 720, duration: 240, pitch: fifth, velocity: vel - 10 }) }
      else for (let t = 0, k = 0; t < ch.duration; t += 480, k++) out.push({ start: ch.start + t, duration: 480, pitch: [root, fifth, root + 12, fifth][(k + take) % 4], velocity: vel })
    } else if (track === 'drums') {
      const hand = region.style === 'hand'
      const sticks = region.style === 'sticks'
      const soft = region.style === 'brush' ? 0.7 : 1
      for (let t = 0; t < ch.duration; t += 480) {
        const beat = (t / 480) % 4
        if (hand) { out.push({ start: ch.start + t, duration: 120, pitch: beat % 2 ? 39 : 36, velocity: vel }); continue }
        if (beat === 0 || beat === 2) out.push({ start: ch.start + t, duration: 120, pitch: 36, velocity: Math.round(vel * soft) })
        else out.push({ start: ch.start + t, duration: 120, pitch: 38, velocity: Math.round(vel * soft) })
        if (sticks || region.complexity > 0.5) out.push({ start: ch.start + t, duration: 60, pitch: 42, velocity: Math.round(vel * 0.6) })
        if (region.complexity > 0.5) out.push({ start: ch.start + t + 240, duration: 60, pitch: 42, velocity: Math.round(vel * 0.45) })
      }
    }
  }
  return out
}

export function replaceTrackSection(song: Song, track: TrackId, sectionId: string, take = 0) {
  if (track === 'ambience') return
  const sec = song.sections.find((s) => s.id === sectionId)!
  const { from, to } = sectionRange(song, sec)
  const tr = song.tracks[track] as { notes: Note[] }
  tr.notes = [...tr.notes.filter((n) => n.start < from || n.start >= to), ...genNotes(song, track, sectionId, take)].sort((a, b) => a.start - b.start || a.pitch - b.pitch)
}

export function regenerateUnlocked(song: Song, sectionId: string, track?: TrackId, take = 0) {
  const tracks = (track ? [track] : (['vocal', 'melody', 'guitar', 'bass', 'drums'] as TrackId[]))
  for (const t of tracks) if (!isLocked(song, t, sectionId)) replaceTrackSection(song, t, sectionId, take)
}

interface Variant {
  name: string; tags: string[]; why: string; tempo: number; lead: 'vocal' | 'melody' | 'guitar'
  inst: Record<TrackId, string>; style: Record<TrackId, string>
  play: Record<TrackId, boolean[]>; level: Record<TrackId, number>; amb: string; mode?: 'minor'
}
const T = true, F = false
export const VARIANT_SETS: Variant[][] = [
  [
    { name: 'Dusk Folk', tags: ['warm', 'slower', 'vocal-led'], why: 'The warm colours of your photo with a strummed steel-string guitar; the chorus sings your hum.', tempo: 1, lead: 'vocal',
      inst: { vocal: 'synth-male', melody: 'harmonica', guitar: 'steel', bass: 'finger-bass', drums: 'jazz-kit', ambience: 'recording' },
      style: { vocal: 'plain', melody: 'follow', guitar: 'strum', bass: 'sustain', drums: 'brush', ambience: 'recording' },
      play: { vocal: [F, T, T, T], melody: [T, T, T, T], guitar: [T, T, T, T], bass: [F, T, T, T], drums: [F, T, T, F], ambience: [T, T, T, T] },
      level: { vocal: 0.9, melody: 0.4, guitar: 0.8, bass: 0.5, drums: 0.35, ambience: 0.3 }, amb: 'Waves' },
    { name: 'Sea Breeze', tags: ['bright', 'medium', 'guitar-led'], why: 'Reads “very windy” as upbeat: picked nylon guitar leads, with busier drums.', tempo: 1.12, lead: 'guitar',
      inst: { vocal: 'synth-female', melody: 'flute', guitar: 'nylon', bass: 'finger-bass', drums: 'pop-kit', ambience: 'recording' },
      style: { vocal: 'plain', melody: 'follow', guitar: 'arpeggio', bass: 'groove', drums: 'sticks', ambience: 'recording' },
      play: { vocal: [F, T, T, T], melody: [T, T, T, T], guitar: [T, T, T, T], bass: [T, T, T, T], drums: [F, T, T, T], ambience: [T, F, T, T] },
      level: { vocal: 0.6, melody: 0.7, guitar: 0.9, bass: 0.6, drums: 0.7, ambience: 0.2 }, amb: 'Waves' },
    { name: 'Homesick Night', tags: ['quiet', 'slow', 'piano'], why: 'Holds on to “homesick”: piano instead of guitar, with the waves underneath.', tempo: 0.85, lead: 'melody',
      inst: { vocal: 'synth-soft', melody: 'piano', guitar: 'nylon', bass: 'upright-bass', drums: 'hand-drum', ambience: 'recording' },
      style: { vocal: 'plain', melody: 'follow', guitar: 'sustain', bass: 'sustain', drums: 'hand', ambience: 'soft' },
      play: { vocal: [F, T, T, T], melody: [T, T, T, T], guitar: [F, F, F, T], bass: [F, F, T, T], drums: [F, F, F, F], ambience: [T, T, T, T] },
      level: { vocal: 0.8, melody: 0.55, guitar: 0.2, bass: 0.35, drums: 0.1, ambience: 0.6 }, amb: 'Waves' },
  ],
  [
    { name: 'Cobbled Street', tags: ['nostalgic', 'medium', 'electric'], why: 'A different road: a muted strum underneath and a steadier beat.', tempo: 1.05, lead: 'guitar',
      inst: { vocal: 'synth-male', melody: 'whistle', guitar: 'electric-clean', bass: 'synth-bass', drums: 'pop-kit', ambience: 'recording' },
      style: { vocal: 'plain', melody: 'answer', guitar: 'muted', bass: 'groove', drums: 'sticks', ambience: 'recording' },
      play: { vocal: [F, T, T, T], melody: [T, T, T, T], guitar: [T, T, T, T], bass: [T, T, T, T], drums: [F, T, T, T], ambience: [T, T, F, T] },
      level: { vocal: 0.7, melody: 0.5, guitar: 0.85, bass: 0.65, drums: 0.6, ambience: 0.25 }, amb: 'Street' },
    { name: 'Afternoon Stroll', tags: ['easy', 'slow', 'ukulele'], why: 'Strummed ukulele, with a whistle answering the voice, like humming on a walk.', tempo: 0.95, lead: 'melody',
      inst: { vocal: 'synth-female', melody: 'whistle', guitar: 'ukulele', bass: 'upright-bass', drums: 'hand-drum', ambience: 'recording' },
      style: { vocal: 'plain', melody: 'answer', guitar: 'strum', bass: 'walking', drums: 'hand', ambience: 'soft' },
      play: { vocal: [F, T, T, T], melody: [T, T, T, T], guitar: [T, T, T, T], bass: [F, T, T, T], drums: [F, T, T, F], ambience: [T, T, T, T] },
      level: { vocal: 0.6, melody: 0.65, guitar: 0.7, bass: 0.5, drums: 0.4, ambience: 0.4 }, amb: 'Street' },
    { name: 'Walking Home Alone', tags: ['quiet', 'very slow', 'just a little'], why: 'Only the fewest instruments, so the tune you hummed stands in front.', tempo: 0.8, lead: 'vocal',
      inst: { vocal: 'synth-soft', melody: 'flute', guitar: 'steel', bass: 'finger-bass', drums: 'jazz-kit', ambience: 'recording' },
      style: { vocal: 'plain', melody: 'follow', guitar: 'arpeggio', bass: 'sustain', drums: 'brush', ambience: 'soft' },
      play: { vocal: [F, T, T, T], melody: [F, F, T, F], guitar: [T, T, T, T], bass: [F, F, T, T], drums: [F, F, F, F], ambience: [T, T, T, T] },
      level: { vocal: 0.85, melody: 0.3, guitar: 0.6, bass: 0.3, drums: 0.05, ambience: 0.5 }, amb: 'Rain' },
  ],
]

const TRACK_LIST: TrackId[] = ['vocal', 'melody', 'guitar', 'bass', 'drums', 'ambience']
const TOD_TEMPO: Record<TimeOfDay, number> = { day: 1.1, dusk: 1, night: 0.88 }

function titleFrom(seed: SeedCard): string {
  const text = seed.inputs.find((i) => i.kind === 'text')?.text?.trim()
  const first = text?.split(/[，。,.！!？?;:\n]/).map((c) => c.trim()).find(Boolean)
  if (first) return first.length <= 32 ? first : first.slice(0, 32).replace(/\s+\S*$/, '')
  return seed.mood ? `A ${seed.mood} song` : 'New song'
}

/** A full draft song for the pick screen (or the demo song), built from the example song. */
export function buildMockSong(seed: SeedCard | null, variant: Variant, groupId: string, index: number, tod: TimeOfDay | undefined, city: string): Song {
  const base = clone(exampleSong) as unknown as Song
  const now = new Date().toISOString()
  const song = base
  song.id = `song-${rid(8)}`
  song.revision = 0
  song.createdAt = now; song.updatedAt = now
  if (seed) {
    song.seed = clone(seed); song.key = seed.key; song.meter = seed.meter ?? base.meter
    song.title = titleFrom(seed)
  } else { song.title = 'Seaside at Dusk' }
  const baseTempo = seed?.tempo ?? base.tempo
  song.tempo = Math.round(clamp(baseTempo * variant.tempo * (tod ? TOD_TEMPO[tod] : 1), 40, 220))
  song.bars = 16
  song.sections = [
    { id: 's-intro', label: 'Intro', startBar: 0, endBar: 4 },
    { id: 's-verse', label: 'Verse', startBar: 4, endBar: 8 },
    { id: 's-chorus', label: 'Chorus', startBar: 8, endBar: 12, lead: variant.lead },
    { id: 's-outro', label: 'Outro', startBar: 12, endBar: 16 },
  ]
  song.locks = []
  song.controls = { brightness: tod === 'day' ? 0.75 : tod === 'night' ? 0.25 : 0.5, complexity: 0.5, density: 0.5 }
  song.master = { volume: 0.8, space: 'room' }
  for (const t of TRACK_LIST) {
    const tr = song.tracks[t]
    tr.instrument = variant.inst[t]
    tr.volume = t === 'drums' ? 0.5 : t === 'ambience' ? 0.5 : 0.8
    tr.muted = false
    tr.regions = song.sections.map((s, i) => {
      const r = defaultRegion(t, s.id, variant.play[t][i])
      r.style = variant.style[t]
      if (s.lead === t) r.intensity = 0.65
      return r
    })
    if (t !== 'ambience') (tr as { notes: Note[] }).notes = []
  }
  ;(song.tracks.guitar as { rhythm: { family: string; presetId: string } }).rhythm = variant.style.guitar === 'arpeggio' ? { family: 'arpeggio', presetId: 't321t321' } : song.tracks.guitar.rhythm
  song.tracks.vocal.source = 'none'
  delete (song.tracks.vocal as { renderAssetId?: string }).renderAssetId
  for (const t of TRACK_LIST) for (const s of song.sections) if (t !== 'ambience') replaceTrackSection(song, t, s.id)
  // Ambience: the recorded sound, if any.
  const amb = seed?.inputs.find((i) => i.kind === 'sound')?.assetId ?? (seed ? undefined : 'a-waves-01')
  song.tracks.ambience.clips = amb ? [{ assetId: amb, start: 0, duration: barTicks(song.meter) * 16, loop: true, gain: 0.8 }] : []
  // Assets and card.
  const inputs = seed?.inputs ?? base.seed!.inputs
  song.assets = seed ? [] : song.assets
  if (seed) for (const i of seed.inputs) if (i.assetId) song.assets.push({ id: i.assetId, role: i.kind === 'sound' ? 'ambience' : (i.kind as 'hum' | 'photo'), mime: 'application/octet-stream' })
  const photos = inputs.filter((i) => i.kind === 'photo' && i.assetId).map((i) => i.assetId!)
  const shareId = rid(12).padEnd(12, 'x')
  song.card = {
    style: photos.length ? 'xieyi' : 'text', line: '', photoAssetIds: photos as never, showPhoto: photos.length > 0, city, showCity: !!city,
    capturedAt: now, share: { shareId: seed ? shareId : 'k3Hq9xV2mPzT', url: `https://fretcase.example/s/${seed ? shareId : 'k3Hq9xV2mPzT'}`, state: 'reserved' },
  }
  const card = song.card
  if (photos.length) card.coverAssetId = photos[0]
  if (!seed) { card.line = 'The sea wind blows the evening into song'; card.message = 'I wrote you a song by the sea. I will sing it to you when I am back.'; card.city = 'Edinburgh' }
  const parts: Record<string, { level: number; sound: string }> = {}
  for (const t of TRACK_LIST) {
    const inst = instrumentLabel(DEFAULT_CATALOG, t, variant.inst[t])
    const st = ({ strum: 'strum', arpeggio: 'picked', muted: 'muted', sustain: 'long notes', brush: 'brushes', sticks: 'sticks', hand: '' } as Record<string, string>)[t === 'guitar' || t === 'drums' ? variant.style[t] : ''] ?? ''
    parts[t] = { level: variant.level[t], sound: t === 'ambience' ? variant.amb : (st ? `${inst}, ${st}` : inst).slice(0, 40) }
  }
  song.candidate = { groupId, index, name: variant.name, tags: variant.tags as never, why: variant.why, ...(tod ? { timeOfDay: tod } : {}), parts }
  delete song.provenance
  return song
}
