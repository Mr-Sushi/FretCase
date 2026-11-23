import { describe, expect, it } from 'vitest'
import { MockApi } from '../api'
import type { SharePage, Song } from '../types'
import { buildModel, currentLineIndex, formatDate, shareIdFromLocation } from './model'

async function load(patch: (s: Song) => void = () => {}) {
  const api = new MockApi(0)
  const { page, song } = await api.sharePage('k3Hq9xV2mPzT')
  patch(song)
  return { page, song, model: buildModel(page, song), api }
}

describe('the song page', () => {
  it('shows what the page JSON gives: title, city and date, photos, message, lyrics, card', async () => {
    const { page, model } = await load()
    expect(model.title).toBe('Seaside at Dusk')
    expect(model.meta).toBe(`Edinburgh · ${formatDate(page.date)}`)
    expect(model.photos).toHaveLength(3)
    expect(model.message).toContain('sing it to you')
    expect(model.card).toBeTruthy()
    expect(model.lyrics.map((g) => g.section)).toEqual(['Verse', 'Chorus', 'Outro'])
    expect(model.lyrics[1].lines.map((l) => l.text)).toEqual(['I sing my longing to the sea', 'The wind sings it back to me'])
  })

  it('has no city when the page has none, and no photos when the page lists none, even if the song knows them', async () => {
    const { page, song } = await load()
    const hidden: SharePage = { ...page, photos: [] }
    delete hidden.city
    const model = buildModel(hidden, song)
    expect(model.meta).toBe(formatDate(hidden.date))
    expect(JSON.stringify(model)).not.toContain('Edinburgh' + ' ·')
    expect(model.photos).toEqual([])
    // The song JSON still carries the card's city; the page must not read it.
    expect(song.card?.city).toBe('Edinburgh')
    expect(model.meta).not.toContain('Edinburgh')
  })

  it('the mock page JSON itself follows the privacy rules', async () => {
    const { api } = await load()
    const st = (api as unknown as { songs: Map<string, { song: Song }> }).songs.get('song-demo-0001')!
    st.song.card!.showCity = false
    st.song.card!.showPhoto = false
    const r = await api.sharePage('k3Hq9xV2mPzT')
    expect(r.page.city).toBeUndefined()
    expect(r.page.photos).toEqual([])
    expect(r.song.seed).toBeUndefined()
    expect(r.song.provenance).toBeUndefined()
    expect(JSON.stringify(r.page)).not.toContain('Edinburgh ·')
  })

  it('highlights the line being sung', async () => {
    const { model } = await load()
    const lines = model.lyrics.flatMap((g) => g.lines)
    expect(currentLineIndex(model, 0)).toBe(-1)
    expect(currentLineIndex(model, lines[2].from + 10)).toBe(2)
    expect(currentLineIndex(model, lines[3].from)).toBe(3)
  })

  it('spreads lines evenly when the page and the song disagree on how many there are', async () => {
    const { page, song } = await load()
    const model = buildModel({ ...page, lyrics: [{ section: 'Chorus', lines: ['one', 'two', 'three'] }] }, song)
    const ls = model.lyrics[0].lines
    expect(ls[0].from).toBe(8 * 1920)
    expect(ls[2].to).toBe(12 * 1920)
  })

  it('reads the share id from the path or the query', () => {
    expect(shareIdFromLocation({ pathname: '/s/k3Hq9xV2mPzT', search: '' })).toBe('k3Hq9xV2mPzT')
    expect(shareIdFromLocation({ pathname: '/song.html', search: '?share=abcdefghij' })).toBe('abcdefghij')
    expect(shareIdFromLocation({ pathname: '/', search: '' })).toBeNull()
  })
})
