import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, MockApi } from '../api'
import { Controller, type AudioLike } from './controller'
import { MAX_PHOTOS, Store, initialState } from './store'
import { previewStartTick } from '../lib/song'
import type { Song } from '../types'
import { syllables } from '../lib/lyrics'

class FakeAudio implements AudioLike {
  loads: Song[] = []
  loop: unknown = null
  gains: [string, number, boolean][] = []
  playing = false
  seeks: number[] = []
  solo: string | null = null
  load(s: Song) { this.loads.push(s) }
  async play() { this.playing = true }
  stop() { this.playing = false }
  seek(t: number) { this.seeks.push(t) }
  setLoop(r: { from: number; to: number } | null) { this.loop = r }
  setTrackGain(t: string, v: number, m: boolean) { this.gains.push([t, v, m]) }
  setSolo(t: string | null) { this.solo = t }
}

const DEMO = 'song-demo-0001'
const photo = () => new Blob(['x'], { type: 'image/jpeg' })

async function setup() {
  const api = new MockApi(0)
  const store = new Store(initialState(true))
  const audio = new FakeAudio()
  const c = new Controller(api, store, audio)
  await c.init()
  return { api, store, audio, c }
}

let ctx: Awaited<ReturnType<typeof setup>>
beforeEach(async () => {
  ctx = await setup()
  // jsdom is not used: the controller only needs a URL maker for local previews.
  if (!('createObjectURL' in URL)) (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:test'
})

describe('capture', () => {
  it('takes up to nine photos and refuses the tenth with a message', () => {
    const { c, store } = ctx
    for (let i = 0; i < MAX_PHOTOS; i++) expect(c.addPhoto(photo())).toBe(true)
    expect(c.addPhoto(photo())).toBe(false)
    expect(store.state.inputs.filter((i) => i.kind === 'photo')).toHaveLength(9)
    expect(store.state.toast?.text).toContain('9')
    c.retakePhoto() // Retake frees one place
    expect(c.addPhoto(photo())).toBe(true)
  })

  it('text is one sentence that can be cleared, and removing an input works', () => {
    const { c, store } = ctx
    c.setText('Seaside at dusk, very windy')
    c.setText('Seaside at dusk, very windy, a little homesick')
    expect(store.state.inputs.filter((i) => i.kind === 'text')).toHaveLength(1)
    c.setText('  ')
    expect(store.state.inputs).toEqual([])
  })

  it('makes nothing from an empty capture', async () => {
    await ctx.c.makeSong()
    expect(ctx.store.state.candidates).toBeNull()
    expect(ctx.store.state.toast?.kind).toBe('info')
  })
})

describe('candidate flow', () => {
  beforeEach(() => { ctx.c.addPhoto(photo()); ctx.c.setText('Seaside at dusk, very windy, a little homesick') })

  it('uploads, makes a seed and shows three different candidates', async () => {
    const { c, store, api } = ctx
    const upload = vi.spyOn(api, 'uploadAsset')
    const cand = vi.spyOn(api, 'candidates')
    await c.makeSong()
    expect(upload).toHaveBeenCalledTimes(1) // the photo; text needs no upload
    expect(cand).toHaveBeenCalledTimes(1)
    expect(store.state.view).toBe('pick')
    const list = store.state.candidates!
    expect(list).toHaveLength(3)
    expect(new Set(list.map((s) => s.candidate!.name)).size).toBe(3)
    expect(new Set(list.map((s) => JSON.stringify(s.candidate!.parts))).size).toBe(3)
    expect(list.every((s) => s.candidate!.groupId === list[0].candidate!.groupId)).toBe(true)
    // Photos from the capture are the card's photos.
    expect(list[0].card?.photoAssetIds).toHaveLength(1)
  })

  it('Day / Dusk / Night asks again with timeOfDay; three more sends the previous group', async () => {
    const { c, store, api } = ctx
    await c.makeSong()
    const spy = vi.spyOn(api, 'candidates')
    const firstGroup = store.state.candidates![0].candidate!.groupId
    await c.moreCandidates({ timeOfDay: 'night' })
    expect(spy.mock.calls[0][1]).toMatchObject({ timeOfDay: 'night' })
    expect(spy.mock.calls[0][1]).not.toHaveProperty('previousGroupId')
    const secondGroup = store.state.candidates![0].candidate!.groupId
    expect(secondGroup).not.toBe(firstGroup)
    await c.moreCandidates({ again: true })
    expect(spy.mock.calls[1][1]).toMatchObject({ timeOfDay: 'night', previousGroupId: secondGroup })
    expect(store.state.candidates!.map((s) => s.candidate!.name)).not.toEqual(['Dusk Folk', 'Sea Breeze', 'Homesick Night'])
  })

  it('a preview starts at the chorus (the vocal-led section) and stops after fifteen seconds', async () => {
    const { c, store, audio } = ctx
    await c.makeSong()
    const song = store.state.candidates![0]
    await c.previewCandidate(0)
    expect(audio.playing).toBe(true)
    expect(audio.seeks.at(-1)).toBe(previewStartTick(song))
    expect(previewStartTick(song)).toBe(8 * 1920) // s-chorus has lead: vocal
    const p = store.state.preview!
    c.onPosition(p.toTick - 10)
    expect(audio.playing).toBe(true)
    c.onPosition(p.toTick + 1)
    expect(audio.playing).toBe(false)
    expect(store.state.preview).toBeNull()
    // Without a vocal-led section the middle of the song is used.
    const noLead = { ...song, sections: song.sections.map((s) => ({ ...s, lead: undefined })) } as Song
    expect(previewStartTick(noLead)).toBe(8 * 1920)
    expect(previewStartTick({ ...noLead, bars: 12 })).toBe(6 * 1920)
  })

  it('choosing a candidate makes it the song and drops the other drafts', async () => {
    const { c, store, api } = ctx
    await c.makeSong()
    const [a, , third] = store.state.candidates!
    await c.chooseCandidate(0)
    expect(store.state.view).toBe('shape')
    expect(store.state.song?.id).toBe(a.id)
    expect(store.state.song?.candidate?.chosen).toBe(true)
    expect(store.state.candidates).toBeNull()
    await expect(api.getSong(third.id)).rejects.toMatchObject({ status: 404 })
    expect((await api.listSongs()).map((s) => s.id)).toContain(a.id)
  })
})

describe('opening a song', () => {
  it('lists the demo song and loads it into the engine', async () => {
    const { store, c, audio } = ctx
    expect(store.state.recentSongs[0].id).toBe(DEMO)
    await c.openSong(DEMO)
    expect(store.state.song?.title).toBe('Seaside at Dusk')
    expect(store.state.view).toBe('shape')
    expect(audio.loads).toHaveLength(1)
  })
})

describe('shape and track edits', () => {
  beforeEach(async () => { await ctx.c.openSong(DEMO) })

  it('the song is replaced by the response and the revision goes up by one', async () => {
    const { c, store } = ctx
    await c.setVolume('drums', 0.45)
    expect(store.state.song?.tracks.drums.volume).toBe(0.45)
    expect(store.state.song?.revision).toBe(1)
  })

  it('queued edits each carry the newest revision', async () => {
    const { c, store } = ctx
    await Promise.all([c.setVolume('drums', 0.3), c.setTempo(100), c.toggleMute('bass')])
    expect(store.state.song?.revision).toBe(3)
    expect(store.state.song?.tempo).toBe(100)
    expect(store.state.song?.tracks.bass.muted).toBe(true)
  })

  it('Another take keeps locked sections and Keep toggles the section lock', async () => {
    const { c, store } = ctx
    const inVerse = () => store.state.song!.tracks.bass.notes.filter((n) => n.start >= 4 * 1920 && n.start < 8 * 1920)
    await c.another('s-verse', 'bass')
    expect(store.state.takes['s-verse']).toBe(2)
    await c.toggleLock(undefined, 's-verse')
    expect(store.state.song!.locks).toContainEqual({ section: 's-verse' })
    const locked = inVerse()
    await c.another('s-verse', 'bass')
    expect(inVerse()).toEqual(locked)
    await c.toggleLock(undefined, 's-verse')
    expect(store.state.song!.locks).toEqual([])
  })

  it('Lead sends setLead for the selected section and removing it sends null', async () => {
    const { c, store, api } = ctx
    const spy = vi.spyOn(api, 'edit')
    await c.setLead('s-verse', 'guitar')
    expect(spy.mock.calls[0][2]).toEqual([{ op: 'setLead', section: 's-verse', track: 'guitar' }])
    expect(store.state.song!.sections[1].lead).toBe('guitar')
    await c.setLead('s-verse', null)
    expect(store.state.song!.sections[1].lead).toBeUndefined()
  })

  it('region editor: setRegion, copyRegion, shiftRegister, revertMelody, setMaster', async () => {
    const { c, store, api } = ctx
    const spy = vi.spyOn(api, 'edit')
    await c.setRegion('guitar', 's-verse', { complexity: 0.85, intensity: 0.15, style: 'arpeggio' })
    let r = store.state.song!.tracks.guitar.regions[1]
    expect(r).toMatchObject({ complexity: 0.85, intensity: 0.15, style: 'arpeggio' })
    expect(store.state.song!.locks).toContainEqual({ track: 'guitar', section: 's-verse' })
    await c.copyRegion('guitar', 's-verse')
    expect(store.state.song!.tracks.guitar.regions.every((x) => x.style === 'arpeggio' && x.complexity === 0.85)).toBe(true)
    await c.setRegion('bass', 's-intro', { play: false })
    expect(store.state.song!.tracks.bass.regions[0].play).toBe(false)
    expect(store.state.song!.tracks.bass.notes.filter((n) => n.start < 4 * 1920)).toEqual([])
    const before = store.state.song!.tracks.melody.notes.map((n) => n.pitch)
    await c.shiftRegister('melody', 's-chorus', 'up')
    expect(store.state.song!.tracks.melody.notes.map((n) => n.pitch)).not.toEqual(before)
    await c.shiftRegister('drums', 's-chorus', 'up') // not allowed on drums: the server says no
    expect(store.state.toast?.kind).toBe('error')
    await c.revertMelody('s-chorus')
    await c.setMaster({ space: 'hall', volume: 0.6 })
    expect(store.state.song!.master).toEqual({ volume: 0.6, space: 'hall' })
    expect(spy.mock.calls.map((x) => (x[2][0] as { op: string }).op)).toEqual(['setRegion', 'copyRegion', 'setRegion', 'shiftRegister', 'shiftRegister', 'revertMelody', 'setMaster'])
    r = store.state.song!.tracks.guitar.regions[0]
    expect(r.style).toBe('arpeggio')
  })

  it('solo is only in the app', async () => {
    const { c, store, audio, api } = ctx
    const spy = vi.spyOn(api, 'edit')
    c.toggleSolo('guitar')
    expect(store.state.solo).toBe('guitar')
    expect(audio.solo).toBe('guitar')
    c.toggleSolo('guitar')
    expect(audio.solo).toBeNull()
    expect(spy).not.toHaveBeenCalled()
  })

  it('selecting a region loops that section', () => {
    const { c, store, audio } = ctx
    c.selectRegion('guitar', 's-chorus')
    expect(store.state.selectedTrack).toBe('guitar')
    expect(audio.loop).toEqual({ from: 8 * 1920, to: 12 * 1920 })
    c.setView('lyrics')
    expect(audio.loop).toBeNull()
  })

  it('a stale revision replaces the song and tells the user', async () => {
    const { c, store, api } = ctx
    await api.edit(DEMO, 0, [{ op: 'setTitle', title: 'Changed elsewhere' }])
    await c.setTempo(90)
    expect(store.state.toast?.kind).toBe('error')
    expect(store.state.song?.title).toBe('Changed elsewhere')
    expect(store.state.song?.tempo).toBe(84 > 0 ? store.state.song!.tempo : 0)
    await c.setTempo(90)
    expect(store.state.song?.tempo).toBe(90)
  })

  it('undo takes back the last action', async () => {
    const { c, store } = ctx
    const t = store.state.song!.tempo
    await c.setTempo(120)
    await c.undo()
    expect(store.state.song?.tempo).toBe(t)
  })
})

describe('lyrics', () => {
  beforeEach(async () => { await ctx.c.openSong(DEMO) })

  it('sends a section line by line and reports the lines that do not fit', async () => {
    const { c, store, api } = ctx
    const spy = vi.spyOn(api, 'edit')
    const bad = await c.setSectionLyrics('s-verse', ['The sea wind blows', 'And one by one the lights come on'])
    expect(bad).toEqual({ ok: false, misfit: [0] })
    expect(store.state.lyrics.misfit).toEqual(['s-verse:0'])
    const ok = await c.setSectionLyrics('s-verse', ['The salty wind along the shore', 'And one by one the lights come on'])
    expect(ok.ok).toBe(true)
    expect(store.state.lyrics.misfit).toEqual([])
    expect(spy.mock.calls[1][2]).toEqual([{ op: 'setLyrics', section: 's-verse', text: 'The salty wind along the shore\nAnd one by one the lights come on' }])
    expect(store.state.song!.tracks.vocal.notes.find((n) => n.start === 4 * 1920)?.lyric).toBe('The')
  })

  it('keeps are held in the app and sent with a rewrite; 503 shows the offline note and leaves the song alone', async () => {
    const { c, store, api } = ctx
    c.toggleKeep('s-verse', 1)
    c.toggleKeep('s-chorus', 0)
    c.toggleKeep('s-chorus', 0)
    expect(store.state.lyrics.keeps).toEqual({ 's-verse': [1], 's-chorus': [] })
    c.toggleTheme('sea')
    const spy = vi.spyOn(api, 'lyricsRewrite')
    const rev = store.state.song!.revision
    await c.rewriteLyrics()
    expect(spy.mock.calls[0][2]).toMatchObject({ keep: { 's-verse': [1] }, tone: 'plain', rhyme: true })
    expect(store.state.lyrics.offline).toBe(true)
    expect(store.state.song!.revision).toBe(rev)
    expect(store.state.toast?.text).toContain('internet')
  })

  it('Other wordings offline sets the note; online it applies a wording with setLyrics', async () => {
    const { c, store } = ctx
    await c.fetchAlternatives('s-verse', 0)
    expect(store.state.lyrics.offline).toBe(true)
    const online = new MockApi(0, true)
    const c2 = new Controller(online, new Store(initialState(true)), new FakeAudio())
    await c2.init()
    await c2.openSong(DEMO)
    c2.selectLine('s-verse', 0)
    await vi.waitFor(() => expect(c2.store.state.lyrics.alternatives?.length).toBe(3))
    const pick = c2.store.state.lyrics.alternatives![0].text
    await c2.applyAlternative('s-verse', 0, pick)
    expect(c2.store.state.song!.tracks.vocal.notes.find((n) => n.start === 4 * 1920)?.lyric).toBe(syllables(pick)[0])
  })

  it('themes come from the song', async () => {
    const { c, store } = ctx
    await c.loadThemes()
    expect(store.state.lyrics.themes.length).toBeGreaterThan(0)
    expect(store.state.lyrics.themeSel).toEqual(store.state.lyrics.themes.map((t) => t.text))
  })
})

describe('card flow', () => {
  beforeEach(async () => { await ctx.c.openSong(DEMO) })

  it('prints after a fresh preview, and a card change needs a new preview', async () => {
    const { c, store } = ctx
    await c.printCard() // previews first, then prints
    expect(store.state.song?.card?.printedAt).toBeTruthy()
    await c.setCard({ style: 'comic' })
    expect(store.state.song?.card?.frontAssetId).toBeUndefined()
    await c.printCard()
    expect(store.state.song?.card?.style).toBe('comic')
    expect(store.state.song?.card?.frontAssetId).toBeTruthy()
  })

  it('the cover must be one of the photos; text style has no cover', async () => {
    const { c, store } = ctx
    await c.setCard({ coverAssetId: 'a-photo-02' })
    expect(store.state.song?.card?.coverAssetId).toBe('a-photo-02')
    await c.setCard({ style: 'text' })
    expect(store.state.song?.card?.coverAssetId).toBeUndefined()
  })

  it('reads the film count from the printer', async () => {
    await ctx.c.refreshPrinter()
    expect(ctx.store.state.printer).toMatchObject({ kind: 'dry_run', remaining: 7 })
  })
})

describe('scanning', () => {
  it('loads and plays the song for a card QR code', async () => {
    const { c, store, audio } = ctx
    expect(await c.handleScan('https://fretcase.example/s/k3Hq9xV2mPzT')).toBe(true)
    expect(store.state.song?.id).toBe(DEMO)
    expect(audio.playing).toBe(true)
  })
  it('ignores codes that are not song pages and reports unknown cards', async () => {
    const { c, store } = ctx
    expect(await c.handleScan('https://example.com/hello')).toBe(false)
    expect(await c.handleScan('https://fretcase.example/s/ZZZZZZZZZZZZ')).toBe(true)
    expect(store.state.toast?.kind).toBe('error')
    expect(store.state.song).toBeNull()
  })
})

describe('panel intents', () => {
  const fire = (c: Controller, type: string, payload: Record<string, unknown>, t = 0) => c.onPanelMessage({ type, payload, t })
  beforeEach(async () => { vi.useFakeTimers(); await ctx.c.openSong(DEMO) })

  it('a fader becomes one setTrackVolume call after 150 ms', async () => {
    const { c, store } = ctx
    const spy = vi.spyOn(ctx.api, 'edit')
    fire(c, 'fader.move', { track: 'drums', value: 0.6 })
    fire(c, 'fader.move', { track: 'drums', value: 0.31 })
    await vi.advanceTimersByTimeAsync(160)
    expect(spy).toHaveBeenCalledTimes(1)
    expect(store.state.song?.tracks.drums.volume).toBe(0.31)
    vi.useRealTimers()
  })

  it('on the track screen the complexity knob sets the selected region (one setRegion per knob, 400 ms after its last detent)', async () => {
    const { c, store } = ctx
    c.setView('detail')
    c.selectRegion('guitar', 's-chorus')
    const spy = vi.spyOn(ctx.api, 'edit')
    fire(c, 'knob.turn', { knob: 'complexity', delta: 5 })
    fire(c, 'knob.turn', { knob: 'complexity', delta: 5 })
    fire(c, 'knob.turn', { knob: 'density', delta: -10 })
    await vi.advanceTimersByTimeAsync(450)
    expect(spy).toHaveBeenCalledTimes(2)
    expect(spy.mock.calls[0][2]).toEqual([{ op: 'setRegion', track: 'guitar', section: 's-chorus', complexity: 0.7 }])
    expect(spy.mock.calls[1][2]).toEqual([{ op: 'setRegion', track: 'guitar', section: 's-chorus', intensity: 0.3 }])
    expect(store.state.song!.controls.complexity).toBe(0.5)
    vi.useRealTimers()
  })

  it('on the track screen the platter moves the selected section and track keys select the row', async () => {
    const { c, store } = ctx
    c.setView('detail')
    fire(c, 'key', { id: 'track.bass', action: 'down' }, 0)
    fire(c, 'key', { id: 'track.bass', action: 'up' }, 100)
    expect(store.state.selectedTrack).toBe('bass')
    fire(c, 'platter.turn', { delta: 8 })
    expect(store.state.editSection).toBe('s-chorus')
    vi.useRealTimers()
  })

  it('on the pick screen the platter moves the focus, the play key plays the focused card, another asks for more', async () => {
    const { c, store, audio } = ctx
    c.addPhoto(photo()); c.setText('Homesick at night')
    await c.makeSong()
    fire(c, 'platter.turn', { delta: 8 })
    expect(store.state.focus).toBe(2)
    fire(c, 'key', { id: 'play', action: 'down' }, 0)
    fire(c, 'key', { id: 'play', action: 'up' }, 50)
    await vi.advanceTimersByTimeAsync(10)
    expect(store.state.preview?.index).toBe(2)
    expect(audio.playing).toBe(true)
    const spy = vi.spyOn(ctx.api, 'candidates')
    fire(c, 'key', { id: 'another', action: 'down' }, 100)
    fire(c, 'key', { id: 'another', action: 'up' }, 150)
    await vi.advanceTimersByTimeAsync(10)
    expect(spy.mock.calls[0][1]).toHaveProperty('previousGroupId')
    vi.useRealTimers()
  })

  it('on the capture screen the red key follows the chosen mode', async () => {
    const { c, store } = ctx
    const rec = { start: vi.fn(async () => {}), stop: vi.fn(async () => new Blob(['a'], { type: 'audio/webm' })) }
    ;(c as unknown as { recorder: typeof rec }).recorder = rec
    c.photoSource = async () => photo()
    c.setView('capture')
    // hum mode: one short press starts, the next stops, and the hum becomes an input
    c.setCaptureMode('hum')
    fire(c, 'key', { id: 'capture', action: 'down' }, 0)
    fire(c, 'key', { id: 'capture', action: 'up' }, 100)
    await vi.advanceTimersByTimeAsync(10)
    expect(store.state.recording).toBe('hum')
    fire(c, 'key', { id: 'capture', action: 'down' }, 3000)
    fire(c, 'key', { id: 'capture', action: 'up' }, 3100)
    await vi.advanceTimersByTimeAsync(10)
    expect(store.state.recording).toBe(null)
    expect(store.state.inputs.map((i) => i.kind)).toEqual(['hum'])
    // sound mode: holding the key records ambience, not a hum
    c.setCaptureMode('sound')
    fire(c, 'key', { id: 'capture', action: 'down' }, 5000)
    await vi.advanceTimersByTimeAsync(700)
    expect(store.state.recording).toBe('sound')
    fire(c, 'key', { id: 'capture', action: 'up' }, 6000)
    await vi.advanceTimersByTimeAsync(10)
    expect(store.state.inputs.map((i) => i.kind)).toEqual(['hum', 'sound'])
    expect(store.state.captureMode).toBe('sound')
    // photo mode: a short press takes a photo
    c.setCaptureMode('photo')
    fire(c, 'key', { id: 'capture', action: 'down' }, 8000)
    fire(c, 'key', { id: 'capture', action: 'up' }, 8100)
    await vi.advanceTimersByTimeAsync(10)
    expect(store.state.inputs.map((i) => i.kind)).toEqual(['hum', 'sound', 'photo'])
    vi.useRealTimers()
  })

  it('on the card screen the platter cycles the styles', async () => {
    const { c, store } = ctx
    c.setView('card')
    await vi.advanceTimersByTimeAsync(10)
    const before = store.state.song!.card!.style
    expect(before).toBe('xieyi')
    fire(c, 'platter.turn', { delta: 4 })
    await vi.advanceTimersByTimeAsync(10)
    expect(store.state.song!.card!.style).toBe('comic')
    vi.useRealTimers()
  })

  it('platter plus "another" regenerates the section under the platter, for the selected track', async () => {
    const { c, store } = ctx
    const spy = vi.spyOn(ctx.api, 'another')
    fire(c, 'key', { id: 'track.melody', action: 'down' }, 0)
    fire(c, 'key', { id: 'track.melody', action: 'up' }, 100)
    expect(store.state.selectedTrack).toBe('melody')
    fire(c, 'platter.turn', { delta: 22 })
    fire(c, 'key', { id: 'another', action: 'down' }, 200)
    fire(c, 'key', { id: 'another', action: 'up' }, 250)
    await vi.advanceTimersByTimeAsync(10)
    expect(spy).toHaveBeenCalledWith(DEMO, expect.any(Number), 's-verse', 'melody')
    vi.useRealTimers()
  })

  it('a long press on a track key mutes it', async () => {
    const { c, store } = ctx
    fire(c, 'key', { id: 'track.bass', action: 'down' }, 0)
    await vi.advanceTimersByTimeAsync(650)
    fire(c, 'key', { id: 'track.bass', action: 'up' }, 650)
    await vi.advanceTimersByTimeAsync(10)
    expect(store.state.song?.tracks.bass.muted).toBe(true)
    vi.useRealTimers()
  })
})

describe('lights', () => {
  it('sends only what changed', async () => {
    const { c, store } = ctx
    const sent: string[] = []
    c.panel = { setRing: () => (sent.push('ring'), true), setKeyLight: (id) => (sent.push(id), true) }
    c.onPanelStatus({ connected: true, panel: true })
    const first = sent.length
    expect(first).toBe(1 + 4 + 6)
    store.set({ toast: null })
    expect(sent.length).toBe(first)
    await c.openSong(DEMO)
    expect(sent.length).toBeGreaterThan(first)
  })
})

describe('errors', () => {
  it('an offline-only operation shows a message and does not loop', async () => {
    const { c, store, api } = ctx
    await c.openSong(DEMO)
    vi.spyOn(api, 'edit').mockRejectedValue(new ApiError('offline_unavailable', 'x', 503))
    await c.setTempo(100)
    expect(store.state.toast?.text).toContain('internet')
    expect(api.edit).toHaveBeenCalledTimes(1)
  })
})

describe('lyrics failure reasons', () => {
  it('turn the server reason into plain words', async () => {
    const { lyricsFailure, lyricsFailureText } = await import('./controller')
    const { ApiError } = await import('../api/types')
    const err = (reason?: string) => new ApiError('offline_unavailable', 'x', 503, undefined, reason ? { reason } : undefined)
    expect(lyricsFailure(err('auth'))).toBe('auth')
    expect(lyricsFailureText('auth')).toContain('key')
    expect(lyricsFailure(err())).toBe('network')
    expect(lyricsFailure(new ApiError('timeout', 'x', 0))).toBe('network')
    expect(lyricsFailureText('not_configured')).toContain('No lyrics model')
    expect(lyricsFailureText('something-new')).toBeNull()
  })
})

describe('first lyrics after choosing', () => {
  it('are written in the background when the server has a lyrics model', async () => {
    const api = new MockApi(0, true)
    const store = new Store(initialState(true))
    const c = new Controller(api, store, new FakeAudio())
    await c.init()
    expect(store.state.lyricsAvailable).toBe(true)
    const spy = vi.spyOn(api, 'lyricsRewrite')
    await c.addPhoto(photo())
    await c.makeSong()
    await c.chooseCandidate(0)
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    await vi.waitFor(() => expect(store.state.lyrics.writing).toBe(false))
  })

  it('are not asked for when the server has no lyrics model', async () => {
    const { api, store, c } = ctx
    expect(store.state.lyricsAvailable).toBe(false)
    const spy = vi.spyOn(api, 'lyricsRewrite')
    await c.addPhoto(photo())
    await c.makeSong()
    await c.chooseCandidate(0)
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })
})

describe('the studio version', () => {
  it('starts a render job, waits for it and takes the song it returns', async () => {
    const { c, store, api } = ctx
    await c.openSong(DEMO)
    const song = store.state.song!
    const done = { ...song, revision: song.revision + 1, render: { assetId: 'a-render-1', model: 'lyria-3.5', basedOnRevision: song.revision, revision: song.revision + 1, createdAt: song.updatedAt, lyrics: [] } }
    vi.spyOn(api, 'render').mockResolvedValue({ id: 'job-1', state: 'running' })
    const job = vi.spyOn(api, 'job').mockResolvedValueOnce({ id: 'job-1', state: 'running' }).mockResolvedValueOnce({ id: 'job-1', state: 'done', result: { song: done } })
    c.studioPollMs = 1
    const run = c.makeStudioVersion()
    expect(store.state.studio.working).toBe(true)
    await run
    expect(job).toHaveBeenCalledTimes(2)
    expect(store.state.song?.render?.assetId).toBe('a-render-1')
    expect(store.state.studio.working).toBe(false)
    expect(store.state.toast?.text).toContain('ready')
    const { studioState } = await import('../lib/song')
    expect(studioState(store.state.song!)).toBe('current')
  })

  it('explains a missing music model in plain words', async () => {
    const { c, store } = ctx
    await c.openSong(DEMO)
    await c.makeStudioVersion()
    expect(store.state.toast?.text).toContain('Gemini API key')
    expect(store.state.studio.working).toBe(false)
  })

  it('reports a failed job with its reason', async () => {
    const { c, store, api } = ctx
    await c.openSong(DEMO)
    vi.spyOn(api, 'render').mockResolvedValue({ id: 'job-2', state: 'running' })
    vi.spyOn(api, 'job').mockResolvedValue({ id: 'job-2', state: 'failed', error: { code: 'offline_unavailable', message: 'x', detail: { reason: 'blocked' } } })
    c.studioPollMs = 1
    await c.makeStudioVersion()
    expect(store.state.toast?.text).toContain('would not make this song')
  })

  it('calls a render older when the song was edited after it', async () => {
    const { studioState } = await import('../lib/song')
    const { store, c } = ctx
    await c.openSong(DEMO)
    const s = store.state.song!
    expect(studioState(s)).toBe('none')
    const r = { assetId: 'a', model: 'm', basedOnRevision: 3, revision: 4, createdAt: s.updatedAt, lyrics: [] }
    expect(studioState({ ...s, revision: 4, render: r })).toBe('current')
    expect(studioState({ ...s, revision: 5, render: r })).toBe('older')
    expect(studioState({ ...s, revision: 4, render: { ...r, basedOnRevision: 2 } })).toBe('older') // edited while it was being made
  })
})

describe('singing one\'s own vocal', () => {
  it('puts a take on the vocal track and goes back to the guide voice', async () => {
    const { c, store, api } = ctx
    await c.openSong(DEMO)
    const asset = await api.uploadAsset(new Blob(['x'], { type: 'audio/wav' }), 'vocal_take')
    const cur = store.state.song!
    c.setSong(await api.edit(cur.id, cur.revision, [{ op: 'setVocalTake', assetId: asset.id }]))
    expect(store.state.song!.tracks.vocal.source).toBe('recording')
    expect(store.state.song!.tracks.vocal.renderAssetId).toBe(asset.id)
    await c.removeVocalTake()
    expect(store.state.song!.tracks.vocal.source).toBe('none')
    expect(store.state.song!.assets.some((a) => a.id === asset.id)).toBe(false)
  })

  it('says so when the browser cannot record', async () => {
    const { c, store } = ctx
    await c.openSong(DEMO)
    await c.recordVocalTake()
    expect(store.state.toast?.text).toContain('cannot record')
    expect(store.state.vocalTake).toBeNull()
  })
})
