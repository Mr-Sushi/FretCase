import * as Tone from 'tone'
import type { Song, TrackId } from '../types'
import { TRACK_IDS, songSeconds, ticksToSeconds } from '../lib/song'
import { buildSchedule, faderGain } from './schedule'
import { makeVoice } from './voices'
import { ensureSamples } from './samples'
import { MasterBus } from './master'

/** Plays a whole song into an AudioBuffer faster than real time (for the song page's "save"). */
export async function renderSong(song: Song, assetUrl: (id: string) => string): Promise<AudioBuffer> {
  await ensureSamples(TRACK_IDS.filter((t) => t !== 'ambience').map((t) => song.tracks[t].instrument), 8000)
  const sched = buildSchedule(song)
  const seconds = songSeconds(song) + 2
  const clips = await Promise.all([...sched.clips.map((c) => ({ ...c, track: 'ambience' as TrackId })), ...(sched.vocalAssetId ? [{ assetId: sched.vocalAssetId, tick: 0, duration: sched.endTick, offsetSec: 0, loop: false, gain: 1, track: 'vocal' as TrackId }] : [])]
    .map(async (c) => {
      const url = assetUrl(c.assetId)
      if (!url) return null
      try { return { c, buffer: await Tone.ToneAudioBuffer.fromUrl(url) } } catch { return null }
    }))
  const rendered = await Tone.Offline(() => {
    const master = new MasterBus(song.master.volume, song.master.space)
    const gains = new Map<TrackId, Tone.Gain>()
    for (const t of TRACK_IDS) {
      const tr = song.tracks[t]
      gains.set(t, new Tone.Gain(faderGain(tr.volume, tr.muted)).connect(master.input))
    }
    const voices = new Map<TrackId, ReturnType<typeof makeVoice>>()
    for (const t of TRACK_IDS) if (t !== 'ambience') voices.set(t, makeVoice(t, song.tracks[t].instrument, gains.get(t)!))
    for (const n of sched.notes) voices.get(n.track)!.trigger(n, ticksToSeconds(n.tick, song.tempo), ticksToSeconds(n.duration, song.tempo))
    for (const k of clips) {
      if (!k) continue
      const p = new Tone.Player(k.buffer)
      p.loop = k.c.loop
      p.volume.value = Tone.gainToDb(Math.max(0.0001, k.c.gain))
      p.connect(gains.get(k.c.track)!)
      p.start(ticksToSeconds(k.c.tick, song.tempo), k.c.offsetSec, ticksToSeconds(k.c.duration, song.tempo))
    }
  }, seconds, 2, 44100)
  return rendered.get() as AudioBuffer
}

export { encodeWav } from './wav'
