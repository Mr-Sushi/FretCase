import type { Song, VocalNote } from '../types'
import { sectionRange } from './song'
import { FINAL_CHARS } from './finals'

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
      text: cur.map((n) => n.lyric ?? '').join(''),
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

/** Syllables of typed text: spaces and punctuation are ignored, one per character. */
export function syllables(text: string): string[] {
  return [...text].filter((ch) => /[\p{L}\p{N}]/u.test(ch))
}

export interface LineCount { chars: number; notes: number; ok: boolean; diff: number; label: string; hint: string }

/** "8 字 / 8 个音" and whether it fits. */
export function countLine(text: string, noteCount: number): LineCount {
  const chars = syllables(text).length
  const diff = chars - noteCount
  return {
    chars, notes: noteCount, ok: diff === 0, diff,
    label: `${chars} 字 / ${noteCount} 个音`,
    hint: diff === 0 ? '正好' : diff > 0 ? `多 ${diff} 字` : `少 ${-diff} 字`,
  }
}

// ---- rhyme ------------------------------------------------------------------------------------

const FINAL_OF = new Map<string, string>()
for (const [f, chars] of Object.entries(FINAL_CHARS)) for (const ch of chars) FINAL_OF.set(ch, f)
// A few very common lyric characters whose first reading is not the sung one.
for (const [ch, f] of Object.entries({ 了: 'e', 的: 'e', 地: 'i', 得: 'e', 着: 'e', 啦: 'a', 吧: 'a', 呀: 'a', 啊: 'a', 呢: 'e', 嘛: 'a' })) FINAL_OF.set(ch, f)

/** Pinyin final without tone, or null for a character that is not in the small table. */
export function finalOf(ch: string): string | null { return FINAL_OF.get(ch) ?? null }

/** The thirteen traditional rhyme groups: finals that rhyme together. */
const RHYME_GROUPS: Record<string, string[]> = {
  zhongdong: ['eng', 'ing', 'ong', 'iong'],
  jiangyang: ['ang', 'iang', 'uang'],
  yanqian: ['an', 'ian', 'uan', 'van'],
  renchen: ['en', 'in', 'un', 'vn'],
  fahua: ['a', 'ia', 'ua'],
  suobo: ['o', 'e', 'uo'],
  yexie: ['ie', 've', 'ue'],
  huailai: ['ai', 'uai'],
  huidui: ['ei', 'ui'],
  yaotiao: ['ao', 'iao'],
  youqiu: ['ou', 'iu'],
  yiqi: ['i', 'v', 'er'],
  gusu: ['u'],
}
const GROUP_OF = new Map<string, string>()
for (const [g, fs] of Object.entries(RHYME_GROUPS)) for (const f of fs) GROUP_OF.set(f, g)
export const rhymeGroup = (final: string | null) => (final ? GROUP_OF.get(final) ?? final : null)

/** Last sung character of a line. */
export const lastChar = (text: string) => syllables(text).slice(-1)[0] ?? ''

/** "韵脚 an", or "韵脚 —" when the character is unknown. */
export function rhymeLabel(text: string): string {
  const f = finalOf(lastChar(text))
  return f ? `韵脚 ${f === 'v' ? 'ü' : f}` : '韵脚 —'
}

/** One plain sentence about how the lines of a section end. */
export function rhymeNote(texts: string[]): { text: string; good: boolean } {
  const ends = texts.map(lastChar).filter(Boolean)
  if (ends.length < 2) return { text: '', good: true }
  if (ends.every((e) => e === ends[0])) return { text: `每句都以“${ends[0]}”结尾，可以换一个`, good: false }
  const finals = ends.map(finalOf)
  const groups = finals.map(rhymeGroup)
  if (groups.every((g) => g && g === groups[0])) {
    const uniq = [...new Set(finals)]
    return { text: uniq.length > 1 ? `${uniq.join(' / ')} 押韵，很顺` : `都押 ${uniq[0]}，很顺`, good: true }
  }
  return { text: '句尾的韵不一样', good: false }
}
