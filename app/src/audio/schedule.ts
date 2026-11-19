import type { Song, TrackId } from '../types'
import { TRACK_IDS, clamp, sectionRange } from '../lib/song'

/** One note or clip to be played, in song ticks (480 per quarter note). */
export interface NoteEvent { track: TrackId; tick: number; duration: number; pitch: number; velocity: number }
export interface ClipEvent { assetId: string; tick: number; duration: number; offsetSec: number; loop: boolean; gain: number }

export interface SongSchedule {
  notes: NoteEvent[]
  clips: ClipEvent[]
  /** Rendered or recorded vocal audio, aligned to tick 0; when present the vocal notes are not played. */
  vocalAssetId: string | null
  endTick: number
}

/** Pure: everything a song asks to be played. Mute and volume are not applied here (they are gains). */
export function buildSchedule(song: Song): SongSchedule {
  const end = songEndTick(song)
  const notes: NoteEvent[] = []
  const vocalAssetId = song.tracks.vocal.renderAssetId ?? null
  for (const track of TRACK_IDS) {
    if (track === 'ambience') continue
    if (track === 'vocal' && vocalAssetId) continue
    for (const n of song.tracks[track].notes) {
      if (n.start >= end) continue
      notes.push({ track, tick: n.start, duration: n.duration, pitch: n.pitch, velocity: ('velocity' in n && n.velocity) || 90 })
    }
  }
  notes.sort((a, b) => a.tick - b.tick)
  const clips: ClipEvent[] = song.tracks.ambience.clips
    .filter((c) => c.start < end)
    .map((c) => ({ assetId: c.assetId, tick: c.start, duration: Math.min(c.duration, end - c.start), offsetSec: c.offsetSec ?? 0, loop: c.loop, gain: c.gain ?? 1 }))
  return { notes, clips, vocalAssetId, endTick: end }
}

export function songEndTick(song: Pick<Song, 'meter' | 'bars'>): number {
  return Math.round((480 * 4 * song.meter.numerator) / song.meter.denominator) * song.bars
}

/** Fader position to linear gain: a gentle curve so the lower half of the fader is still useful. */
export function faderGain(volume: number, muted: boolean): number {
  if (muted) return 0
  const v = clamp(volume, 0, 1)
  return v * v
}

/** Tick range of a section, to loop while editing. */
export function loopRangeFor(song: Song, sectionId: string | null): { from: number; to: number } | null {
  if (!sectionId) return null
  const s = song.sections.find((x) => x.id === sectionId)
  return s ? sectionRange(song, s) : null
}

/**
 * What differs between two songs for playback purposes: whether the schedule has to be rebuilt
 * (notes, clips, instruments, meter) or only gains and tempo changed.
 */
export function diffForPlayback(prev: Song | null, next: Song): { rebuild: boolean; gains: boolean; tempo: boolean } {
  if (!prev) return { rebuild: true, gains: true, tempo: true }
  const sig = (s: Song) => JSON.stringify([
    s.id, s.meter, s.bars,
    TRACK_IDS.map((t) => s.tracks[t].instrument),
    TRACK_IDS.filter((t) => t !== 'ambience').map((t) => (s.tracks[t as Exclude<TrackId, 'ambience'>].notes)),
    s.tracks.ambience.clips, s.tracks.vocal.renderAssetId ?? null,
  ])
  const gainSig = (s: Song) => JSON.stringify(TRACK_IDS.map((t) => [s.tracks[t].volume, s.tracks[t].muted]))
  return { rebuild: sig(prev) !== sig(next), gains: gainSig(prev) !== gainSig(next), tempo: prev.tempo !== next.tempo }
}
