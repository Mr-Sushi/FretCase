import type { Catalog, Note, SeedCard, SeedInput, SharePage, Song, TrackId } from '../types'
import { DEFAULT_CATALOG } from '../lib/catalog'
import { clamp, hasExactLock, isLocked, sectionRange, snapToKey } from '../lib/song'
import { sectionLines, syllables } from '../lib/lyrics'
import { ApiError, type Api, type AssetRole, type CandidateRequest, type EditOp, type Health, type LyricsAlternative, type LyricsRequest, type LyricsRewriteRequest, type LyricsTheme, type PrinterStatus, type SongListItem } from './types'
import { MOCK_POOL, VARIANT_SETS, buildMockSong, clone, regenerateUnlocked, replaceTrackSection, rid } from './mockSong'

export const MOCK_CATALOG: Catalog = clone(DEFAULT_CATALOG)
const now = () => new Date().toISOString()

const PHOTO_GRADIENTS = [['#f2a65a', '#7a3b2e', '#2b1d14'], ['#9ec5d6', '#4d6d86', '#1f2d3a'], ['#e8c27a', '#a8613a', '#43261a'], ['#b9a2d6', '#5b4a85', '#241c3a']]
function svgUrl(svg: string) { return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg) }
/** Stand-in for a photo the mock does not have: a dusk gradient. */
function photoSvg(id: string): string {
  const g = PHOTO_GRADIENTS[[...id].reduce((a, c) => a + c.charCodeAt(0), 0) % PHOTO_GRADIENTS.length]
  return svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${g[0]}"/><stop offset="0.55" stop-color="${g[1]}"/><stop offset="1" stop-color="${g[2]}"/></linearGradient></defs><rect width="1200" height="800" fill="url(#g)"/><circle cx="820" cy="400" r="90" fill="#fff3d6" opacity="0.85"/><rect y="520" width="1200" height="280" fill="#000" opacity="0.25"/></svg>`)
}
/** Stand-in for the print image: photo on top, paper strip below with title, line and a code mark. */
function cardSvg(song: Song): string {
  const c = song.card
  const esc = (s: string) => s.replace(/[<>&]/g, '')
  const date = (c?.capturedAt ?? song.createdAt).slice(0, 10).replace(/-/g, '.')
  const meta = `${c?.showCity && c.city ? c.city + ' · ' : ''}${date}`
  const text = c?.style === 'text'
  let code = ''
  for (let y = 0; y < 9; y++) for (let x = 0; x < 9; x++) if ((x * 7 + y * 13 + x * y) % 3 === 0 || (x < 3 && y < 3)) code += `<rect x="${1040 + x * 19}" y="${640 + y * 19}" width="19" height="19" fill="#3a2a1e"/>`
  const top = text
    ? `<rect width="1260" height="610" fill="#f7f1e4"/><text x="630" y="330" font-size="64" text-anchor="middle" fill="#3a2a1e" font-family="serif">${esc(c?.line || song.title)}</text>`
    : `<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e8c27a"/><stop offset="0.6" stop-color="#a8613a"/><stop offset="1" stop-color="#43261a"/></linearGradient></defs><rect width="1260" height="610" fill="url(#g)"/><circle cx="880" cy="300" r="90" fill="#fff3d6" opacity="0.85"/>`
  return svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="1260" height="840" viewBox="0 0 1260 840"><rect width="1260" height="840" fill="#f7f1e4"/>${top}<text x="50" y="715" font-size="64" font-weight="700" fill="#3a2a1e" font-family="serif">${esc(song.title)}</text><text x="50" y="765" font-size="28" fill="#6e5644" font-family="sans-serif">${esc(c?.line ?? '')}</text><text x="50" y="810" font-size="24" fill="#6e5644" font-family="sans-serif">${esc(meta)}</text>${code}</svg>`)
}

interface Stored { song: Song; history: Song[]; previewSig?: string; takes: Record<string, number>; leadMemo: Record<string, Record<string, number>> }

/** In-memory stand-in for the server: three candidates built from the example song, edits applied locally. Not musically clever. */
export class MockApi implements Api {
  readonly mock = true
  private songs = new Map<string, Stored>()
  private drafts = new Map<string, Stored>()
  private blobs = new Map<string, string>()
  private groups = 0
  private city = '纽卡斯尔'
  private film = 7
  /** The mock has no model: wordings come from a small pool when `online` is set (?lyrics=online), else they answer 503 like the offline server. */
  constructor(private latency = 0, private online = false) {
    const demo = buildMockSong(null, VARIANT_SETS[0][0], 'grp-demo-0001', 0, 'dusk', '厦门')
    demo.id = 'song-demo-0001'
    demo.candidate!.chosen = true
    demo.assets.push({ id: 'a-card-print-demo01', role: 'card_print', mime: 'image/svg+xml' })
    demo.card!.frontAssetId = 'a-card-print-demo01'
    this.songs.set(demo.id, { song: demo, history: [], takes: {}, leadMemo: {} })
  }

  private async tick() { if (this.latency) await new Promise((r) => setTimeout(r, this.latency)) }
  private get(id: string): Stored {
    const s = this.songs.get(id) ?? this.drafts.get(id)
    if (!s) throw new ApiError('not_found', '没有这首歌', 404)
    return s
  }
  private checkRev(st: Stored, base: number) {
    if (st.song.revision !== base) throw new ApiError('revision_conflict', `Song is at revision ${st.song.revision}`, 409, clone(st.song))
  }
  private commit(st: Stored, mutate: (s: Song) => void, undoable = true): Song {
    const next = clone(st.song)
    mutate(next)
    if (undoable) { st.history.push(st.song); if (st.history.length > 50) st.history.shift() }
    next.revision = st.song.revision + 1
    next.updatedAt = now()
    st.song = next
    return clone(next)
  }

  async health(): Promise<Health> { return { ok: true, online: this.online, version: 'mock', panel: false, lyrics: this.online } }
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
    if (id.startsWith('a-photo')) return photoSvg(id)
    if (id.startsWith('a-card-print')) {
      const st = [...this.songs.values()].find((s) => s.song.assets.some((a) => a.id === id))
      return st ? cardSvg(st.song) : ''
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
      inputs: inputs as SeedCard['inputs'], key, tempo: sad ? 72 : 88, meter: { numerator: 4, denominator: 4 },
      mood: sad ? '安静偏冷' : '平静偏暖', ...(hasHum ? { motif } : {}),
      instruments: { melody: 'piano', guitar: 'nylon', drums: 'jazz-kit' },
      reasons: [
        { field: 'key', text: sad ? '文字偏忧伤，所以用小调' : '没有特别的线索，用明亮的大调' },
        { field: 'tempo', text: sad ? '情绪偏慢，所以速度放慢' : '中速，适合边走边听' },
      ],
      source: 'offline',
    }
  }

  async candidates(seed: SeedCard, req: CandidateRequest = {}): Promise<Song[]> {
    await this.tick()
    if (!seed.inputs.length) throw new ApiError('invalid_request', 'no inputs', 400)
    if (seed.inputs.filter((i) => i.kind === 'photo').length > 9) throw new ApiError('invalid_request', 'too many photos', 400)
    const set = VARIANT_SETS[(req.previousGroupId ? ++this.groups : this.groups) % VARIANT_SETS.length]
    const groupId = `grp-${rid(8)}`
    const out = set.map((v, i) => {
      const song = buildMockSong(seed, v, groupId, i, req.timeOfDay, this.city)
      this.drafts.set(song.id, { song, history: [], takes: {}, leadMemo: {} })
      return clone(song)
    })
    return out
  }

  async choose(id: string): Promise<Song> {
    await this.tick()
    const st = this.drafts.get(id)
    if (!st) throw new ApiError('not_found', '没有这首歌', 404)
    const gid = st.song.candidate!.groupId
    for (const [k, d] of this.drafts) if (d.song.candidate?.groupId === gid) this.drafts.delete(k)
    const song = this.commit(st, (s) => { s.candidate!.chosen = true }, false)
    this.songs.set(id, st)
    return song
  }

  async listSongs(): Promise<SongListItem[]> {
    return [...this.songs.values()].map((s) => ({ id: s.song.id, title: s.song.title, updatedAt: s.song.updatedAt })).reverse()
  }
  async getSong(id: string) { await this.tick(); return clone(this.get(id).song) }

  async edit(id: string, baseRevision: number, ops: EditOp[]): Promise<Song> {
    await this.tick()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    const trial = clone(st.song)
    for (const op of ops) this.applyOp(st, trial, op)
    return this.commit(st, (s) => { for (const op of ops) this.applyOp(st, s, op) })
  }

  async another(id: string, baseRevision: number, section: string, track?: TrackId): Promise<Song> {
    await this.tick()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    if (!st.song.sections.some((s) => s.id === section)) throw new ApiError('cannot_apply', '没有这一段', 422)
    const key = `${section}:${track ?? '*'}`
    const n = (st.takes[key] = (st.takes[key] ?? 0) + 1)
    return this.commit(st, (s) => regenerateUnlocked(s, section, track, n))
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

  private needOnline() { if (!this.online) throw new ApiError('offline_unavailable', 'Needs the network', 503) }

  async lyricsRewrite(id: string, baseRevision: number, req: LyricsRewriteRequest): Promise<Song> {
    await this.tick()
    this.needOnline()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    return this.commit(st, (s) => {
      for (const sec of s.sections) {
        if (req.sections && !req.sections.includes(sec.id)) continue
        const lines = sectionLines(s, sec.id)
        const keep = req.keep?.[sec.id] ?? []
        const text = lines.map((l) => {
          if (keep.includes(l.index)) return l.text
          const pool = MOCK_POOL[l.noteCount]
          return pool ? pool[(l.index + s.revision) % pool.length].text : l.text
        })
        if (lines.length) this.setLyricsText(s, sec.id, text.join('\n'))
      }
    })
  }
  async lyricsAlternatives(id: string, req: LyricsRequest & { section: string; line: number }): Promise<LyricsAlternative[]> {
    await this.tick()
    this.needOnline()
    const line = sectionLines(this.get(id).song, req.section)[req.line]
    if (!line) throw new ApiError('cannot_apply', 'no such line', 422)
    return (MOCK_POOL[line.noteCount] ?? []).filter((p) => p.text !== line.text).slice(0, 3)
  }
  async lyricsThemes(id: string): Promise<LyricsTheme[]> {
    await this.tick()
    const song = this.get(id).song
    const out: LyricsTheme[] = []
    const text = song.seed?.inputs.find((i) => i.kind === 'text')?.text
    if (text) for (const w of text.split(/[，。,.！!？?\s]+/).filter(Boolean).slice(0, 4)) out.push({ text: w.slice(0, 6), source: 'text' })
    if (song.seed?.inputs.some((i) => i.kind === 'photo')) out.push({ text: '暖色', source: 'photo' })
    if (song.seed?.inputs.some((i) => i.kind === 'sound')) out.push({ text: '海浪', source: 'sound' })
    if (!out.length) out.push({ text: '海', source: 'photo' }, { text: '风', source: 'text' }, { text: '傍晚', source: 'text' }, { text: '想家', source: 'text' })
    return out
  }

  async cardPreview(id: string, baseRevision: number): Promise<Song> {
    await this.tick()
    const st = this.get(id)
    this.checkRev(st, baseRevision)
    const song = this.commit(st, (s) => {
      const f = `a-card-print-${rid()}`
      s.assets = s.assets.filter((a) => a.role !== 'card_print')
      s.assets.push({ id: f, role: 'card_print', mime: 'image/svg+xml' })
      s.card = { ...s.card!, frontAssetId: f }
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
    this.film = Math.max(0, this.film - 1)
    return this.commit(st, (s) => { s.card = { ...s.card!, printedAt: now() } }, false)
  }
  async printer(): Promise<PrinterStatus> { return { kind: 'dry_run', connected: true, paper: this.film ? 'ok' : 'out', remaining: this.film } }

  async resolveShare(shareId: string): Promise<string> {
    const st = [...this.songs.values()].find((s) => s.song.card?.share?.shareId === shareId)
    if (!st) throw new ApiError('not_found', '这张卡片的歌不在这台设备上', 404)
    return st.song.id
  }
  async sharePage(shareId: string): Promise<{ page: SharePage; song: Song }> {
    await this.tick()
    const st = [...this.songs.values()].find((s) => s.song.card?.share?.shareId === shareId)
    if (!st) throw new ApiError('not_found', 'no such share', 404)
    const song = clone(st.song)
    const c = song.card
    const lyrics = song.sections.map((s) => ({ section: s.label, lines: sectionLines(song, s.id).map((l) => l.text) })).filter((g) => g.lines.length)
    const page: SharePage = {
      title: song.title, ...(song.candidate ? { subtitle: song.candidate.name } : {}), ...(c?.line ? { line: c.line } : {}),
      ...(c?.showCity && c.city ? { city: c.city } : {}), date: (c?.capturedAt ?? song.createdAt).slice(0, 10),
      ...(c?.message ? { message: c.message } : {}),
      photos: c?.showPhoto ? (c.photoAssetIds ?? []).map((a) => this.assetUrl(a)) : [],
      ...(c?.frontAssetId ? { card: this.assetUrl(c.frontAssetId) } : {}), lyrics,
    }
    delete song.seed; delete song.provenance
    return { page, song }
  }
  async getLocation() { return { city: this.city, source: 'manual' as const } }
  async putLocation(city: string) { this.city = city }
  async studyLog() { /* dropped in mock mode */ }

  // ---- edits --------------------------------------------------------------------------------

  private setLyricsText(s: Song, sectionId: string, text: string) {
    const sec = s.sections.find((x) => x.id === sectionId)
    if (!sec) throw new ApiError('cannot_apply', '没有这一段', 422)
    const r = sectionRange(s, sec)
    const lines = sectionLines(s, sectionId)
    const notes = s.tracks.vocal.notes.filter((n) => n.start >= r.from && n.start < r.to).sort((a, b) => a.start - b.start)
    if (text.includes('\n')) {
      const typed = text.split('\n').map((t) => syllables(t))
      const bad = Array.from({ length: Math.max(typed.length, lines.length) }, (_, i) => ({ index: i, noteCount: lines[i]?.noteCount ?? 0, syllableCount: typed[i]?.length ?? 0 })).filter((l) => l.noteCount !== l.syllableCount)
      if (bad.length) throw new ApiError('cannot_apply', 'Lines do not fit', 422, undefined, { lines: bad })
      let k = 0
      typed.forEach((chars) => chars.forEach((ch) => { notes[k++].lyric = ch }))
      return
    }
    const chars = syllables(text)
    if (chars.length !== notes.length) throw new ApiError('cannot_apply', 'Does not fit', 422, undefined, { noteCount: notes.length, syllableCount: chars.length })
    notes.forEach((n, i) => { n.lyric = chars[i] })
  }

  private applyOp(st: Stored, s: Song, op: EditOp): void {
    const secIds = new Set(s.sections.map((x) => x.id))
    const needSection = (id: string) => { if (!secIds.has(id)) throw new ApiError('cannot_apply', '没有这一段', 422) }
    switch (op.op) {
      case 'setControl': s.controls[op.control] = clamp(op.value, 0, 1); return
      case 'setTempo': s.tempo = clamp(op.tempo, 40, 220); return
      case 'setTrackVolume': s.tracks[op.track].volume = clamp(op.volume, 0, 1); return
      case 'setTrackMute': s.tracks[op.track].muted = op.muted; return
      case 'setInstrument': s.tracks[op.track].instrument = op.instrument; return
      case 'replaceNotes': {
        if (op.track === 'ambience') throw new ApiError('cannot_apply', '环境声不能改音符', 422)
        const tr = s.tracks[op.track]
        const kept = (tr.notes as Note[]).filter((n) => n.start < op.from || n.start >= op.to)
        ;(tr as { notes: Note[] }).notes = [...kept, ...op.notes.map((n) => ({ velocity: 90, ...n }))].sort((a, b) => a.start - b.start || a.pitch - b.pitch)
        for (const sec of s.sections) {
          const r = sectionRange(s, sec)
          if (op.from < r.to && op.to > r.from && !hasExactLock(s, op.track, sec.id)) s.locks.push({ track: op.track, section: sec.id })
        }
        return
      }
      case 'setLyrics': this.setLyricsText(s, op.section, op.text); return
      case 'setRhythm': s.tracks.guitar.rhythm = { family: op.family, presetId: op.presetId }; return
      case 'lock':
      case 'unlock': {
        if (!op.track && !op.section) throw new ApiError('invalid_request', '需要音轨或段落', 400)
        if (op.section) needSection(op.section)
        if (op.op === 'lock') { if (!hasExactLock(s, op.track, op.section)) s.locks.push({ ...(op.track ? { track: op.track } : {}), ...(op.section ? { section: op.section } : {}) }) }
        else s.locks = s.locks.filter((l) => !(l.track === op.track && l.section === op.section))
        return
      }
      case 'setSections': {
        let bar = 0
        for (const sec of op.sections) { if (sec.startBar !== bar) throw new ApiError('cannot_apply', '段落必须连续', 422); bar = sec.endBar }
        if (bar !== s.bars) throw new ApiError('cannot_apply', '段落必须覆盖全部小节', 422)
        s.sections = op.sections as Song['sections']
        return
      }
      case 'setTitle': s.title = op.title.slice(0, 80); return
      case 'setCard': {
        const { op: _op, ...patch } = op
        void _op
        const card = { ...(s.card ?? { style: 'xieyi', showPhoto: false, showCity: false }), ...patch } as NonNullable<Song['card']>
        if (card.style === 'text') delete card.coverAssetId
        else if (!card.coverAssetId && card.photoAssetIds?.length) card.coverAssetId = card.photoAssetIds[0]
        if (card.coverAssetId && !(card.photoAssetIds as string[] | undefined)?.includes(card.coverAssetId)) throw new ApiError('cannot_apply', 'cover must be one of the photos', 422)
        delete card.frontAssetId
        s.card = card
        return
      }
      case 'setRegion': {
        needSection(op.section)
        const r = s.tracks[op.track].regions.find((x) => x.section === op.section)!
        if (op.play !== undefined) r.play = op.play
        if (op.complexity !== undefined) r.complexity = clamp(op.complexity, 0, 1)
        if (op.intensity !== undefined) r.intensity = clamp(op.intensity, 0, 1)
        if (op.style !== undefined) r.style = op.style
        replaceTrackSection(s, op.track, op.section)
        if (!hasExactLock(s, op.track, op.section)) s.locks.push({ track: op.track, section: op.section })
        return
      }
      case 'copyRegion': {
        needSection(op.section)
        const regions = s.tracks[op.track].regions
        const from = regions.find((x) => x.section === op.section)!
        for (const r of regions) { r.complexity = from.complexity; r.intensity = from.intensity; r.style = from.style; replaceTrackSection(s, op.track, r.section) }
        if (!hasExactLock(s, op.track, undefined)) s.locks.push({ track: op.track })
        return
      }
      case 'setLead': {
        needSection(op.section)
        const sec = s.sections.find((x) => x.id === op.section)!
        const memo = st.leadMemo[op.section]
        const tracks: TrackId[] = ['vocal', 'melody', 'guitar', 'bass', 'drums', 'ambience']
        const adjust = (t: TrackId, d: number) => {
          const r = s.tracks[t].regions.find((x) => x.section === op.section)!
          if (isLocked(s, t, op.section)) return
          r.intensity = clamp(r.intensity + d, 0, 1)
        }
        if (memo) { for (const t of tracks) { const r = s.tracks[t].regions.find((x) => x.section === op.section)!; if (t in memo && !isLocked(s, t, op.section)) r.intensity = memo[t] } delete st.leadMemo[op.section] }
        if (op.track) {
          st.leadMemo[op.section] = Object.fromEntries(tracks.map((t) => [t, s.tracks[t].regions.find((x) => x.section === op.section)!.intensity]))
          for (const t of tracks) adjust(t, t === op.track ? 0.15 : -0.1)
          if (op.track === 'vocal' && !isLocked(s, 'melody', op.section)) s.tracks.melody.regions.find((x) => x.section === op.section)!.style = 'answer'
          sec.lead = op.track
        } else delete sec.lead
        for (const t of tracks) if (t !== 'ambience') if (!isLocked(s, t, op.section)) replaceTrackSection(s, t, op.section)
        return
      }
      case 'shiftRegister': {
        needSection(op.section)
        if (op.track === 'drums' || op.track === 'ambience') throw new ApiError('cannot_apply', 'not allowed on this track', 422)
        const sec = s.sections.find((x) => x.id === op.section)!
        const { from, to } = sectionRange(s, sec)
        const dir = op.direction === 'up' ? 1 : -1
        const lo = op.track === 'bass' ? 28 : 40, hi = op.track === 'bass' ? 55 : 100
        const notes = (s.tracks[op.track].notes as Note[]).filter((n) => n.start >= from && n.start < to)
        const next = notes.map((n) => op.track === 'bass' ? n.pitch + dir * 12 : op.track === 'guitar' ? n.pitch + dir * 5 : snapToKey(n.pitch + dir * 2, s.key))
        if (next.some((p) => p < lo || p > hi)) throw new ApiError('cannot_apply', 'out of range', 422)
        notes.forEach((n, i) => { n.pitch = next[i] })
        if (!hasExactLock(s, op.track, op.section)) s.locks.push({ track: op.track, section: op.section })
        return
      }
      case 'revertMelody': {
        needSection(op.section)
        if (!s.seed?.motif?.length) throw new ApiError('cannot_apply', 'no motif', 422)
        for (const t of ['vocal', 'melody'] as const) replaceTrackSection(s, t, op.section)
        return
      }
      case 'setMaster': {
        if (op.volume !== undefined) s.master.volume = clamp(op.volume, 0, 1)
        if (op.space) s.master.space = op.space
        return
      }
    }
  }
}

const cardSig = (s: Song) => JSON.stringify({ ...s.card, frontAssetId: 0, printedAt: 0, share: 0, title: s.title })
