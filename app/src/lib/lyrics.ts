import type { Song, VocalNote } from '../types'
import { sectionRange } from './song'

export interface LyricLine {
  index: number
  text: string
  /** Number of vocal notes in the line. */
  noteCount: number
  fromTick: number
  toTick: number
}

/** The lyric lines of one section, from the vocal notes: a line ends on a note with `lineEnd` (the rest is one last line). */
export function sectionLines(song: Song, sectionId: string): LyricLine[] {
  const sec = song.sections.find((s) => s.id === sectionId)
  if (!sec) return []
  const r = sectionRange(song, sec)
  const notes = song.tracks.vocal.notes
    .filter((n) => n.start >= r.from && n.start < r.to)
    .sort((a, b) => a.start - b.start)
  const lines: LyricLine[] = []
  let cur: VocalNote[] = []
  const flush = () => {
    if (!cur.length) return
    lines.push({
      index: lines.length,
      text: joinSyllables(cur.map((n) => n.lyric ?? '')),
      noteCount: cur.length,
      fromTick: cur[0].start,
      toTick: cur[cur.length - 1].start + cur[cur.length - 1].duration,
    })
    cur = []
  }
  for (const n of notes) { cur.push(n); if (n.lineEnd) flush() }
  flush()
  return lines
}

export const lyricsOfSong = (song: Song) => song.sections.map((s) => ({ section: s, lines: sectionLines(song, s.id) }))

// ---- syllables: the same rule as engine/fretcase_engine/editing.py ----------------------------------------

const CJK = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/
// Hyphens and apostrophes are not separators: a hyphen marks a syllable break, an apostrophe belongs to its word.
const PUNCTUATION = /[\s,，。、；;:：!！?？"“”‘（）()《》〈〉【】\[\]—…~～·]+/
const DIGRAPHS = new Set(['ch', 'sh', 'th', 'ph', 'wh', 'ck', 'gh', 'qu', 'wr', 'kn'])
const VOWELS = 'aeiouy'

/**
 * English syllables of one word, as sung one per note: every syllable but the last ends with "-", so
 * ["walk-", "ing"] reads back as "walking". A word written with hyphens ("fi-re") is split exactly there; other words
 * by a spelling rule that is right for most everyday words and can always be overridden with a hyphen.
 */
export function wordSyllables(word: string): string[] {
  if (word.includes('-')) {
    const parts = word.split('-').filter(Boolean)
    return parts.map((p, i) => (i < parts.length - 1 ? p + '-' : p))
  }
  const low = word.toLowerCase()
  let runs: [number, number][] = [...low.matchAll(/[aeiouy]+/g)].map((m) => [m.index!, m.index! + m[0].length])
  if (runs.length && runs[0][0] === 0 && low[0] === 'y' && runs[0][1] > 1) runs[0] = [1, runs[0][1]]
  else if (runs.length && runs[0][0] === 0 && runs[0][1] === 1 && low[0] === 'y' && low.length > 1) runs = runs.slice(1)
  if (low.endsWith('ing') && low.length > 3 && VOWELS.includes(low[low.length - 4]) && runs.length && runs[runs.length - 1][0] < low.length - 3) {
    const [start, end] = runs[runs.length - 1]
    runs.splice(runs.length - 1, 1, [start, low.length - 3], [low.length - 3, end]) // "go-ing"
  }
  if (runs.length > 1) {
    const last = runs[runs.length - 1]
    const tail = low.slice(last[0])
    const before = last[0] > 0 ? low[last[0] - 1] : ''
    const silentE = tail === 'e' && !(before === 'l' && last[0] >= 2 && !VOWELS.includes(low[last[0] - 2]))
    const silentEd = tail === 'ed' && !'td'.includes(before)
    const silentEs = tail === 'es' && !'sxzgc'.includes(before) && !['ch', 'sh'].includes(low.slice(last[0] - 2, last[0]))
    if (silentE || silentEd || silentEs) runs = runs.slice(0, -1)
  }
  if (runs.length <= 1) return [word]
  const cuts: number[] = []
  for (let i = 0; i < runs.length - 1; i++) {
    const end = runs[i][1], start = runs[i + 1][0]
    const cluster = low.slice(end, start)
    if (cluster.length <= 1 || DIGRAPHS.has(cluster)) cuts.push(end) // "o-pen", "fa-ther"
    else if (DIGRAPHS.has(cluster.slice(-2))) cuts.push(start - 2) // "kit-chen"
    else cuts.push(end + 1) // "win-dow", "lit-tle"
  }
  if (low.endsWith('ing') && low.length > 4) cuts[cuts.length - 1] = low.length - 3 // "walk-ing"
  const bounds = [0, ...cuts, word.length]
  const pieces = bounds.slice(0, -1).map((a, i) => word.slice(a, bounds[i + 1]))
  return pieces.map((p, i) => (i < pieces.length - 1 ? p + '-' : p))
}

/** Lines of sung syllables in typed text: only line breaks start a new line, punctuation and spaces are ignored. */
export function syllableLines(text: string): string[][] {
  const lines: string[][] = []
  for (const raw of text.split(/[\n\r]+/)) {
    const out: string[] = []
    for (const token of raw.split(PUNCTUATION)) {
      let buf = ''
      for (const ch of token) {
        if (CJK.test(ch)) { if (buf) { out.push(...wordSyllables(buf)); buf = '' } out.push(ch) } else buf += ch
      }
      buf = buf.replace(/^['’]+|['’]+$/g, '')
      if (buf) out.push(...wordSyllables(buf))
    }
    if (out.length) lines.push(out)
  }
  return lines
}

/** Sung syllables of typed text, all lines together. */
export const syllables = (text: string): string[] => syllableLines(text).flat()

/** Sung syllables back to text: "walk-" + "ing" -> "walking", words separated by spaces. */
export function joinSyllables(parts: string[]): string {
  let out = ''
  for (const syl of parts) {
    if (!syl) continue
    if (out && !out.endsWith('-') && !CJK.test(syl[0]) && !CJK.test(out[out.length - 1])) out += ' '
    if (out.endsWith('-')) out = out.slice(0, -1)
    out += syl
  }
  return out.endsWith('-') ? out.slice(0, -1) : out
}

export interface LineCount { chars: number; notes: number; ok: boolean; diff: number; label: string; hint: string }

/** "8 syl / 8 notes" and whether it fits. */
export function countLine(text: string, noteCount: number): LineCount {
  const chars = syllables(text).length
  const diff = chars - noteCount
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`
  return {
    chars, notes: noteCount, ok: diff === 0, diff,
    label: `${chars} syl / ${plural(noteCount, 'note')}`,
    hint: diff === 0 ? 'fits' : diff > 0 ? `${diff} too many` : `${-diff} too few`,
  }
}

// ---- rhyme: by spelling, a hint rather than a rule ---------------------------------------------

/** Last sung word of a line. */
export const lastWord = (text: string) => joinSyllables(syllables(text)).split(' ').slice(-1)[0]?.toLowerCase() ?? ''

const OPEN_SOUNDS: [RegExp, string][] = [
  [/^(ee|ea|e|ie|ey)$/, 'ee'], [/^(ay|ai|ei)$/, 'ay'], [/^(o|oe|oa|ow)$/, 'oh'], [/^(oo|ue|ew|u|ou)$/, 'oo'], [/^(y|ye|ie|igh)$/, 'eye'],
]

/** The rhyming end of a word: its last vowel sound and what follows ("night" -> "ight"), or null. */
export function rhymeKey(word: string): string | null {
  let low = word.toLowerCase().replace(/[^a-z]/g, '')
  if (!low) return null
  if (/igh/.test(low.slice(-4))) low = low.replace(/igh(t?)$/, 'ite$1').replace(/itet$/, 'ite')
  const runs = [...low.matchAll(/[aeiouy]+/g)]
  if (!runs.length) return null
  let last = runs[runs.length - 1]
  // Silent e keeps the vowel long and stays in the key: "home" -> "ome", "light" -> "ite", "hop" -> "op".
  if (runs.length > 1 && low.endsWith('e') && last[0] === 'e' && last.index === low.length - 1) last = runs[runs.length - 2]
  const key = low.slice(last.index!)
  if (/^[aeiouy]+$/.test(key)) for (const [re, sound] of OPEN_SOUNDS) if (re.test(key)) return sound
  return key
}

/** The ending to show for a key: the word's own spelling where it differs only by "igh" ("ite" from "light" -> "ight"). */
function shownEnding(key: string, word: string): string {
  const m = word.toLowerCase().match(/igh(t?)$/)
  return m && key === 'ite' ? `igh${m[1]}` : key
}

/** "rhyme -ight", or "rhyme —" for a word without one. */
export function rhymeLabel(text: string): string {
  const w = lastWord(text)
  const k = rhymeKey(w)
  return k ? `rhyme -${shownEnding(k, w)}` : 'rhyme —'
}

/** One plain sentence about how the lines of a section end. */
export function rhymeNote(texts: string[]): { text: string; good: boolean } {
  const ends = texts.map(lastWord).filter(Boolean)
  if (ends.length < 2) return { text: '', good: true }
  if (ends.every((e) => e === ends[0])) return { text: `Every line ends on “${ends[0]}”; try another word`, good: false }
  const keys = ends.map(rhymeKey)
  if (keys.every((k) => k && k === keys[0])) return { text: `The lines rhyme on -${shownEnding(keys[0]!, ends[0])}`, good: true }
  return { text: 'The line endings do not rhyme', good: false }
}
