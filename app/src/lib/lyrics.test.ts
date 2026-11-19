import { describe, expect, it } from 'vitest'
import exampleSong from '../generated/example-song.json'
import type { Song } from '../types'
import { countLine, finalOf, rhymeGroup, rhymeLabel, rhymeNote, sectionLines, syllables } from './lyrics'
import { describeSection } from './describe'
import { DEFAULT_CATALOG } from './catalog'
import { buildMockSong, VARIANT_SETS } from '../api/mockSong'

const song = buildMockSong(null, VARIANT_SETS[0][0], 'grp-test-0001', 0, 'dusk', '厦门') as Song

describe('lyric lines', () => {
  it('are whole lines taken from the vocal notes, never one character per note', () => {
    const lines = sectionLines(song, 's-chorus')
    expect(lines.map((l) => l.text)).toEqual(['我把想家唱给海听', '它把回答还给风'])
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
  it('counts characters and ignores punctuation and spaces', () => {
    expect(syllables('我把 想家，唱给海听！')).toHaveLength(8)
    expect(countLine('我把想家唱给海听', 8)).toMatchObject({ ok: true, label: '8 字 / 8 个音', hint: '正好' })
    expect(countLine('灯一盏一盏亮起来', 7)).toMatchObject({ ok: false, label: '8 字 / 7 个音', hint: '多 1 字' })
    expect(countLine('远方的灯', 6)).toMatchObject({ ok: false, hint: '少 2 字' })
  })
})

describe('rhyme labels', () => {
  it('finds the final of the last syllable', () => {
    expect(finalOf('岸')).toBe('an')
    expect(finalOf('来')).toBe('ai')
    expect(finalOf('听')).toBe('ing')
    expect(finalOf('风')).toBe('eng')
    expect(finalOf('了')).toBe('e')
    expect(rhymeLabel('海风吹过傍晚的岸')).toBe('韵脚 an')
    expect(rhymeLabel('abc')).toBe('韵脚 —')
  })
  it('ing and eng rhyme, an and ai do not', () => {
    expect(rhymeGroup('ing')).toBe(rhymeGroup('eng'))
    expect(rhymeGroup('an')).not.toBe(rhymeGroup('ai'))
    expect(rhymeNote(['我把想家唱给海听', '它把回答还给风'])).toEqual({ text: 'ing / eng 押韵，很顺', good: true })
    expect(rhymeNote(['远方的灯亮了', '我也该回去了'])).toEqual({ text: '每句都以“了”结尾，可以换一个', good: false })
    expect(rhymeNote(['海风吹过傍晚的岸', '灯一盏一盏亮起来']).good).toBe(false)
  })
})

describe('what plays in a section, in plain words', () => {
  it('is built from the regions', () => {
    const s = JSON.parse(JSON.stringify(song)) as Song
    for (const t of Object.values(s.tracks)) for (const r of t.regions) if (r.section === 's-intro') r.play = false
    s.tracks.guitar.regions[0].play = true
    s.tracks.ambience.regions[0].play = true
    expect(describeSection(s, DEFAULT_CATALOG, 's-intro')).toBe('只有吉他和海浪')
    s.tracks.guitar.regions[0].play = false
    expect(describeSection(s, DEFAULT_CATALOG, 's-intro')).toBe('只有海浪')
    for (const t of Object.values(s.tracks)) t.regions[2].play = true
    expect(describeSection(s, DEFAULT_CATALOG, 's-chorus')).toContain('人声领着')
    expect(describeSection(s, DEFAULT_CATALOG, 's-chorus')).toContain('大家一起上')
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
    expect(text).toBe('吉他领着，人声和贝斯跟着')
    expect(text.split('吉他').length - 1).toBe(1)
  })
})
