import type { Song, TrackId } from '../types'
import { TRACKS, isLocked } from '../lib/song'

export const RING_PIXELS = 16
export const RING_ACCENT = '#e08a12'
const RING_BAR = '#8a6a44'
const RING_LOCKED = '#3a2a1c'

/**
 * 16 lights clockwise from the top: one pixel per group of bars (fewer bars than lights: one bar spans several),
 * the current position in the accent colour, locked sections dimmed.
 */
export function computeRing(song: Pick<Song, 'bars' | 'sections' | 'locks'> | null, positionBar: number): (string | null)[] {
  if (!song) return Array(RING_PIXELS).fill(null)
  const current = Math.min(RING_PIXELS - 1, Math.floor((positionBar / song.bars) * RING_PIXELS))
  return Array.from({ length: RING_PIXELS }, (_, i) => {
    if (i === current) return RING_ACCENT
    const bar = Math.min(song.bars - 1, Math.floor(((i + 0.5) / RING_PIXELS) * song.bars))
    const sec = song.sections.find((s) => bar >= s.startBar && bar < s.endBar)
    // A whole-section lock dims it; a track-only lock does not (the ring cannot show tracks).
    const locked = !!sec && song.locks.some((l) => l.section === sec.id && !l.track)
    return locked ? RING_LOCKED : RING_BAR
  })
}

export interface KeyLightMsg { id: string; mode: 'off' | 'on' | 'blink' | 'pulse'; color?: string }

function dim(hex: string, f = 0.35): string {
  const n = parseInt(hex.slice(1), 16)
  const c = (v: number) => Math.round(v * f).toString(16).padStart(2, '0')
  return `#${c((n >> 16) & 255)}${c((n >> 8) & 255)}${c(n & 255)}`
}

export interface LightState {
  song: Song | null
  selected: TrackId | null
  recording: boolean
  busy: boolean
  playing: boolean
}

/** Light of every key for the current state. Selected track: full colour; others dimmer; muted: off. */
export function computeKeyLights(s: LightState): KeyLightMsg[] {
  const lights: KeyLightMsg[] = [
    { id: 'capture', mode: s.recording ? 'blink' : s.busy ? 'pulse' : 'on', color: '#d64533' },
    { id: 'play', mode: s.playing ? 'on' : 'off', color: '#f1e6cf' },
    { id: 'undo', mode: 'on', color: '#f1e6cf' },
    { id: 'another', mode: s.busy ? 'pulse' : 'on', color: '#f1e6cf' },
  ]
  for (const t of TRACKS) {
    const tr = s.song?.tracks[t.id]
    if (!tr || tr.muted) lights.push({ id: `track.${t.id}`, mode: 'off', color: t.color })
    else lights.push({ id: `track.${t.id}`, mode: 'on', color: s.selected === t.id || s.selected === null ? t.color : dim(t.color) })
  }
  return lights
}

export const lockedTrack = (song: Song, t: TrackId) => isLocked(song, t, null)
