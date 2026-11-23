import type { Catalog, Song, TrackId } from '../types'
import { TRACKS, regionOf } from './song'
import { instrumentLabel } from './catalog'

const PLAIN: Record<TrackId, string> = { vocal: 'the voice', melody: 'the melody', guitar: 'the guitar', bass: 'the bass', drums: 'the drums', ambience: 'the ambience' }
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const list = (names: string[]) => (names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`)

/** Name used in a sentence about who plays: the player's own word, or the sound's short label. */
function who(song: Song, cat: Catalog, track: TrackId): string {
  const cand = song.candidate?.parts?.[track]?.sound
  if (track === 'ambience') return cand && cand !== 'As recorded' && cand !== 'Ambience' ? `the ${cand.toLowerCase()}` : 'the ambience'
  if (track === 'melody') return `the ${instrumentLabel(cat, 'melody', song.tracks.melody.instrument).toLowerCase()}`
  return PLAIN[track]
}

/** Who plays in a section, as a plain sentence built from the regions: "Only the guitar and the waves". */
export function describeSection(song: Song, cat: Catalog, sectionId: string): string {
  const all = TRACKS.map((t) => t.id).filter((t) => regionOf(song, t, sectionId)?.play !== false)
  const sec = song.sections.find((s) => s.id === sectionId)
  const lead = sec?.lead && all.includes(sec.lead) ? sec.lead : null
  // The lead is named once, at the front, with the same word the list would use.
  const playing = lead ? all.filter((t) => t !== lead) : all
  let base: string
  const names = playing.map((t) => who(song, cat, t))
  if (lead) {
    const head = `${cap(who(song, cat, lead))} leads`
    if (playing.length === 0) return `Only ${who(song, cat, lead)}`
    if (playing.length === 5) return `${head}, everyone joins in`
    return `${head}, ${list(names)} follow${playing.length === 1 ? 's' : ''}`
  }
  if (playing.length === 0) base = 'This part is quiet'
  else if (playing.length <= 2) base = `Only ${list(names)}`
  else if (playing.length === 6) base = 'Everyone plays'
  else base = `${cap(list(names))} play together`
  return base
}
