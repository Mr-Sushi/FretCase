import type { SharePage, Song } from '../types'
import { sectionLines } from '../lib/lyrics'
import { barTicks, sectionRange } from '../lib/song'

export interface PageLine { text: string; from: number; to: number }
export interface PageModel {
  title: string
  subtitle?: string
  /** "Edinburgh · 19 November 2026": the city appears only when the page JSON has one. */
  meta: string
  photos: string[]
  card?: string
  message?: string
  line?: string
  lyrics: { section: string; lines: PageLine[] }[]
  sections: { id: string; label: string; startTick: number; endTick: number }[]
}

export function formatDate(iso?: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : ''
}

/**
 * Everything the song page shows, taken from the page JSON and nothing else: no seed, no city unless `city` is given,
 * no photos unless `photos` lists them. The song is only used for timing (which line is sung when).
 */
export function buildModel(page: SharePage, song: Song): PageModel {
  const bt = barTicks(song.meter)
  const sections = song.sections.map((s) => ({ id: s.id, label: s.label, startTick: s.startBar * bt, endTick: s.endBar * bt }))
  const lyrics = page.lyrics.map((group, gi) => {
    const sec = song.sections.find((s) => s.label === group.section) ?? song.sections[gi]
    const timed = sec ? sectionLines(song, sec.id) : []
    const range = sec ? sectionRange(song, sec) : { from: 0, to: 0 }
    const even = (range.to - range.from) / Math.max(1, group.lines.length)
    return {
      section: group.section,
      lines: group.lines.map((text, i): PageLine => timed.length === group.lines.length
        ? { text, from: timed[i].fromTick, to: i + 1 < timed.length ? timed[i + 1].fromTick : range.to }
        : { text, from: Math.round(range.from + i * even), to: Math.round(range.from + (i + 1) * even) }),
    }
  })
  return {
    title: page.title,
    ...(page.subtitle ? { subtitle: page.subtitle } : {}),
    meta: [page.city, formatDate(page.date)].filter(Boolean).join(' · '),
    photos: page.photos ?? [],
    ...(page.card ? { card: page.card } : {}),
    ...(page.message ? { message: page.message } : {}),
    ...(page.line ? { line: page.line } : {}),
    lyrics, sections,
  }
}

/** Index (over all lines in order) of the line being sung at `tick`: the last one that has started, or -1 before the first. */
export function currentLineIndex(model: PageModel, tick: number): number {
  const all = model.lyrics.flatMap((g) => g.lines)
  let cur = -1
  all.forEach((l, i) => { if (tick >= l.from) cur = i })
  return cur
}
export const currentSectionIndex = (model: PageModel, tick: number) => Math.max(0, model.sections.findIndex((s) => tick >= s.startTick && tick < s.endTick))

/** The share id from `/s/{shareId}` or `?share=`. */
export function shareIdFromLocation(loc: { pathname: string; search: string }): string | null {
  const m = /\/s\/([A-Za-z0-9_-]{10,32})/.exec(loc.pathname)
  return m?.[1] ?? new URLSearchParams(loc.search).get('share')
}
