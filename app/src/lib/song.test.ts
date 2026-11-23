import { describe, expect, it } from 'vitest'
import { buildMockSong, VARIANT_SETS } from '../api/mockSong'
import { songEnergy, songFeel } from './song'

const demo = (i: number, tod: 'day' | 'dusk' | 'night' = 'dusk') => buildMockSong(null, VARIANT_SETS[0][i], 'grp-t', i, tod, 'Edinburgh')

describe('the feel of a song', () => {
  it('tells the three demo songs apart: easy-going, upbeat and calm', () => {
    expect([0, 1, 2].map((i) => songFeel(demo(i)).id)).toEqual(['easy', 'upbeat', 'calm'])
  })
  it('rises with the tempo', () => {
    const slow = demo(0), fast = { ...demo(0), tempo: 132 }
    expect(songEnergy(fast)).toBeGreaterThan(songEnergy(slow))
  })
  it('falls when the drums stop or a strum becomes long notes', () => {
    const song = demo(1)
    const quiet = structuredClone(song)
    quiet.tracks.drums.muted = true
    for (const r of quiet.tracks.guitar.regions) r.style = 'sustain'
    expect(songEnergy(quiet)).toBeLessThan(songEnergy(song))
  })
  it('gives every feel a colour and a word, so the colour is never the only sign', () => {
    for (const tempo of [50, 80, 100, 120, 160]) {
      const f = songFeel({ ...demo(1), tempo })
      expect(f.color).toMatch(/^#[0-9A-F]{6}$/i)
      expect(f.label.length).toBeGreaterThan(2)
    }
  })
})
