import { describe, expect, it } from 'vitest'
import { JogModel, NORMAL_DETENTS_PER_SEC, spinUp } from './jog'

describe('jog', () => {
  it('turning at record speed plays at normal speed; faster is faster, backwards is negative', () => {
    const j = new JogModel()
    const step = 1000 / NORMAL_DETENTS_PER_SEC // ms between detents at 33⅓ rpm
    let t = 0
    for (let i = 0; i < 10; i++) { t += step; j.feed(1, t) }
    expect(j.rate(t)).toBeCloseTo(1, 1)
    for (let i = 0; i < 10; i++) { t += step / 2; j.feed(1, t) }
    expect(j.rate(t)).toBeCloseTo(2, 1)
    for (let i = 0; i < 10; i++) { t += step; j.feed(-1, t) }
    expect(j.rate(t)).toBeCloseTo(-1, 1)
  })

  it('slows to a stop under a still hand, then counts as released', () => {
    const j = new JogModel()
    for (let t = 75; t <= 750; t += 75) j.feed(1, t)
    expect(j.released(800)).toBe(false)
    expect(Math.abs(j.rate(1050))).toBeLessThan(0.1)
    expect(j.released(1100)).toBe(true)
  })

  it('caps the speed', () => {
    const j = new JogModel()
    j.feed(10, 0); j.feed(10, 20)
    expect(j.rate(20)).toBe(4)
  })

  it('spins back up to normal speed', () => {
    expect(spinUp(-1, 0)).toEqual({ rate: -1, done: false })
    expect(spinUp(0, 175).rate).toBeCloseTo(0.5)
    expect(spinUp(0.2, 400)).toEqual({ rate: 1, done: true })
  })
})
