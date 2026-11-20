/**
 * The platter as a record under the hand: platter detents give the speed and direction the song plays at.
 * The encoder has 24 detents a turn, so a record at 33⅓ rpm turns 13.3 detents a second: that is normal speed.
 * When the detents stop the record slows to a stop, as under a still hand; after `releaseMs` without a detent the
 * hand counts as lifted and the engine spins the song back up to normal speed.
 */
export const NORMAL_DETENTS_PER_SEC = (24 * 100) / 3 / 60

export interface JogOptions { releaseMs: number; maxRate: number; smoothing: number; holdMs: number; stopMs: number }
export const JOG_DEFAULTS: JogOptions = { releaseMs: 350, maxRate: 4, smoothing: 0.5, holdMs: 60, stopMs: 90 }

export class JogModel {
  private v = 0 // detents per second, smoothed
  private last = -Infinity
  private opts: JogOptions
  constructor(opts: Partial<JogOptions> = {}) { this.opts = { ...JOG_DEFAULTS, ...opts } }

  /** A platter turn of `delta` detents (negative is backwards) at time `now` in ms. */
  feed(delta: number, now: number) {
    const fresh = now - this.last > this.opts.releaseMs
    const dt = Math.max(0.02, Math.min(0.25, (now - this.last) / 1000))
    const inst = delta / dt
    this.v = fresh ? inst : this.v * (1 - this.opts.smoothing) + inst * this.opts.smoothing
    this.last = now
  }

  /** Playback rate at `now`: 1 is normal, negative plays backwards. Pitch follows, as on a record. */
  rate(now: number): number {
    const since = now - this.last
    const v = since > this.opts.holdMs ? this.v * Math.exp(-(since - this.opts.holdMs) / this.opts.stopMs) : this.v
    const r = v / NORMAL_DETENTS_PER_SEC
    return Math.max(-this.opts.maxRate, Math.min(this.opts.maxRate, r))
  }

  /** True once no detent came for `releaseMs`: the hand is off the record. */
  released(now: number) { return now - this.last >= this.opts.releaseMs }
}

/** Speed during the spin back up after the hand lets go: from `from` to 1 over `ms`. */
export function spinUp(from: number, elapsedMs: number, ms = 350): { rate: number; done: boolean } {
  const k = Math.max(0, Math.min(1, elapsedMs / ms))
  return { rate: from + (1 - from) * k, done: k >= 1 }
}
