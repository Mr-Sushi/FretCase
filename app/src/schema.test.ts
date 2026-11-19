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

  it('mock songs, candidates and edits stay valid', async () => {
    const api = new MockApi(0)
    const c = new Controller(api, new Store(initialState(true)), null)
    await c.init()
    const check = (label: string, song = c.store.state.song) => {
      const ok = validateSong(song)
      expect(ok, `${label}: ${JSON.stringify(validateSong.errors)}`).toBe(true)
    }
    await c.openSong('song-demo-0001'); check('open')
    await c.setVolume('drums', 0.3); check('volume')
    await c.setRegion('guitar', 's-verse', { complexity: 0.9, style: 'strum' }); check('setRegion')
    await c.copyRegion('guitar', 's-verse'); check('copyRegion')
    await c.setLead('s-verse', 'melody'); check('setLead')
    await c.shiftRegister('bass', 's-verse', 'up'); check('shiftRegister')
    await c.setMaster({ space: 'hall' }); check('setMaster')
    await c.another('s-verse', 'bass'); check('another')
    await c.setSectionLyrics('s-verse', ['晚风吹过海边的岸', '灯一盏一盏亮起来']); check('lyrics')
    await c.setCard({ style: 'ink', line: '一句话' }); check('setCard')
    await c.previewCard(); check('preview')
    await c.printCard(); check('print')
    c.addPhoto(new Blob(['x'])); c.setText('夜里下雨了')
    await c.makeSong()
    for (const s of c.store.state.candidates!) check(`candidate ${s.candidate!.index}`, s)
    await c.chooseCandidate(1); check('chosen')
  })
})
