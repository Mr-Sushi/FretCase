import { describe, expect, it } from 'vitest'
import example from '../generated/example-song.json'
import type { Song } from '../types'
import { buildSchedule, diffForPlayback, faderGain, loopRangeFor, songEndTick } from './schedule'

const song = () => JSON.parse(JSON.stringify(example)) as Song

describe('buildSchedule', () => {
  it('lists every pitched and drum note in time order, with the ambience clip', () => {
    const s = song()
    const sch = buildSchedule(s)
    const expected = (['vocal', 'melody', 'guitar', 'bass', 'drums'] as const).reduce((n, t) => n + s.tracks[t].notes.length, 0)
    expect(sch.notes).toHaveLength(expected)
    expect(sch.notes.map((n) => n.tick)).toEqual([...sch.notes.map((n) => n.tick)].sort((a, b) => a - b))
    expect(sch.clips).toEqual([{ assetId: 'a-waves-01', tick: 0, duration: 30720, offsetSec: 0, loop: true, gain: 0.8 }])
    expect(sch.endTick).toBe(16 * 1920)
  })

  it('drops notes beyond the end and clips the ambience clip to the song', () => {
    const s = song()
    s.bars = 4
    s.tracks.bass.notes.push({ start: 4 * 1920 + 10, duration: 100, pitch: 40 })
    const sch = buildSchedule(s)
    expect(sch.notes.some((n) => n.tick >= songEndTick(s))).toBe(false)
    expect(sch.clips[0].duration).toBe(4 * 1920)
  })

  it('uses a rendered vocal instead of the vocal notes', () => {
    const s = song()
    s.tracks.vocal.renderAssetId = 'a-vocal-01'
    const sch = buildSchedule(s)
    expect(sch.vocalAssetId).toBe('a-vocal-01')
    expect(sch.notes.some((n) => n.track === 'vocal')).toBe(false)
  })

  it('handles meters with other bar lengths', () => {
    expect(songEndTick({ meter: { numerator: 6, denominator: 8 }, bars: 8 })).toBe(8 * 1440)
    expect(songEndTick({ meter: { numerator: 3, denominator: 4 }, bars: 8 })).toBe(8 * 1440)
    expect(songEndTick({ meter: { numerator: 2, denominator: 4 }, bars: 8 })).toBe(8 * 960)
  })
})

describe('gain and loop', () => {
  it('maps fader to a squared gain and mute to zero', () => {
    expect(faderGain(1, false)).toBe(1)
    expect(faderGain(0.5, false)).toBeCloseTo(0.25)
    expect(faderGain(0.9, true)).toBe(0)
    expect(faderGain(2, false)).toBe(1)
  })

  it('loops the section under the play position', () => {
    const s = song()
    expect(loopRangeFor(s, 's-verse')).toEqual({ from: 4 * 1920, to: 8 * 1920 })
    expect(loopRangeFor(s, 'nope')).toBeNull()
    expect(loopRangeFor(s, null)).toBeNull()
  })
})

describe('diffForPlayback', () => {
  it('a fader or mute change does not rebuild the schedule', () => {
    const a = song(), b = song()
    b.tracks.drums.volume = 0.3
    b.tracks.bass.muted = true
    b.revision++
    expect(diffForPlayback(a, b)).toEqual({ rebuild: false, gains: true, tempo: false })
  })
  it('a moved note or a new instrument rebuilds', () => {
    const a = song(), b = song()
    b.tracks.melody.notes[0].pitch += 2
    expect(diffForPlayback(a, b).rebuild).toBe(true)
    const c = song()
    c.tracks.guitar.instrument = 'steel'
    expect(diffForPlayback(a, c).rebuild).toBe(true)
  })
  it('tempo alone only changes the tempo', () => {
    const a = song(), b = song()
    b.tempo = 100
    expect(diffForPlayback(a, b)).toEqual({ rebuild: false, gains: false, tempo: true })
  })
  it('first load rebuilds everything', () => {
    expect(diffForPlayback(null, song())).toEqual({ rebuild: true, gains: true, tempo: true })
  })
})
