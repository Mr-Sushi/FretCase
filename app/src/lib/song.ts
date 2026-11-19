import type { Key, Meter, Note, Section, Song, TrackId } from '../types'

export const TPQ = 480

export const TRACKS: { id: TrackId; name: string; color: string }[] = [
  { id: 'vocal', name: '人声', color: '#E2725B' },
  { id: 'melody', name: '旋律', color: '#E3A44A' },
  { id: 'guitar', name: '吉他', color: '#4FB3A6' },
  { id: 'bass', name: '贝斯', color: '#6C93D6' },
  { id: 'drums', name: '鼓', color: '#A98BD8' },
  { id: 'ambience', name: '环境', color: '#86B068' },
]
export const TRACK_IDS = TRACKS.map((t) => t.id)
export const trackColor = (id: TrackId) => TRACKS.find((t) => t.id === id)!.color
export const trackName = (id: TrackId) => TRACKS.find((t) => t.id === id)!.name

export const barTicks = (m: Meter) => Math.round((TPQ * 4 * m.numerator) / m.denominator)
export const songTicks = (s: Pick<Song, 'meter' | 'bars'>) => barTicks(s.meter) * s.bars

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function sectionAtBar(sections: Section[], bar: number): Section | undefined {
  const b = Math.floor(bar)
  return sections.find((s) => b >= s.startBar && b < s.endBar) ?? (b >= 0 ? sections[sections.length - 1] : sections[0])
}

export function sectionRange(song: Pick<Song, 'meter'>, s: Section): { from: number; to: number } {
  const bt = barTicks(song.meter)
  return { from: s.startBar * bt, to: s.endBar * bt }
}

export function isLocked(song: Pick<Song, 'locks'>, track: TrackId | null, sectionId: string | null): boolean {
  return song.locks.some((l) => {
    if (l.track && l.section) return l.track === track && l.section === sectionId
    if (l.track) return l.track === track
    if (l.section) return l.section === sectionId
    return false
  })
}

export const hasExactLock = (song: Pick<Song, 'locks'>, track?: TrackId, section?: string) =>
  song.locks.some((l) => l.track === track && l.section === section)

// ---- pitch helpers -------------------------------------------------------------------------

const PC: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }
export function tonicPc(tonic: string): number {
  let pc = PC[tonic[0]]
  if (tonic[1] === '#') pc += 1
  if (tonic[1] === 'b') pc -= 1
  return (pc + 12) % 12
}
const MAJOR = [0, 2, 4, 5, 7, 9, 11]
const MINOR = [0, 2, 3, 5, 7, 8, 10]
export function scalePcs(key: Key): Set<number> {
  const t = tonicPc(key.tonic)
  return new Set((key.mode === 'major' ? MAJOR : MINOR).map((i) => (i + t) % 12))
}
/** Nearest pitch that belongs to the key, preferring the original pitch, then the lower neighbour. */
export function snapToKey(pitch: number, key: Key): number {
  const pcs = scalePcs(key)
  for (let d = 0; d <= 6; d++) {
    if (pcs.has(((pitch - d) % 12 + 12) % 12)) return pitch - d
    if (pcs.has(((pitch + d) % 12 + 12) % 12)) return pitch + d
  }
  return pitch
}
const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
export const noteName = (p: number) => `${NAMES[p % 12]}${Math.floor(p / 12) - 1}`
export const midiToHz = (p: number) => 440 * Math.pow(2, (p - 69) / 12)

export function notesInRange<N extends Note>(notes: N[], from: number, to: number): N[] {
  return notes.filter((n) => n.start >= from && n.start < to)
}

export function trackNotes(song: Song, track: TrackId): Note[] {
  if (track === 'ambience') return []
  return song.tracks[track].notes
}

export const barOfTick = (song: Pick<Song, 'meter'>, tick: number) => tick / barTicks(song.meter)

export const sectionById = (song: Pick<Song, 'sections'>, id: string | null | undefined) => song.sections.find((s) => s.id === id)
export const regionOf = (song: Song, track: TrackId, sectionId: string) => song.tracks[track].regions.find((r) => r.section === sectionId)
export const trackLabelSound = (song: Song, track: TrackId) => song.tracks[track].instrument

/** Seconds of the whole song. */
export function songSeconds(song: Pick<Song, 'meter' | 'bars' | 'tempo'>): number {
  return (songTicks(song) / TPQ) * (60 / song.tempo)
}
export const ticksToSeconds = (ticks: number, tempo: number) => (ticks / TPQ) * (60 / tempo)
export const secondsToTicks = (sec: number, tempo: number) => Math.round((sec * tempo * TPQ) / 60)

/** "1 分 40 秒" */
export function formatLong(sec: number): string {
  const s = Math.round(sec)
  return s >= 60 ? `${Math.floor(s / 60)} 分 ${s % 60} 秒` : `${s} 秒`
}
/** "1:40" */
export function formatClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** Where a candidate preview starts: the vocal-led section, else the middle of the song. */
export function previewStartTick(song: Song): number {
  const bt = barTicks(song.meter)
  const lead = song.sections.find((s) => s.lead === 'vocal')
  if (lead) return lead.startBar * bt
  return Math.floor(song.bars / 2) * bt
}
