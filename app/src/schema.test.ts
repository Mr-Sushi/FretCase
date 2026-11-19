import Ajv2020 from 'ajv/dist/2020.js'
import addFormats from 'ajv-formats'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { Controller } from './app/controller'
import { Store, initialState } from './app/store'
import { MockApi } from './api'
import { PanelClient } from './panel/client'

const shared = join(__dirname, '..', '..', 'shared', 'schema')
const load = (f: string) => JSON.parse(readFileSync(join(shared, f), 'utf8'))
const ajv = new Ajv2020({ strict: false, allErrors: true })
addFormats(ajv)
const validateSong = ajv.compile(load('song.schema.json'))
const validatePanel = ajv.compile(load('panel-events.schema.json'))

describe('what the app sends and shows conforms to the shared schemas', () => {
  it('every message the panel client sends validates against the panel schema', () => {
    const sent: unknown[] = []
    class WS {
      readyState = 1
      onopen: (() => void) | null = null
      onmessage = null; onclose = null; onerror = null
      constructor() { setTimeout(() => this.onopen?.(), 0) }
      send(s: string) { sent.push(JSON.parse(s)) }
      close() {}
    }
    const c = new PanelClient('ws://x', () => {}, () => {}, WS as unknown as typeof WebSocket)
    c.start()
    return new Promise<void>((resolve) => setTimeout(() => {
      c.setRing(Array.from({ length: 16 }, (_, i) => (i % 2 ? '#e08a12' : null)), 0.6)
      c.setKeyLight('track.guitar', 'on', '#49b8b3')
      c.setKeyLight('capture', 'blink')
      c.send({ type: 'ping' })
      for (const m of sent) expect(validatePanel(m), JSON.stringify([m, validatePanel.errors])).toBe(true)
      expect(sent.length).toBe(5)
      c.stop()
      resolve()
    }, 5))
  })

  it('mock songs stay valid through generation and edits', async () => {
    const api = new MockApi(0)
    const c = new Controller(api, new Store(initialState(true)), null)
    await c.init()
    const check = (label: string) => {
      const ok = validateSong(c.store.state.song)
      expect(ok, `${label}: ${JSON.stringify(validateSong.errors)}`).toBe(true)
    }
    await c.openSong('song-hai-bian-01'); check('open')
    await c.setVolume('drums', 0.3); check('volume')
    await c.setControl('density', 0.9); check('density')
    await c.another('s-verse', 'bass'); check('another')
    await c.replaceNotes('guitar', 0, 1920, [{ start: 0, duration: 480, pitch: 64 }]); check('replaceNotes')
    await c.setLyrics('s-intro', '海风吹过傍晚'); check('lyrics')
    await c.toggleLock('bass'); check('lock')
    await c.previewCard(); check('preview')
    await c.printCard(); check('print')
    c.addText('夜里下雨了')
    await c.makeSeed()
    await c.generate(); check('new song')
  })
})
