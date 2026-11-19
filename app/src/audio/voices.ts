import * as Tone from 'tone'
import type { TrackId } from '../types'
import { midiToHz } from '../lib/song'
import type { NoteEvent } from './schedule'

export interface Voice { trigger(n: NoteEvent, time: number, durSec: number): void; dispose(): void }

/**
 * Voices for the catalogue's instrument ids. No sample files are bundled yet, so every id maps to a synth patch;
 * an unknown id gets the track's default patch. Works in a live or an offline Tone context.
 */
export function makeVoice(track: TrackId, instrument: string, out: Tone.ToneAudioNode): Voice {
  const connect = <T extends Tone.ToneAudioNode>(n: T): T => { n.connect(out); return n }
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
  return {
    trigger(n, time, durSec) { synth.triggerAttackRelease(midiToHz(n.pitch), Math.max(0.05, durSec), time, n.velocity / 127) },
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
  return {
    trigger(n, time) {
      const v = n.velocity / 127
      if (n.pitch === 36 || n.pitch === 35) kick.triggerAttackRelease(hand ? 'G2' : 'C1', 0.2, time, v)
      else if (n.pitch === 38 || n.pitch === 40 || n.pitch === 39) snare.triggerAttackRelease(0.15, time, v)
      else hat.triggerAttackRelease(0.05, time, v)
    },
    dispose() { kick.dispose(); snare.dispose(); hat.dispose() },
  }
}
