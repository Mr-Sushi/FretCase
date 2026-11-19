import exampleSong from '../generated/example-song.json'
import presetsFile from '../generated/rhythm-presets.json'
import type { Catalog, Note, RhythmPreset, SeedCard, SeedInput, Song, TrackId } from '../types'
import { barTicks, clamp, hasExactLock, isLocked, sectionRange, snapToKey, tonicPc, TRACK_IDS } from '../lib/song'
import { ApiError, type Api, type AssetRole, type EditOp, type Health, type SongListItem } from './types'

const presets = (presetsFile as { presets: RhythmPreset[] }).presets

export const MOCK_CATALOG: Catalog = {
  instruments: {
    vocal: ['synth-female', 'synth-male'],
    melody: ['piano', 'nylon-lead'],
    guitar: ['nylon', 'steel'],
    bass: ['finger-bass'],
    drums: ['brush-kit', 'pop-kit'],
    ambience: ['recording'],
  },
  rhythmPresets: { presets },
  cardStyles: ['ink', 'comic', 'xieyi', 'original', 'text'],
}

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))
const now = () => new Date().toISOString()
const rid = (n = 6) => Array.from({ length: n }, () => 'abcdefghjkmnpqrstuvwxyz23456789'[Math.floor(Math.random() * 31)]).join('')

/** Svg placeholder for card images in mock mode. */
function cardSvg(title: string, side: 'front' | 'back', style: string): string {
  const body = side === 'front'
    ? `<text x="192" y="250" font-size="26" text-anchor="middle" fill="#2b1d14">${style}</text>`
    : `<rect x="112" y="150" width="160" height="160" fill="none" stroke="#2b1d14" stroke-width="6"/><text x="192" y="350" font-size="20" text-anchor="middle" fill="#2b1d14">${title}</text>`
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="384" height="480" viewBox="0 0 384 480"><rect width="384" height="480" fill="#f4ecdc"/>${body}</svg>`
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
}

interface Stored { song: Song; history: Song[]; previewSig?: string; anotherCount: Record<string, number> }

/** In-memory stand-in for the server: serves the example song and applies edits locally. Not musically clever. */
export class MockApi implements Api {
  readonly mock = true
  private songs = new Map<string, Stored>()
  private blobs = new Map<string, string>()
  private city = '纽卡斯尔'
  /** Milliseconds to wait before answering, to feel like a network. */
  constructor(private latency = 0) {
    const s = clone(exampleSong) as unknown as Song
    this.songs.set(s.id, { song: s, history: [], anotherCount: {} })
  }

  private async tick() { if (this.latency) await new Promise((r) => setTimeout(r, this.latency)) }
  private get(id: string): Stored {
    const s = this.songs.get(id)
    if (!s) throw new ApiError('not_found', '没有这首歌', 404)
    return s
  }
  private checkRev(st: Stored, base: number) {
    if (st.song.revision !== base) throw new ApiError('revision_conflict', `Song is at revision ${st.song.revision}`, 409, clone(st.song))
  }
  /** Runs a mutation on a copy; on success stores it as the next revision and pushes the previous one on the undo stack. */
  private commit(st: Stored, mutate: (s: Song) => void, undoable = true): Song {
    const next = clone(st.song)
    mutate(next)
    if (undoable) { st.history.push(st.song); if (st.history.length > 50) st.history.shift() }
    next.revision = st.song.revision + 1
    next.updatedAt = now()
    st.song = next
    return clone(next)
  }

  async health(): Promise<Health> { return { ok: true, online: false, version: 'mock', panel: false } }
  async catalog() { return clone(MOCK_CATALOG) }

  async uploadAsset(file: Blob, role: AssetRole) {
    await this.tick()
    const id = `a-${role.replace('_', '-')}-${rid()}`
    this.blobs.set(id, URL.createObjectURL(file))
    return { id, role, mime: file.type || 'application/octet-stream' }
  }
  assetUrl(id: string) {
    const b = this.blobs.get(id)
    if (b) return b
    const m = /^card-(front|back)-(.+)$/.exec(id)
    if (m) {
      const st = [...this.songs.values()].find((s) => s.song.assets.some((a) => a.id === id))
      return cardSvg(st?.song.title ?? '', m[1] as 'front' | 'back', st?.song.card?.style ?? 'ink')
    }
    return ''
  }

  async createSeed(inputs: SeedInput[]): Promise<SeedCard> {
    await this.tick()
    const text = inputs.filter((i) => i.kind === 'text').map((i) => i.text ?? '').join(' ')
    const sad = /(雨|夜|想|难过|孤|冷)/.test(text)
    const hasHum = inputs.some((i) => i.kind === 'hum')
    const key = { tonic: sad ? 'A' : 'D', mode: sad ? 'minor' : 'major' } as const
    const motif: Note[] = [0, 2, 4, 2, 0, -1, 0, 2].map((d, i) => ({ start: i * 480, duration: 480, pitch: 62 + d + (sad ? 3 : 0), velocity: 90 }))
    return {
      inputs: inputs as SeedCard['inputs'],
      key,
      tempo: sad ? 72 : 88,
      meter: { numerator: 4, denominator: 4 },
      mood: sad ? '安静偏冷' : '平静偏暖',
      ...(hasHum ? { motif } : {}),
      instruments: { melody: 'piano', guitar: 'nylon', drums: 'brush-kit' },
      reasons: [
        { field: 'key', text: sad ? '文字偏忧伤，所以用小调' : '没有特别的线索，用明亮的大调' },
        { field: 'tempo', text: sad ? '情绪偏慢，所以速度放慢' : '中速，适合边走边听' },
        ...(hasHum ? [{ field: 'motif' as const, text: '哼唱转成了八个音的旋律动机' }] : []),
      ],
      source: 'offline',
    }
  }

  async createSong(seed: SeedCard, bars = 16): Promise<Song> {
    await this.tick()
    const base = clone(exampleSong) as unknown as Song
    const id = `song-${rid(8)}`
    const shift = tonicPc(seed.key.tonic) - tonicPc(base.key.tonic)
    const mode = seed.key.mode !== base.key.mode ? (seed.key.mode === 'minor' ? -3 : 3) : 0
    const move = (n: Note) => ({ ...n, pitch: clamp(n.pitch + shift + mode, 0, 127) })
    const song: Song = {
      ...base, id, revision: 0, createdAt: now(), updatedAt: now(),
      title: `${seed.mood}的歌`, key: seed.key, tempo: seed.tempo, meter: seed.meter ?? base.meter, bars,
      seed: clone(seed), locks: [], controls: { brightness: 0.5, complexity: 0.5, density: 0.5 }, assets: [],
      card: { style: 'ink', showPhoto: false, showCity: false, share: { shareId: rid(12).padEnd(12, 'x'), url: `https://fretcase.example/s/${rid(12).padEnd(12, 'x')}`, state: 'reserved' } },
    }
    song.card!.share!.url = `https://fretcase.example/s/${song.card!.share!.shareId}`
    for (const t of ['vocal', 'melody', 'guitar', 'bass', 'drums'] as const) {
      const tr = song.tracks[t]
      tr.volume = 0.8; tr.muted = false
      if (t !== 'drums') tr.notes = (tr.notes as Note[]).map(move) as never
    }
    if (seed.motif?.length) song.tracks.melody.notes = seed.motif.map((n) => ({ ...n }))
    song.tracks.ambience.volume = 0.5
    const amb = seed.inputs.find((i) => i.kind === 'sound')
    song.tracks.ambience.clips = amb?.assetId ? [{ assetId: amb.assetId, start: 0, duration: songEnd(song), loop: true, gain: 0.8 }] : []
    for (const i of seed.inputs) {
      if (i.assetId) song.assets.push({ id: i.assetId, role: i.kind === 'sound' ? 'ambience' : (i.kind as 'hum' | 'photo'), mime: 'application/octet-stream' })
    }
    const photo = seed.inputs.find((i) => i.kind === 'photo')
    if (photo?.assetId) song.card!.photoAssetId = photo.assetId
    this.songs.set(id, { song, history: [], anotherCount: {} })
    return clone(song)
  }

  async listSongs(): Promise<SongListItem[]> {
    return [...this.songs.values()].map((s) => ({ id: s.song.id, title: s.song.title, updatedAt: s.song.updatedAt })).reverse()
  }
  async getSong(id: string) { await this.tick(); return clone(this.get(id).song) }

  async edit(id: string, baseRevision: number, ops: EditOp[]): Promise<Song> {
    await this.tick()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    // Validate on a trial copy first so that a failing op leaves the song untouched.
    const trial = clone(st.song)
    for (const op of ops) applyOp(trial, op)
    return this.commit(st, (s) => { for (const op of ops) applyOp(s, op) })
  }

  async another(id: string, baseRevision: number, section: string, track?: TrackId): Promise<Song> {
    await this.tick()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    const sec = st.song.sections.find((s) => s.id === section)
    if (!sec) throw new ApiError('cannot_apply', '没有这一段', 422)
    const key = `${section}:${track ?? '*'}`
    const n = (st.anotherCount[key] = (st.anotherCount[key] ?? 0) + 1)
    return this.commit(st, (s) => {
      const range = sectionRange(s, sec)
      const targets = (track ? [track] : TRACK_IDS).filter((t) => t !== 'ambience' && !isLocked(s, t, section))
      for (const t of targets) {
        if (t === 'drums' || t === 'ambience') continue
        const notes = s.tracks[t].notes as Note[]
        // Mock "take": move pitches in the section by a few scale steps, different each time.
        const step = [2, -2, 4, -4][n % 4]
        for (const note of notes) {
          if (note.start >= range.from && note.start < range.to) note.pitch = snapToKey(clamp(note.pitch + step, 24, 100), s.key)
        }
      }
      s.provenance = { ...(s.provenance ?? {}), harmonySource: 'rule' }
    })
  }

  async rehum(id: string, baseRevision: number, section: string): Promise<Song> {
    await this.tick()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    if (!st.song.sections.some((s) => s.id === section)) throw new ApiError('cannot_apply', '没有这一段', 422)
    return this.commit(st, () => { /* mock: melody unchanged */ })
  }

  async undo(id: string, baseRevision: number): Promise<Song> {
    await this.tick()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    const prev = st.history.pop()
    if (!prev) throw new ApiError('cannot_apply', '没有可撤销的操作', 422)
    const restored = clone(prev)
    restored.revision = st.song.revision + 1
    restored.updatedAt = now()
    st.song = restored
    return clone(restored)
  }

  async cardPreview(id: string, baseRevision: number): Promise<Song> {
    await this.tick()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    const song = this.commit(st, (s) => {
      const f = `card-front-${rid()}`, b = `card-back-${rid()}`
      s.assets = s.assets.filter((a) => a.role !== 'card_front' && a.role !== 'card_back')
      s.assets.push({ id: f, role: 'card_front', mime: 'image/svg+xml' }, { id: b, role: 'card_back', mime: 'image/svg+xml' })
      s.card = { ...s.card!, frontAssetId: f, backAssetId: b }
      delete s.card.printedAt
    }, false)
    st.previewSig = cardSig(song)
    return song
  }

  async cardPrint(id: string, baseRevision: number): Promise<Song> {
    await this.tick()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    if (!st.song.card?.frontAssetId || st.previewSig !== cardSig(st.song)) throw new ApiError('cannot_apply', '请先预览', 422)
    return this.commit(st, (s) => { s.card = { ...s.card!, printedAt: now() } }, false)
  }

  async resolveShare(shareId: string): Promise<string> {
    const st = [...this.songs.values()].find((s) => s.song.card?.share?.shareId === shareId)
    if (!st) throw new ApiError('not_found', '这张卡片的歌不在这台设备上', 404)
    return st.song.id
  }
  async getLocation() { return { city: this.city, source: 'manual' as const } }
  async putLocation(city: string) { this.city = city }
  async studyLog() { /* dropped in mock mode */ }
}

function songEnd(s: Pick<Song, 'meter' | 'bars'>) { return barTicks(s.meter) * s.bars }
const cardSig = (s: Song) => JSON.stringify({ ...s.card, frontAssetId: 0, backAssetId: 0, printedAt: 0, share: 0, title: s.title })

function applyOp(s: Song, op: EditOp): void {
  const secIds = new Set(s.sections.map((x) => x.id))
  switch (op.op) {
    case 'setControl': {
      s.controls[op.control] = clamp(op.value, 0, 1)
      if (op.control === 'density' && !isLocked(s, 'guitar', null)) {
        const level = op.value < 0.33 ? 'start' : op.value < 0.67 ? 'next' : 'challenge'
        const meter = `${s.meter.numerator}/${s.meter.denominator}`
        const cands = presets.filter((p) => p.meter === meter)
        const pick = cands.find((p) => p.level === level) ?? cands[0]
        if (pick) s.tracks.guitar.rhythm = { family: pick.family, presetId: pick.id }
      }
      return
    }
    case 'setTempo': s.tempo = clamp(op.tempo, 40, 220); return
    case 'setTrackVolume': s.tracks[op.track].volume = clamp(op.volume, 0, 1); return
    case 'setTrackMute': s.tracks[op.track].muted = op.muted; return
    case 'setInstrument': s.tracks[op.track].instrument = op.instrument; return
    case 'replaceNotes': {
      if (op.track === 'ambience') throw new ApiError('cannot_apply', '环境声不能改音符', 422)
      const tr = s.tracks[op.track]
      const kept = (tr.notes as Note[]).filter((n) => n.start < op.from || n.start >= op.to)
      const lyrics = op.track === 'vocal' ? (tr.notes as Note[]) : []
      const fresh = op.notes.map((n) => ({ velocity: 90, ...n }))
      ;(tr as { notes: Note[] }).notes = [...kept, ...fresh].sort((a, b) => a.start - b.start || a.pitch - b.pitch)
      void lyrics
      for (const sec of s.sections) {
        const r = sectionRange(s, sec)
        if (op.from < r.to && op.to > r.from && !hasExactLock(s, op.track, sec.id)) s.locks.push({ track: op.track, section: sec.id })
      }
      return
    }
    case 'setLyrics': {
      const sec = s.sections.find((x) => x.id === op.section)
      if (!sec) throw new ApiError('cannot_apply', '没有这一段', 422)
      const r = sectionRange(s, sec)
      const notes = s.tracks.vocal.notes.filter((n) => n.start >= r.from && n.start < r.to)
      const chars = [...op.text.replace(/\s+/g, '')]
      if (chars.length !== notes.length) {
        throw new ApiError('cannot_apply', '字数和音数不一样', 422, undefined, { noteCount: notes.length, syllableCount: chars.length })
      }
      notes.forEach((n, i) => { n.lyric = chars[i] })
      return
    }
    case 'setRhythm': s.tracks.guitar.rhythm = { family: op.family, presetId: op.presetId }; return
    case 'lock':
    case 'unlock': {
      if (!op.track && !op.section) throw new ApiError('invalid_request', '需要音轨或段落', 400)
      if (op.section && !secIds.has(op.section)) throw new ApiError('cannot_apply', '没有这一段', 422)
      if (op.op === 'lock') { if (!hasExactLock(s, op.track, op.section)) s.locks.push({ ...(op.track ? { track: op.track } : {}), ...(op.section ? { section: op.section } : {}) }) }
      else s.locks = s.locks.filter((l) => !(l.track === op.track && l.section === op.section))
      return
    }
    case 'setSections': {
      let bar = 0
      for (const sec of op.sections) { if (sec.startBar !== bar) throw new ApiError('cannot_apply', '段落必须连续', 422); bar = sec.endBar }
      if (bar !== s.bars) throw new ApiError('cannot_apply', '段落必须覆盖全部小节', 422)
      s.sections = op.sections as Song["sections"]
      return
    }
    case 'setTitle': s.title = op.title.slice(0, 80); return
    case 'setCard': {
      const { op: _op, ...patch } = op
      void _op
      s.card = { ...(s.card ?? { style: 'ink', showPhoto: false, showCity: false }), ...patch } as Song['card']
      return
    }
  }
}

