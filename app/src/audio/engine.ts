import * as Tone from 'tone'
import type { Song, SpaceId, TrackId } from '../types'
import { TRACK_IDS } from '../lib/song'
import { buildSchedule, diffForPlayback, faderGain, type NoteEvent } from './schedule'
import { makeVoice, type Voice } from './voices'
import { MasterBus } from './master'
import { renderSong } from './offline'
import { JogModel, spinUp } from './jog'
import { TPQ } from '../lib/song'

/** A rendered copy of the song, forwards and backwards, for playing it like a record. */
interface RecordCopy { key: string; fwd: AudioBuffer; rev: AudioBuffer }
interface Deck {
  model: JogModel
  pos: number // seconds into the song
  rate: number // the rate last set
  last: number // ms
  src: AudioBufferSourceNode | null
  dir: 1 | -1
  out: Tone.Gain
  spin: { from: number; start: number } | null
  timer: ReturnType<typeof setInterval>
}

export interface EngineEvents { onPosition?(tick: number): void; onEnd?(): void; onLoadError?(assetId: string): void }

/**
 * Tone.js playback: one voice and one gain node per track, faders drive the gain.
 * The schedule is built from the song (pure, see schedule.ts); a song update only rebuilds it when notes or
 * instruments changed, so a fader or a mute never interrupts playback.
 */
export class PlaybackEngine {
  private song: Song | null = null
  private master = new MasterBus()
  private solo: TrackId | null = null
  private gains = new Map<TrackId, Tone.Gain>()
  private voices = new Map<TrackId, Voice>()
  private parts: Tone.Part[] = []
  private players: Tone.Player[] = []
  private raf = 0
  private loop: { from: number; to: number } | null = null
  private ended = false
  private gen = 0
  private record: RecordCopy | null = null
  private recordKey = ''
  private deck: Deck | null = null

  constructor(private assetUrl: (id: string) => string, private events: EngineEvents = {}) {
    Tone.getTransport().PPQ = 480
    for (const t of TRACK_IDS) {
      const g = new Tone.Gain(0).connect(this.master.input)
      this.gains.set(t, g)
    }
  }

  get playing() { return Tone.getTransport().state === 'started' }
  get tick() { return Tone.getTransport().ticks }

  async load(song: Song) {
    const d = diffForPlayback(this.song, song)
    this.song = song
    const tr = Tone.getTransport()
    if (d.tempo || d.rebuild) tr.bpm.value = song.tempo
    this.master.set(song.master.volume, song.master.space)
    if (d.gains || d.rebuild) this.applyGains()
    if (d.rebuild) this.rebuild()
  }

  private applyGains() {
    if (!this.song) return
    for (const t of TRACK_IDS) {
      const tr = this.song.tracks[t]
      this.gains.get(t)!.gain.rampTo(this.effective(t, tr.volume, tr.muted), 0.05)
    }
  }

  /** Moves a fader's gain now, before the server round trip has returned. */
  setTrackGain(track: TrackId, volume: number, muted: boolean) {
    this.gains.get(track)?.gain.rampTo(this.effective(track, volume, muted), 0.03)
  }

  private effective(track: TrackId, volume: number, muted: boolean) {
    return faderGain(volume, muted || (this.solo !== null && this.solo !== track))
  }

  /** "Only listen to this one": app-side, never sent to the server. */
  setSolo(track: TrackId | null) {
    this.solo = track
    this.applyGains()
  }

  /** Master volume and reverb while a slider is dragged, before the server round trip. */
  setMaster(volume: number, space: SpaceId) { this.master.set(volume, space) }

  private rebuild() {
    for (const p of this.parts) { p.dispose() }
    for (const p of this.players) { p.dispose() }
    this.parts = []; this.players = []
    for (const [t, v] of this.voices) { v.dispose(); this.voices.delete(t) }
    const song = this.song!
    const sched = buildSchedule(song)
    for (const t of TRACK_IDS) {
      if (t === 'ambience') continue
      this.voices.set(t, makeVoice(t, song.tracks[t].instrument, this.gains.get(t)!))
    }
    const byTrack = new Map<TrackId, NoteEvent[]>()
    for (const n of sched.notes) byTrack.set(n.track, [...(byTrack.get(n.track) ?? []), n])
    for (const [t, list] of byTrack) {
      const voice = this.voices.get(t)!
      const part = new Tone.Part<{ time: string; n: NoteEvent }>((time, v) => voice.trigger(v.n, time, Tone.Ticks(v.n.duration).toSeconds()), list.map((n) => ({ time: `${n.tick}i`, n })))
      part.start(0)
      this.parts.push(part)
    }
    const clips = [...sched.clips.map((c) => ({ ...c, track: 'ambience' as TrackId }))]
    if (sched.vocalAssetId) clips.push({ assetId: sched.vocalAssetId, tick: 0, duration: sched.endTick, offsetSec: 0, loop: false, gain: 1, track: 'vocal' })
    const gen = ++this.gen
    for (const c of clips) {
      // A clip that cannot be loaded is skipped: the song still plays without it.
      const url = this.assetUrl(c.assetId)
      if (!url) { this.events.onLoadError?.(c.assetId); continue }
      const buffer = new Tone.ToneAudioBuffer(
        url,
        () => {
          if (gen !== this.gen) { buffer.dispose(); return } // the song changed while the file was loading
          const player = new Tone.Player(buffer)
          player.loop = c.loop
          player.volume.value = Tone.gainToDb(Math.max(0.0001, c.gain))
          player.connect(this.gains.get(c.track)!)
          player.sync().start(`${c.tick}i`, c.offsetSec).stop(`${c.tick + c.duration}i`)
          this.players.push(player)
        },
        () => this.events.onLoadError?.(c.assetId),
      )
    }
    this.applyLoop()
  }

  /** Loops the given tick range (the section being edited) or the whole song when null. */
  setLoop(range: { from: number; to: number } | null) {
    this.loop = range
    this.applyLoop()
  }

  private applyLoop() {
    const tr = Tone.getTransport()
    if (this.loop) {
      tr.loopStart = `${this.loop.from}i`
      tr.loopEnd = `${this.loop.to}i`
      tr.loop = true
    } else {
      tr.loop = false
    }
  }

  async play() {
    await Tone.start()
    if (!this.song) return
    const tr = Tone.getTransport()
    const end = buildSchedule(this.song).endTick
    if (!this.loop && tr.ticks >= end) tr.ticks = 0
    if (this.loop && (tr.ticks < this.loop.from || tr.ticks >= this.loop.to)) tr.ticks = this.loop.from
    this.ended = false
    tr.start()
    this.follow()
  }

  /** Reports the play position every frame and stops at the end of the song. */
  private follow() {
    const tr = Tone.getTransport()
    const end = buildSchedule(this.song!).endTick
    const loopFn = () => {
      this.events.onPosition?.(tr.ticks)
      if (!this.loop && tr.ticks >= end && !this.ended) { this.ended = true; this.stop(); this.events.onEnd?.(); return }
      this.raf = requestAnimationFrame(loopFn)
    }
    cancelAnimationFrame(this.raf)
    this.raf = requestAnimationFrame(loopFn)
  }

  // ---- the platter as a record ----------------------------------------------------------------

  /**
   * Renders the song in the background so that the platter can play it like a record. Called when playback starts;
   * a song changed since then is rendered again on the next platter turn (that turn moves the position instead).
   */
  prepareJog() {
    const song = this.song
    if (!song) return
    const key = `${song.id}:${song.revision}`
    if (this.recordKey === key) return
    this.recordKey = key
    void renderSong(song, this.assetUrl).then((fwd) => {
      if (this.recordKey !== key) return
      const ctx = Tone.getContext().rawContext as unknown as BaseAudioContext
      const rev = ctx.createBuffer(fwd.numberOfChannels, fwd.length, fwd.sampleRate)
      for (let c = 0; c < fwd.numberOfChannels; c++) rev.getChannelData(c).set(fwd.getChannelData(c).slice().reverse())
      this.record = { key, fwd, rev }
    }).catch((e) => { console.warn('render for the platter failed', e); if (this.recordKey === key) this.recordKey = '' })
  }

  /**
   * A platter turn while playing: the song follows the platter, faster, slower or backwards, pitch included, and
   * spins back up to normal speed when the hand lets go. False when the rendered copy is not ready (or not playing):
   * the caller then moves the play position instead.
   */
  jog(delta: number): boolean {
    const song = this.song
    if (!song) return false
    const now = performance.now()
    if (!this.deck) {
      const rec = this.record
      if (!rec || rec.key !== `${song.id}:${song.revision}`) { this.prepareJog(); return false }
      if (!this.playing) return false
      const tr = Tone.getTransport()
      const pos = (tr.ticks / TPQ) * (60 / song.tempo)
      tr.pause()
      cancelAnimationFrame(this.raf)
      const out = new Tone.Gain(1).toDestination()
      this.deck = { model: new JogModel(), pos, rate: 1, last: now, src: null, dir: 1, out, spin: null, timer: setInterval(() => this.turnDeck(), 20) }
      this.setDeckRate(1)
    }
    this.deck.spin = null
    this.deck.model.feed(delta, now)
    return true
  }

  private turnDeck() {
    const d = this.deck, rec = this.record, song = this.song
    if (!d || !rec || !song) return
    const now = performance.now()
    const dur = rec.fwd.duration
    d.pos = Math.max(0, Math.min(dur, d.pos + d.rate * ((now - d.last) / 1000)))
    d.last = now
    let rate: number
    if (d.spin) {
      const s = spinUp(d.spin.from, now - d.spin.start)
      if (s.done) { this.leaveDeck(true); return }
      rate = s.rate
    } else if (d.model.released(now)) {
      d.spin = { from: d.model.rate(now), start: now }
      rate = d.spin.from
    } else rate = d.model.rate(now)
    this.setDeckRate(rate)
    this.events.onPosition?.(Math.round((d.pos * song.tempo / 60) * TPQ))
  }

  private setDeckRate(rate: number) {
    const d = this.deck, rec = this.record
    if (!d || !rec) return
    const ctx = Tone.getContext().rawContext as unknown as AudioContext
    const dir: 1 | -1 = rate < 0 ? -1 : 1
    if (!d.src || dir !== d.dir) {
      d.src?.stop()
      d.src?.disconnect()
      const src = ctx.createBufferSource()
      src.buffer = dir > 0 ? rec.fwd : rec.rev
      Tone.connect(src, d.out)
      const offset = dir > 0 ? d.pos : rec.fwd.duration - d.pos
      src.playbackRate.value = Math.max(Math.abs(rate), 0.0001)
      src.start(ctx.currentTime, Math.max(0, Math.min(rec.fwd.duration - 0.001, offset)))
      d.src = src
      d.dir = dir
    } else {
      d.src.playbackRate.setTargetAtTime(Math.max(Math.abs(rate), 0.0001), ctx.currentTime, 0.015)
    }
    d.rate = rate
  }

  /** Back from the record to the live instruments, at the record's position; `resume` starts them playing. */
  private leaveDeck(resume: boolean) {
    const d = this.deck, song = this.song
    if (!d) return
    this.deck = null
    clearInterval(d.timer)
    d.out.gain.rampTo(0, 0.02)
    const src = d.src, out = d.out
    setTimeout(() => { try { src?.stop() } catch { /* already stopped */ } src?.disconnect(); out.dispose() }, 60)
    if (!song) return
    const tr = Tone.getTransport()
    let tick = Math.round((d.pos * song.tempo / 60) * TPQ)
    if (this.loop && (tick < this.loop.from || tick >= this.loop.to)) tick = this.loop.from
    tr.ticks = tick
    this.events.onPosition?.(tick)
    if (resume) { tr.start(); this.follow() }
  }

  /** Stops and keeps the position (pause). */
  stop() {
    if (this.deck) this.leaveDeck(false)
    cancelAnimationFrame(this.raf)
    Tone.getTransport().pause()
    this.events.onPosition?.(Tone.getTransport().ticks)
  }

  seek(tick: number) {
    if (this.deck && this.song) { this.deck.pos = (Math.max(0, tick) / TPQ) * (60 / this.song.tempo); return }
    Tone.getTransport().ticks = Math.max(0, Math.round(tick))
    this.events.onPosition?.(Tone.getTransport().ticks)
  }

  dispose() {
    if (this.deck) this.leaveDeck(false)
    cancelAnimationFrame(this.raf)
    Tone.getTransport().stop()
    for (const p of this.parts) p.dispose()
    for (const p of this.players) p.dispose()
    for (const v of this.voices.values()) v.dispose()
    for (const g of this.gains.values()) g.dispose()
    this.master.dispose()
  }
}
