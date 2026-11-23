import * as Tone from 'tone'
import type { SpaceId } from '../types'
import { faderGain } from './schedule'

/** Reverb settings for the master "space". */
export const SPACES: Record<SpaceId, { roomSize: number; wet: number }> = {
  dry: { roomSize: 0.2, wet: 0 },
  room: { roomSize: 0.55, wet: 0.14 },
  hall: { roomSize: 0.85, wet: 0.3 },
}

/** The song-wide bus: a gain for the master volume followed by an algorithmic reverb, then the speakers. */
export class MasterBus {
  readonly input: Tone.Gain
  private reverb: Tone.Freeverb
  constructor(volume = 0.8, space: SpaceId = 'room') {
    this.input = new Tone.Gain(faderGain(volume, false))
    this.reverb = new Tone.Freeverb({ roomSize: SPACES[space].roomSize, dampening: 3000, wet: SPACES[space].wet })
    this.input.connect(this.reverb)
    this.reverb.toDestination()
  }
  set(volume: number, space: SpaceId) {
    this.input.gain.rampTo(faderGain(volume, false), 0.05)
    this.reverb.roomSize.value = SPACES[space].roomSize
    this.reverb.wet.value = SPACES[space].wet
  }
  dispose() { this.input.dispose(); this.reverb.dispose() }
}
