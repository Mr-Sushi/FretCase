import * as Tone from 'tone'
import type { TrackId } from '../types'
import { midiToHz } from '../lib/song'
import type { NoteEvent } from './schedule'
import { samplesFor } from './samples'

export interface Voice { trigger(n: NoteEvent, time: number, durSec: number): void; dispose(): void }

/**
 * Monophonic Tone instruments throw "Start time must be strictly greater than previous start time" when two notes
 * land on the same instant (a bass note doubled after a register change, a kick and a fill on one tick).
 * Each such instrument gets its own clock that nudges a repeated time forward by a millisecond.
 */
function monoClock(): (time: number) => number {
  let last = -Infinity
  return (time) => { const t = Math.max(time, last + 0.001); last = t; return t }
}

/** How each sampled instrument is played: envelope and level (the files are loudness-normalised). */
const SAMPLED: Record<string, { attack?: number; release: number; gain: number; maxSec?: number }> = {
  'synth-male': { attack: 0.06, release: 0.35, gain: 1 },
  'synth-female': { attack: 0.05, release: 0.35, gain: 1 },
  'synth-soft': { attack: 0.15, release: 0.5, gain: -3 },
  piano: { release: 1.0, gain: 0 },
  harmonica: { attack: 0.02, release: 0.25, gain: -3 },
  whistle: { attack: 0.03, release: 0.25, gain: -5 },
  flute: { attack: 0.03, release: 0.3, gain: -3 },
  steel: { release: 0.7, gain: -11 },
  nylon: { release: 0.7, gain: -10 },
  'electric-clean': { release: 0.6, gain: -12 },
  ukulele: { release: 0.25, gain: -10, maxSec: 0.6 },
  'finger-bass': { release: 0.2, gain: -1 },
  'upright-bass': { release: 0.25, gain: 0 },
  'synth-bass': { release: 0.15, gain: -5 },
}
/** Drum hits: a General MIDI key that has no file of its own plays the nearest kind, at its own level. */
const DRUM_KEY: Record<number, number> = { 35: 36, 37: 38, 39: 38, 40: 38, 41: 36, 43: 36, 44: 42, 45: 38, 47: 38, 48: 38, 49: 51, 50: 38, 52: 51, 53: 51, 55: 51, 57: 51, 59: 51 }
const DRUM_LEVEL: Record<number, number> = { 36: 1, 38: 0.8, 42: 0.32, 46: 0.38, 51: 0.32 }

/**
 * Voices for the catalogue's instrument ids. An instrument whose samples are loaded (samples.ts) plays them;
 * otherwise, and for an unknown id, it falls back to a synth patch. Works in a live or an offline Tone context.
 */
export function makeVoice(track: TrackId, instrument: string, out: Tone.ToneAudioNode): Voice {
  const connect = <T extends Tone.ToneAudioNode>(n: T): T => { n.connect(out); return n }
  const set = samplesFor(instrument)
  if (set?.kind === 'drums' && track === 'drums') return sampledDrums(set.buffers, connect)
  if (set?.kind === 'pitched' && track !== 'drums' && track !== 'ambience') return sampledVoice(instrument, set.buffers, connect)
  if (track === 'drums') return drumVoice(instrument, connect)
  let synth: Tone.PolySynth | Tone.MonoSynth
  let gain = 0
  const poly = (osc: Tone.ToneOscillatorType, env: Partial<Tone.EnvelopeOptions>) =>
    new Tone.PolySynth(Tone.Synth, { oscillator: { type: osc } as never, envelope: env })
  switch (track) {
    case 'bass':
      if (instrument === 'upright-bass') synth = new Tone.MonoSynth({ oscillator: { type: 'sine' }, envelope: { attack: 0.03, decay: 0.3, sustain: 0.5, release: 0.3 }, filterEnvelope: { attack: 0.02, decay: 0.2, sustain: 0.3, baseFrequency: 150, octaves: 1.5 } })
      else if (instrument === 'synth-bass') synth = new Tone.MonoSynth({ oscillator: { type: 'sawtooth' }, envelope: { attack: 0.005, decay: 0.15, sustain: 0.6, release: 0.15 }, filterEnvelope: { attack: 0.005, decay: 0.2, sustain: 0.2, baseFrequency: 180, octaves: 2.5 } })
      else synth = new Tone.MonoSynth({ oscillator: { type: 'triangle' }, envelope: { attack: 0.01, decay: 0.2, sustain: 0.6, release: 0.2 }, filterEnvelope: { attack: 0.01, decay: 0.2, sustain: 0.4, baseFrequency: 120, octaves: 2 } })
      break
    case 'guitar':
      if (instrument === 'steel') synth = poly('sawtooth', { attack: 0.004, decay: 0.55, sustain: 0.04, release: 0.5 })
      else if (instrument === 'electric-clean') synth = poly('square', { attack: 0.004, decay: 0.7, sustain: 0.12, release: 0.5 })
      else if (instrument === 'ukulele') synth = poly('triangle', { attack: 0.003, decay: 0.35, sustain: 0.02, release: 0.3 })
      else synth = poly('triangle', { attack: 0.005, decay: 0.9, sustain: 0.05, release: 0.6 })
      gain = instrument === 'steel' || instrument === 'electric-clean' ? -8 : 0
      break
    case 'melody':
      if (instrument === 'harmonica') synth = poly('square', { attack: 0.04, decay: 0.2, sustain: 0.55, release: 0.25 })
      else if (instrument === 'whistle') synth = poly('sine', { attack: 0.08, decay: 0.1, sustain: 0.7, release: 0.3 })
      else if (instrument === 'flute') synth = poly('sine', { attack: 0.06, decay: 0.3, sustain: 0.5, release: 0.4 })
      else synth = poly('triangle', { attack: 0.005, decay: 1.0, sustain: 0.1, release: 0.8 })
      gain = instrument === 'harmonica' ? -10 : 0
      break
    default: // vocal guide tone
      if (instrument === 'synth-male') synth = poly('sawtooth', { attack: 0.05, decay: 0.2, sustain: 0.6, release: 0.3 })
      else if (instrument === 'synth-soft') synth = poly('sine', { attack: 0.1, decay: 0.2, sustain: 0.6, release: 0.5 })
      else synth = poly('triangle', { attack: 0.06, decay: 0.2, sustain: 0.6, release: 0.4 })
      gain = instrument === 'synth-male' ? -14 : -4
  }
  synth.volume.value = gain
  connect(synth)
  const at = synth instanceof Tone.MonoSynth ? monoClock() : (t: number) => t
  return {
    trigger(n, time, durSec) { synth.triggerAttackRelease(midiToHz(n.pitch), Math.max(0.05, durSec), at(time), n.velocity / 127) },
    dispose() { synth.dispose() },
  }
}

function drumVoice(instrument: string, connect: <T extends Tone.ToneAudioNode>(n: T) => T): Voice {
  const pop = instrument === 'pop-kit'
  const hand = instrument === 'hand-drum'
  const kick = connect(new Tone.MembraneSynth({ pitchDecay: hand ? 0.06 : 0.03, octaves: hand ? 3 : 5, envelope: { attack: 0.001, decay: pop ? 0.3 : 0.4, sustain: 0 } }))
  const snare = connect(new Tone.NoiseSynth({ noise: { type: pop ? 'white' : 'pink' }, envelope: { attack: 0.001, decay: pop ? 0.18 : 0.25, sustain: 0 } }))
  const hat = connect(new Tone.NoiseSynth({ noise: { type: 'white' }, envelope: { attack: 0.001, decay: 0.05, sustain: 0 } }))
  hat.volume.value = -12
  const kickAt = monoClock(), snareAt = monoClock(), hatAt = monoClock()
  return {
    trigger(n, time) {
      const v = n.velocity / 127
      if (n.pitch === 36 || n.pitch === 35) kick.triggerAttackRelease(hand ? 'G2' : 'C1', 0.2, kickAt(time), v)
      else if (n.pitch === 38 || n.pitch === 40 || n.pitch === 39) snare.triggerAttackRelease(0.15, snareAt(time), v)
      else hat.triggerAttackRelease(0.05, hatAt(time), v)
    },
    dispose() { kick.dispose(); snare.dispose(); hat.dispose() },
  }
}

function sampledVoice(instrument: string, buffers: Map<string, AudioBuffer>, connect: <T extends Tone.ToneAudioNode>(n: T) => T): Voice {
  const cfg = SAMPLED[instrument] ?? { release: 0.4, gain: -9 }
  const sampler = connect(new Tone.Sampler({ urls: Object.fromEntries(buffers) as never, attack: cfg.attack ?? 0, release: cfg.release }))
  sampler.volume.value = cfg.gain
  return {
    trigger(n, time, durSec) {
      const d = Math.max(0.05, cfg.maxSec ? Math.min(durSec, cfg.maxSec) : durSec)
      sampler.triggerAttackRelease(midiToHz(n.pitch), d, time, n.velocity / 127)
    },
    dispose() { sampler.dispose() },
  }
}

function sampledDrums(buffers: Map<string, AudioBuffer>, connect: <T extends Tone.ToneAudioNode>(n: T) => T): Voice {
  const urls: Record<string, AudioBuffer> = {}
  for (const [key, buf] of buffers) urls[Tone.Frequency(+key, 'midi').toNote()] = buf
  const sampler = connect(new Tone.Sampler({ urls: urls as never, release: 0.4 }))
  sampler.volume.value = 6
  return {
    trigger(n, time) {
      const key = buffers.has(String(n.pitch)) ? n.pitch : (DRUM_KEY[n.pitch] ?? 42)
      if (!buffers.has(String(key))) return
      const v = Math.min(1, (n.velocity / 127) * (DRUM_LEVEL[key] ?? 0.5))
      sampler.triggerAttackRelease(Tone.Frequency(key, 'midi').toNote(), 1.5, time, v)
    },
    dispose() { sampler.dispose() },
  }
}
