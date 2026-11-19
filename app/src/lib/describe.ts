import type { Catalog, Song, TrackId } from '../types'
import { TRACKS, regionOf } from './song'
import { instrumentLabel } from './catalog'

const PLAIN: Record<TrackId, string> = { vocal: '人声', melody: '旋律', guitar: '吉他', bass: '贝斯', drums: '鼓', ambience: '环境声' }

/** Name used in a sentence about who plays: the player's own word, or the sound's short label. */
function who(song: Song, cat: Catalog, track: TrackId): string {
  const cand = song.candidate?.parts?.[track]?.sound
  if (track === 'ambience') return cand && cand !== '原声' ? cand : '环境声'
  if (track === 'melody') return instrumentLabel(cat, 'melody', song.tracks.melody.instrument)
  return PLAIN[track]
}

/** Who plays in a section, as a plain sentence built from the regions: "只有吉他和海浪". */
export function describeSection(song: Song, cat: Catalog, sectionId: string): string {
  const all = TRACKS.map((t) => t.id).filter((t) => regionOf(song, t, sectionId)?.play !== false)
  const sec = song.sections.find((s) => s.id === sectionId)
  const lead = sec?.lead && all.includes(sec.lead) ? sec.lead : null
  // The lead is named once, at the front, with the same word the list would use.
  const playing = lead ? all.filter((t) => t !== lead) : all
  let base: string
  const names = playing.map((t) => who(song, cat, t))
  if (lead) {
    const head = `${who(song, cat, lead)}领着`
    if (playing.length === 0) return `只有${who(song, cat, lead)}`
    if (playing.length === 5) return `${head}，大家一起上`
    const rest = playing.length === 1 ? names[0] : `${names.slice(0, -1).join('、')}和${names[names.length - 1]}`
    return `${head}，${rest}跟着`
  }
  if (playing.length === 0) base = '这一段很安静'
  else if (playing.length === 1) base = `只有${names[0]}`
  else if (playing.length === 2) base = `只有${names[0]}和${names[1]}`
  else if (playing.length === 6) base = '大家一起上'
  else base = `${names.slice(0, -1).join('、')}和${names[names.length - 1]}一起`
  return base
}
