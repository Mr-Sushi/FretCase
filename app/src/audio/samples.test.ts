import { afterEach, describe, expect, it, vi } from 'vitest'
import { ensureSamples, resetSamples, samplesFor } from './samples'

afterEach(() => { resetSamples(); vi.unstubAllGlobals() })

describe('instrument samples', () => {
  it('fall back to the synth patch when the manifest cannot be loaded, without waiting for the timeout', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new Error('offline')))
    const started = Date.now()
    expect(await ensureSamples(['steel', 'jazz-kit'], 5000)).toBe(false)
    expect(Date.now() - started).toBeLessThan(1000)
    expect(samplesFor('steel')).toBeNull()
  })

  it('report an instrument the manifest does not list as not ready', async () => {
    vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ pitched: {}, drums: {}, aliases: {} })))
    expect(await ensureSamples(['steel'], 5000)).toBe(false)
  })

  it('have nothing to load for an empty list', async () => {
    expect(await ensureSamples([])).toBe(true)
  })

  it('every catalogue instrument has samples in the manifest', async () => {
    const fs = await import('node:fs')
    const m = JSON.parse(fs.readFileSync(new URL('../../public/samples/manifest.json', import.meta.url), 'utf-8'))
    const { DEFAULT_CATALOG } = await import('../lib/catalog')
    for (const [track, list] of Object.entries(DEFAULT_CATALOG.instruments)) {
      if (track === 'ambience') continue
      for (const inst of list as { id: string }[]) {
        const id = m.aliases[inst.id] ?? inst.id
        expect(m.pitched[id] ?? m.drums[id], `${track}/${inst.id}`).toBeTruthy()
        for (const file of Object.values(m.pitched[id] ?? m.drums[id]) as string[]) expect(fs.existsSync(new URL(`../../public/samples/${file}`, import.meta.url)), file).toBe(true)
      }
    }
  })
})
