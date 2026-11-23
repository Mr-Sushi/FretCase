import * as Tone from 'tone'

/**
 * Recorded instrument samples, served with the app from public/samples/ (see scripts/fetch-samples.py).
 * Buffers are decoded once and shared, so a voice built in an offline render uses them too.
 * Anything that cannot be loaded leaves that instrument on its synth patch (voices.ts): the song still plays.
 */
interface Manifest { pitched: Record<string, Record<string, string>>; drums: Record<string, Record<string, string>>; aliases: Record<string, string> }

export type SampleSet = { kind: 'pitched' | 'drums'; buffers: Map<string, AudioBuffer> }

const base = (): string => {
  const b = (import.meta as { env?: { BASE_URL?: string } }).env?.BASE_URL ?? '/'
  return `${b.endsWith('/') ? b : `${b}/`}samples/`
}

let manifest: Promise<Manifest | null> | null = null
const sets = new Map<string, SampleSet>()
const loading = new Map<string, Promise<SampleSet | null>>()

function loadManifest(): Promise<Manifest | null> {
  if (!manifest) {
    manifest = (async () => {
      try {
        if (typeof fetch !== 'function') return null
        const r = await fetch(`${base()}manifest.json`)
        return r.ok ? ((await r.json()) as Manifest) : null
      } catch { return null }
    })()
  }
  return manifest
}

/** The set's id after aliases ("ukulele" plays the nylon guitar files). */
function resolve(m: Manifest, instrument: string): string { return m.aliases[instrument] ?? instrument }

/** Samples already decoded for an instrument, or null (then the voice uses its synth patch). */
export function samplesFor(instrument: string): SampleSet | null {
  return sets.get(instrument) ?? null
}

function load(instrument: string): Promise<SampleSet | null> {
  const cached = loading.get(instrument)
  if (cached) return cached
  const p = (async () => {
    const m = await loadManifest()
    if (!m) return null
    const id = resolve(m, instrument)
    const kind = m.pitched[id] ? 'pitched' : m.drums[id] ? 'drums' : null
    if (!kind) return null
    const files = (kind === 'pitched' ? m.pitched : m.drums)[id]
    try {
      const entries = await Promise.all(Object.entries(files).map(async ([key, file]) => [key, (await Tone.ToneAudioBuffer.fromUrl(base() + file)).get()!] as const))
      const set: SampleSet = { kind, buffers: new Map(entries) }
      sets.set(instrument, set)
      return set
    } catch { return null }
  })()
  loading.set(instrument, p)
  p.then((s) => { if (!s) loading.delete(instrument) }, () => loading.delete(instrument)) // a failed load may be tried again later
  return p
}

/**
 * Loads the samples for these instruments. Resolves true when all of them are ready, false when any failed or
 * when `timeoutMs` passed first (the loads go on, so a later call finds them).
 */
export async function ensureSamples(instruments: string[], timeoutMs = 6000): Promise<boolean> {
  const todo = [...new Set(instruments)].filter((i) => !sets.has(i))
  if (!todo.length) return true
  const all = Promise.all(todo.map(load)).then((r) => r.every(Boolean))
  return Promise.race([all, new Promise<boolean>((res) => setTimeout(() => res(false), timeoutMs))])
}

/** For tests. */
export function resetSamples() { manifest = null; sets.clear(); loading.clear() }
