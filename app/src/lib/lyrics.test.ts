import { describe, expect, it } from 'vitest'
import exampleSong from '../generated/example-song.json'
import type { Song } from '../types'
import { countLine, joinSyllables, rhymeLabel, rhymeNote, sectionLines, syllables } from './lyrics'
import { describeSection } from './describe'
import { DEFAULT_CATALOG } from './catalog'
import { buildMockSong, VARIANT_SETS } from '../api/mockSong'

const song = buildMockSong(null, VARIANT_SETS[0][0], 'grp-test-0001', 0, 'dusk', 'Edinburgh') as Song

describe('lyric lines', () => {
  it('are whole lines taken from the vocal notes, never one syllable per note', () => {
    const lines = sectionLines(song, 's-chorus')
    expect(lines.map((l) => l.text)).toEqual(['I sing my longing to the sea', 'The wind sings it back to me'])
    expect(lines.map((l) => l.noteCount)).toEqual([8, 7])
    expect(sectionLines(song, 's-intro')).toEqual([]) // the vocal does not play in the intro
  })

  it('a section without lineEnd marks is one line', () => {
    const s = JSON.parse(JSON.stringify(exampleSong)) as Song
    for (const n of s.tracks.vocal.notes) delete n.lineEnd
    const lines = sectionLines(s, 's-intro')
    expect(lines).toHaveLength(1)
    expect(lines[0].noteCount).toBe(6)
  })
})

describe('counting', () => {
  it('counts sung syllables and ignores punctuation and spaces', () => {
    expect(syllables('I sing my, longing to the sea!')).toEqual(['I', 'sing', 'my', 'long-', 'ing', 'to', 'the', 'sea'])
    expect(countLine('I sing my longing to the sea', 8)).toMatchObject({ ok: true, label: '8 syl / 8 notes', hint: 'fits' })
    expect(countLine('The wind sings it back to me', 6)).toMatchObject({ ok: false, label: '7 syl / 6 notes', hint: '1 too many' })
    expect(countLine('Far away', 6)).toMatchObject({ ok: false, hint: '3 too few' })
  })
  it('a hyphen typed by the user forces a break, and joining removes it again', () => {
    expect(syllables('Walk-ing home')).toEqual(['Walk-', 'ing', 'home'])
    expect(joinSyllables(['walk-', 'ing', 'home'])).toBe('walking home')
    expect(joinSyllables(syllables('And one by one the lights come on'))).toBe('And one by one the lights come on')
  })
})

describe('rhyme labels', () => {
  it('names the ending sound of the last word', () => {
    expect(rhymeLabel('I sing my longing to the sea')).toBe('rhyme -ee')
    expect(rhymeLabel('123')).toBe('rhyme —')
    expect(rhymeLabel('And I walk home tonight')).toBe('rhyme -ight')
    expect(rhymeLabel('Walking home')).toBe('rhyme -ome')
  })
  it('notices rhymes, missing rhymes and a repeated last word', () => {
    expect(rhymeNote(['I sing my longing to the sea', 'The wind sings it back to me'])).toEqual({ text: 'The lines rhyme on -ee', good: true })
    expect(rhymeNote(['The sea wind blows across the shore', 'And one by one the lights come on']).good).toBe(false)
    expect(rhymeNote(['Far away the lamps light', 'And I walk home tonight'])).toEqual({ text: 'The lines rhyme on -ight', good: true })
    expect(rhymeNote(['A kite', 'The light']).good).toBe(true)
    expect(rhymeNote(['A bit', 'The light']).good).toBe(false)
    expect(rhymeNote(['go home', 'go home'])).toEqual({ text: 'Every line ends on “home”; try another word', good: false })
  })
})

describe('what plays in a section, in plain words', () => {
  it('is built from the regions', () => {
    const s = JSON.parse(JSON.stringify(song)) as Song
    for (const t of Object.values(s.tracks)) for (const r of t.regions) if (r.section === 's-intro') r.play = false
    s.tracks.guitar.regions[0].play = true
    s.tracks.ambience.regions[0].play = true
    expect(describeSection(s, DEFAULT_CATALOG, 's-intro')).toBe('Only the guitar and the waves')
    s.tracks.guitar.regions[0].play = false
    expect(describeSection(s, DEFAULT_CATALOG, 's-intro')).toBe('Only the waves')
    for (const t of Object.values(s.tracks)) t.regions[2].play = true
    expect(describeSection(s, DEFAULT_CATALOG, 's-chorus')).toContain('The voice leads')
    expect(describeSection(s, DEFAULT_CATALOG, 's-chorus')).toContain('everyone joins in')
  })
})

describe('the lead in the section sentence', () => {
  it('is named once, with the same word as the list', () => {
    const s = JSON.parse(JSON.stringify(song)) as Song
    for (const t of Object.values(s.tracks)) t.regions[2].play = false
    s.tracks.guitar.regions[2].play = true
    s.tracks.vocal.regions[2].play = true
    s.tracks.bass.regions[2].play = true
    s.sections[2].lead = 'guitar'
    const text = describeSection(s, DEFAULT_CATALOG, 's-chorus')
    expect(text).toBe('The guitar leads, the voice and the bass follow')
    expect(text.split('guitar').length - 1).toBe(1)
  })
})
