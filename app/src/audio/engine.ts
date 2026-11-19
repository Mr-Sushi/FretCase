import * as Tone from 'tone'
import type { Song, SpaceId, TrackId } from '../types'
import { TRACK_IDS } from '../lib/song'
import { buildSchedule, diffForPlayback, faderGain, type NoteEvent } from './schedule'
import { makeVoice, type Voice } from './voices'
import { MasterBus } from './master'

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
    const loopFn = () => {
      this.events.onPosition?.(tr.ticks)
      if (!this.loop && tr.ticks >= end && !this.ended) { this.ended = true; this.stop(); this.events.onEnd?.(); return }
      this.raf = requestAnimationFrame(loopFn)
    }
    cancelAnimationFrame(this.raf)
    this.raf = requestAnimationFrame(loopFn)
  }

  /** Stops and keeps the position (pause). */
  stop() {
    cancelAnimationFrame(this.raf)
    Tone.getTransport().pause()
    this.events.onPosition?.(Tone.getTransport().ticks)
  }

  seek(tick: number) {
    Tone.getTransport().ticks = Math.max(0, Math.round(tick))
    this.events.onPosition?.(Tone.getTransport().ticks)
  }

  dispose() {
    cancelAnimationFrame(this.raf)
    Tone.getTransport().stop()
    for (const p of this.parts) p.dispose()
    for (const p of this.players) p.dispose()
    for (const v of this.voices.values()) v.dispose()
    for (const g of this.gains.values()) g.dispose()
    this.master.dispose()
  }
}
