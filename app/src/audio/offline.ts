import * as Tone from 'tone'
import type { Song, TrackId } from '../types'
import { TRACK_IDS, songSeconds, ticksToSeconds } from '../lib/song'
import { buildSchedule, faderGain } from './schedule'
import { makeVoice } from './voices'
import { MasterBus } from './master'

/** Plays a whole song into an AudioBuffer faster than real time (for the song page's "save"). */
export async function renderSong(song: Song, assetUrl: (id: string) => string): Promise<AudioBuffer> {
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

/** 16-bit PCM WAV file from an AudioBuffer. */
export function encodeWav(buf: AudioBuffer): Blob {
  const ch = buf.numberOfChannels, len = buf.length, rate = buf.sampleRate
  const data = new DataView(new ArrayBuffer(44 + len * ch * 2))
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) data.setUint8(o + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); data.setUint32(4, 36 + len * ch * 2, true); str(8, 'WAVE'); str(12, 'fmt ')
  data.setUint32(16, 16, true); data.setUint16(20, 1, true); data.setUint16(22, ch, true)
  data.setUint32(24, rate, true); data.setUint32(28, rate * ch * 2, true); data.setUint16(32, ch * 2, true); data.setUint16(34, 16, true)
  str(36, 'data'); data.setUint32(40, len * ch * 2, true)
  const chans = Array.from({ length: ch }, (_, i) => buf.getChannelData(i))
  let o = 44
  for (let i = 0; i < len; i++) for (let c = 0; c < ch; c++) {
    const v = Math.max(-1, Math.min(1, chans[c][i]))
    data.setInt16(o, v < 0 ? v * 0x8000 : v * 0x7fff, true); o += 2
  }
  return new Blob([data], { type: 'audio/wav' })
}
