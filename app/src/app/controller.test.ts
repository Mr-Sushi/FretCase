import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, MockApi } from '../api'
import { Controller, type AudioLike } from './controller'
import { Store, initialState } from './store'
import type { SeedCard, Song } from '../types'

class FakeAudio implements AudioLike {
  loads: Song[] = []
  loop: unknown = null
  gains: [string, number, boolean][] = []
  playing = false
  seeks: number[] = []
  load(s: Song) { this.loads.push(s) }
  async play() { this.playing = true }
  stop() { this.playing = false }
  seek(t: number) { this.seeks.push(t) }
  setLoop(r: { from: number; to: number } | null) { this.loop = r }
  setTrackGain(t: string, v: number, m: boolean) { this.gains.push([t, v, m]) }
}

async function setup() {
  const api = new MockApi(0)
  const store = new Store(initialState(true))
  const audio = new FakeAudio()
  const c = new Controller(api, store, audio)
  await c.init()
  return { api, store, audio, c }
}

let ctx: Awaited<ReturnType<typeof setup>>
beforeEach(async () => { ctx = await setup() })

describe('opening a song', () => {
  it('lists the example song and loads it into the engine', async () => {
    const { store, c, audio } = ctx
    expect(store.state.recentSongs[0].id).toBe('song-hai-bian-01')
    await c.openSong('song-hai-bian-01')
    expect(store.state.song?.title).toBe('海边的傍晚')
    expect(store.state.view).toBe('song')
    expect(audio.loads).toHaveLength(1)
  })
})

describe('seed to song', () => {
  it('goes from a text input to a six-track song', async () => {
    const { store, c } = ctx
    c.addText('今晚的海很安静')
    await c.makeSeed()
    const seed = store.state.seed as SeedCard
    expect(seed.reasons.length).toBeGreaterThan(0)
    expect(seed.source).toBe('offline')
    c.updateSeed({ ...seed, tempo: 70 }) // the user changes the tempo, then confirms
    await c.generate()
    expect(store.state.song?.tempo).toBe(70)
    expect(store.state.song?.revision).toBe(0)
    expect(store.state.view).toBe('song')
    expect(store.state.inputs).toEqual([])
  })

  it('refuses to make a seed without input', async () => {
    await ctx.c.makeSeed()
    expect(ctx.store.state.seed).toBeNull()
    expect(ctx.store.state.toast?.kind).toBe('info')
  })
})

describe('edits in mock mode', () => {
  beforeEach(async () => { await ctx.c.openSong('song-hai-bian-01') })

  it('the song is replaced by the response and the revision goes up by one', async () => {
    const { c, store } = ctx
    await c.setVolume('drums', 0.45)
    expect(store.state.song?.tracks.drums.volume).toBe(0.45)
    expect(store.state.song?.revision).toBe(4)
  })

  it('moves the engine gain before the server answers', async () => {
    const { c, audio } = ctx
    const p = c.setVolume('bass', 0.2)
    expect(audio.gains.at(-1)).toEqual(['bass', 0.2, false])
    await p
  })

  it('queued edits each carry the newest revision', async () => {
    const { c, store } = ctx
    await Promise.all([c.setVolume('drums', 0.3), c.setTempo(100), c.toggleMute('bass')])
    expect(store.state.song?.revision).toBe(6)
    expect(store.state.song?.tempo).toBe(100)
    expect(store.state.song?.tracks.bass.muted).toBe(true)
    expect(store.state.song?.tracks.drums.volume).toBe(0.3)
  })

  it('density changes the guitar rhythm preset', async () => {
    const { c, store } = ctx
    await c.setControl('density', 0.9)
    expect(store.state.song?.controls.density).toBe(0.9)
    expect(store.state.song?.tracks.guitar.rhythm.presetId).not.toBe('t321t321')
  })

  it('replaceNotes edits a note and locks that track in the touched sections', async () => {
    const { c, store } = ctx
    const song = store.state.song!
    const notes = song.tracks.melody.notes.filter((n) => n.start < 4 * 1920).map((n, i) => (i === 0 ? { ...n, pitch: n.pitch + 2 } : n))
    await c.replaceNotes('melody', 0, 4 * 1920, notes)
    const after = store.state.song!
    expect(after.tracks.melody.notes[0].pitch).toBe(song.tracks.melody.notes[0].pitch + 2)
    expect(after.locks).toContainEqual({ track: 'melody', section: 's-intro' })
  })

  it('lyrics with the wrong count are rejected with the counts', async () => {
    const { c, store } = ctx
    const r = await c.setLyrics('s-intro', '海风')
    expect(r.ok).toBe(false)
    expect(r.noteCount).toBe(6)
    expect(r.syllableCount).toBe(2)
    expect(store.state.song?.revision).toBe(3)
    const ok = await c.setLyrics('s-intro', '海风吹过傍晚')
    expect(ok.ok).toBe(true)
    expect(store.state.song?.tracks.vocal.notes[5].lyric).toBe('晚')
  })

  it('undo takes back the last action', async () => {
    const { c, store } = ctx
    await c.setTempo(120)
    await c.undo()
    expect(store.state.song?.tempo).toBe(84)
    expect(store.state.song?.revision).toBe(5)
  })

  it('"another" changes unlocked notes only', async () => {
    const { c, store } = ctx
    const inVerse = () => store.state.song!.tracks.bass.notes.filter((n) => n.start >= 4 * 1920 && n.start < 8 * 1920)
    const before = inVerse()
    const outside = store.state.song!.tracks.bass.notes.filter((n) => n.start < 4 * 1920)
    await c.another('s-verse', 'bass')
    expect(inVerse()).not.toEqual(before)
    expect(store.state.song!.tracks.bass.notes.filter((n) => n.start < 4 * 1920)).toEqual(outside)
    await c.toggleLock('bass', 's-verse')
    expect(store.state.song!.locks).toContainEqual({ track: 'bass', section: 's-verse' })
    const locked = inVerse()
    await c.another('s-verse', 'bass')
    expect(inVerse()).toEqual(locked)
  })

  it('a stale revision replaces the song and tells the user', async () => {
    const { c, store, api } = ctx
    await api.edit('song-hai-bian-01', 3, [{ op: 'setTitle', title: '别处改的' }]) // someone else moved the song on
    await c.setTempo(90) // the app still holds revision 3
    expect(store.state.toast?.kind).toBe('error')
    expect(store.state.song?.title).toBe('别处改的')
    expect(store.state.song?.revision).toBe(4)
    expect(store.state.song?.tempo).toBe(84) // not applied
    await c.setTempo(90)
    expect(store.state.song?.tempo).toBe(90)
  })

  it('opens the track editor looping the section under the play position', async () => {
    const { c, store, audio } = ctx
    c.seekToBar(9)
    c.editTrack('guitar')
    expect(store.state.editSection).toBe('s-chorus')
    expect(audio.loop).toEqual({ from: 8 * 1920, to: 12 * 1920 })
    c.setView('song')
    expect(audio.loop).toBeNull()
  })
})

describe('card flow', () => {
  beforeEach(async () => { await ctx.c.openSong('song-hai-bian-01') })

  it('refuses to print without a preview, then prints after one', async () => {
    const { c, store } = ctx
    await c.printCard()
    expect(store.state.song?.card?.printedAt).toBeUndefined()
    await c.previewCard()
    expect(store.state.song?.card?.frontAssetId).toBeTruthy()
    await c.printCard()
    expect(store.state.song?.card?.printedAt).toBeTruthy()
  })

  it('a card change after the preview needs a new preview', async () => {
    const { c, store } = ctx
    await c.previewCard()
    await c.setCard({ style: 'comic' })
    await c.printCard()
    expect(store.state.song?.card?.printedAt).toBeUndefined()
    await c.previewCard()
    await c.printCard()
    expect(store.state.song?.card?.printedAt).toBeTruthy()
  })
})

describe('scanning', () => {
  it('loads and plays the song for a card QR code', async () => {
    const { c, store, audio } = ctx
    const ok = await c.handleScan('https://fretcase.example/s/k3Hq9xV2mPzT')
    expect(ok).toBe(true)
    expect(store.state.song?.id).toBe('song-hai-bian-01')
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

  beforeEach(async () => { vi.useFakeTimers(); await ctx.c.openSong('song-hai-bian-01') })

  it('a fader becomes one setTrackVolume call after 150 ms', async () => {
    const { c, store } = ctx
    const spy = vi.spyOn(ctx.api, 'edit')
    fire(c, 'fader.move', { track: 'drums', value: 0.6 })
    fire(c, 'fader.move', { track: 'drums', value: 0.31 })
    await vi.advanceTimersByTimeAsync(160)
    expect(spy).toHaveBeenCalledTimes(1)
    expect(store.state.song?.tracks.drums.volume).toBe(0.31)
  })

  it('a feel knob becomes one setControl call', async () => {
    const { c, store } = ctx
    const spy = vi.spyOn(ctx.api, 'edit')
    fire(c, 'knob.turn', { knob: 'brightness', delta: 5 })
    fire(c, 'knob.turn', { knob: 'brightness', delta: 5 })
    await vi.advanceTimersByTimeAsync(450)
    expect(spy).toHaveBeenCalledTimes(1)
    expect(store.state.song?.controls.brightness).toBeCloseTo(0.82)
  })

  it('platter plus "another" regenerates the section under the platter, for the selected track', async () => {
    const { c, store } = ctx
    const spy = vi.spyOn(ctx.api, 'another')
    fire(c, 'key', { id: 'track.melody', action: 'down' }, 0)
    fire(c, 'key', { id: 'track.melody', action: 'up' }, 100)
    expect(store.state.selectedTrack).toBe('melody')
    fire(c, 'platter.turn', { delta: 22 }) // 5.5 bars
    expect(store.state.positionTick).toBe(Math.round(5.5 * 1920))
    fire(c, 'key', { id: 'another', action: 'down' }, 200)
    fire(c, 'key', { id: 'another', action: 'up' }, 250)
    await vi.advanceTimersByTimeAsync(10)
    expect(spy).toHaveBeenCalledWith('song-hai-bian-01', 3, 's-verse', 'melody')
    vi.useRealTimers()
  })

  it('a long press on a track key mutes it', async () => {
    const { c, store } = ctx
    fire(c, 'key', { id: 'track.bass', action: 'down' }, 0)
    await vi.advanceTimersByTimeAsync(650)
    fire(c, 'key', { id: 'track.bass', action: 'up' }, 650)
    await vi.advanceTimersByTimeAsync(10)
    expect(store.state.song?.tracks.bass.muted).toBe(true)
    expect(store.state.selectedTrack).toBeNull()
  })

  it('the panel snapshot sets the song volumes', async () => {
    const { c, store } = ctx
    fire(c, 'snapshot', { faders: { vocal: 0.8, melody: 0.8, guitar: 0.8, bass: 0.7, drums: 0.45, ambience: 0.5 }, keysDown: [] })
    await vi.advanceTimersByTimeAsync(10)
    expect(store.state.song?.tracks.drums.volume).toBe(0.45)
    expect(store.state.song?.tracks.bass.volume).toBe(0.7)
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
    await c.openSong('song-hai-bian-01')
    expect(sent.length).toBeGreaterThan(first)
  })
})

describe('errors', () => {
  it('an offline-only operation shows a message and does not loop', async () => {
    const { c, store, api } = ctx
    await c.openSong('song-hai-bian-01')
    vi.spyOn(api, 'edit').mockRejectedValue(new ApiError('offline_unavailable', 'x', 503))
    await c.setTempo(100)
    expect(store.state.toast?.text).toContain('联网')
    expect(api.edit).toHaveBeenCalledTimes(1)
  })
})
