import { ApiError, type Api, type CardPatch, type EditOp, type KnobControl, type LeadTrack, type NoteInput } from '../api'
import { loopRangeFor } from '../audio/schedule'
import { MicRecorder } from '../lib/recorder'
import { barTicks, hasExactLock, isLocked, previewStartTick, regionOf, sectionAtBar, secondsToTicks, trackName } from '../lib/song'
import { sectionLines, syllables } from '../lib/lyrics'
import { PanelInterpreter, type Intent } from '../panel/interpreter'
import { computeKeyLights, computeRing, type KeyLightMsg } from '../panel/lights'
import type { CardStyle, SeedCard, SeedInput, Song, SpaceId, TimeOfDay, TrackId } from '../types'
import { initialLyrics, MAX_PHOTOS, Store, type CapturedInput, type LyricsUi, type View } from './store'

/** What the controller needs from the playback engine (the Tone.js engine, or a fake in tests). */
export interface AudioLike {
  load(song: Song): Promise<void> | void
  play(): Promise<void> | void
  stop(): void
  seek(tick: number): void
  setLoop(range: { from: number; to: number } | null): void
  setTrackGain(track: TrackId, volume: number, muted: boolean): void
  setSolo?(track: TrackId | null): void
  setMaster?(volume: number, space: SpaceId): void
}

/** What the controller needs from the panel socket. */
export interface PanelLike {
  setRing(pixels: (string | null)[], brightness?: number): boolean
  setKeyLight(id: string, mode: KeyLightMsg['mode'], color?: string): boolean
}

export const PREVIEW_SECONDS = 15
const CARD_STYLE_ORDER: CardStyle[] = ['original', 'xieyi', 'comic', 'ink', 'text']
let toastId = 0

/**
 * All app behaviour that is not drawing: talking to the API, keeping the song, playing, recording,
 * and acting on panel intents. Views call these methods; none of them builds or patches a Song itself,
 * every change goes through the API and the response replaces the song (docs/api.md, "Songs change only through the server").
 */
export class Controller {
  private chain: Promise<unknown> = Promise.resolve()
  private recorder = new MicRecorder()
  private logBuf: { at: string; type: string; detail?: unknown }[] = []
  private logTimer: ReturnType<typeof setInterval> | null = null
  private lastLights = new Map<string, string>()
  private lastRing = ''
  private previewTimer: ReturnType<typeof setTimeout> | null = null
  private snippetEnd: number | null = null
  interpreter: PanelInterpreter
  panel: PanelLike | null = null
  /** Registered by the capture view while the rear camera is open. */
  photoSource: (() => Promise<Blob | null>) | null = null

  constructor(public api: Api, public store: Store, public audio: AudioLike | null) {
    const st = store
    this.interpreter = new PanelInterpreter(
      {
        get bars() { return st.state.song?.bars ?? 1 },
        get sections() { return st.state.song?.sections ?? [] },
        get selectedTrack() { return st.state.selectedTrack },
        screen: () => st.state.view,
        volume: (t) => st.state.song?.tracks[t].volume ?? 0.8,
        controlValue: (c) => st.state.song?.controls[c] ?? 0.5,
        tempo: () => st.state.song?.tempo ?? 84,
        focus: () => st.state.focus,
        sectionIndex: () => Math.max(0, st.state.song?.sections.findIndex((s) => s.id === st.state.editSection) ?? 0),
        cardStyleIndex: () => Math.max(0, CARD_STYLE_ORDER.indexOf((st.state.song?.card?.style ?? 'xieyi') as CardStyle)),
        regionParam: (p) => {
          const s = st.state.song, t = st.state.selectedTrack, sec = st.state.editSection
          if (!s || !t || !sec) return null
          return regionOf(s, t, sec)?.[p] ?? null
        },
      },
      (i) => void this.onIntent(i),
    )
    this.store.subscribe(() => this.syncLights())
  }

  // ---- lifecycle -----------------------------------------------------------------------------

  async init() {
    const { store, api } = this
    store.set({ mock: api.mock })
    this.logTimer = setInterval(() => void this.flushLog(), 5000)
    await this.refreshHealth()
    try { store.set({ catalog: await api.catalog() }) } catch { /* the app still works with the built-in catalogue */ }
    try { const loc = await api.getLocation(); store.set({ city: loc.city ?? '' }) } catch { /* optional */ }
    await this.refreshSongs()
  }

  dispose() {
    if (this.logTimer) clearInterval(this.logTimer)
    if (this.previewTimer) clearTimeout(this.previewTimer)
    this.interpreter.dispose()
  }

  async refreshHealth() {
    try {
      const h = await this.api.health()
      this.store.set({ serverOnline: true, netOnline: h.online })
    } catch {
      this.store.set({ serverOnline: false })
    }
  }

  async refreshSongs() {
    try {
      const list = await this.api.listSongs()
      this.store.set({ recentSongs: list.slice(0, 8).map((s) => ({ id: s.id, title: s.title })) })
    } catch { /* offline list stays empty */ }
  }

  async refreshPrinter() {
    try { this.store.set({ printer: await this.api.printer() }) } catch { this.store.set({ printer: null }) }
  }

  // ---- messages and log --------------------------------------------------------------------

  toast(text: string, kind: 'info' | 'error' = 'info') {
    const id = ++toastId
    this.store.set({ toast: { text, kind, id } })
    setTimeout(() => { if (this.store.state.toast?.id === id) this.store.set({ toast: null }) }, 4000)
  }

  log(type: string, detail?: unknown) {
    this.logBuf.push({ at: new Date().toISOString(), type, detail })
    if (this.logBuf.length > 200) this.logBuf.shift()
  }

  private async flushLog() {
    if (!this.logBuf.length) return
    const events = this.logBuf.splice(0)
    try { await this.api.studyLog(events) } catch { /* the study log is best effort */ }
  }

  private fail(e: unknown) {
    if (e instanceof ApiError) {
      switch (e.code) {
        case 'revision_conflict':
          if (e.song) this.setSong(e.song)
          this.toast('歌曲刚刚有了新的版本，已更新，请再试一次', 'error'); return
        case 'offline_unavailable': this.toast('这一步需要联网，现在没有网络', 'error'); return
        case 'network': this.toast('连不上服务器', 'error'); this.store.set({ serverOnline: false }); return
        case 'timeout': this.toast('服务器没有及时响应', 'error'); return
        // Server messages are English and meant for logs, so the toast stays in Chinese.
        case 'cannot_apply': {
          console.warn(e.message)
          const detail = (e as ApiError & { detail?: Record<string, unknown> }).detail ?? {}
          if (detail.printer) { this.toast('打印机出了问题：没连上或没有相纸，请检查打印机', 'error'); return }
          if (/range/i.test(e.message)) { this.toast('已经到这件乐器能到的最高或最低了', 'error'); return }
          if (detail.reason === 'no_motif') { this.toast('这首歌没有哼唱，没有可以用回的旋律', 'error'); return }
          this.toast('这一步现在做不了', 'error'); return
        }
        case 'not_implemented': console.warn(e.message); this.toast('这个功能还没做好', 'error'); return
        default: console.warn(e.code, e.message); this.toast('出错了', 'error'); return
      }
    }
    this.toast('出错了', 'error')
  }

  // ---- navigation ---------------------------------------------------------------------------

  canGo(view: View): boolean {
    const s = this.store.state
    if (view === 'capture') return true
    if (view === 'pick') return !!s.candidates
    return !!s.song
  }

  setView(view: View) {
    const s = this.store.state
    if (!this.canGo(view)) { this.toast(view === 'pick' ? '先把采集的东西做成歌' : '先选一首歌', 'info'); return }
    if (s.view === 'pick' && view !== 'pick') this.stopPreview()
    this.store.set({ view, scanning: false, showSongs: false })
    if (view === 'shape' || view === 'detail') this.ensureSelection()
    else { this.store.set({ looping: false }); this.applyLoop() }
    if (view === 'card') { void this.refreshPrinter(); this.enterCard() }
    if (view === 'lyrics') void this.loadThemes()
    this.log('view', view)
  }

  private ensureSelection() {
    const { song, editSection } = this.store.state
    if (song && (!editSection || !song.sections.some((x) => x.id === editSection))) this.store.set({ editSection: this.sectionUnderPosition()?.id ?? song.sections[0].id })
  }

  private applyLoop() {
    const s = this.store.state
    this.audio?.setLoop(s.looping && s.song && s.editSection ? loopRangeFor(s.song, s.editSection) : null)
  }

  /** Selects a section on the shape or track screen and plays only that section. */
  selectSection(sectionId: string, loop = true) {
    const song = this.store.state.song
    if (!song) return
    this.store.set({ editSection: sectionId, looping: loop })
    this.applyLoop()
    const sec = song.sections.find((s) => s.id === sectionId)
    if (sec && loop) this.seekToBar(sec.startBar)
  }
  listenAll() { this.store.set({ looping: false }); this.applyLoop() }

  selectRegion(track: TrackId, sectionId: string) {
    this.store.set({ selectedTrack: track })
    this.selectSection(sectionId, true)
    this.log('region.select', { track, sectionId })
  }

  selectTrack(track: TrackId | null) { this.store.set({ selectedTrack: track }); this.log('track.select', track) }

  sectionUnderPosition() {
    const s = this.store.state
    if (!s.song) return undefined
    return sectionAtBar(s.song.sections, Math.min(s.positionTick / barTicks(s.song.meter), s.song.bars - 1e-6))
  }

  // ---- song state ---------------------------------------------------------------------------

  /** Replaces the local song with the server's. The only place the song changes. */
  setSong(song: Song) {
    const prev = this.store.state.song
    const sameSong = prev?.id === song.id
    this.store.set({ song })
    void this.audio?.load(song)
    if (!sameSong) { this.audio?.seek(0); this.store.set({ solo: null, takes: {}, previewSig: null, lyrics: initialLyrics(), selectedTrack: null }); this.audio?.setSolo?.(null) }
    this.applyLoop()
  }

  async openSong(id: string, thenPlay = false) {
    try {
      this.store.set({ busy: '正在打开' })
      const song = await this.api.getSong(id)
      this.stopPreview()
      this.setSong(song)
      this.store.set({ view: 'shape', positionTick: 0, selectedTrack: null, editSection: song.sections[0].id, looping: false, showSongs: false })
      this.applyLoop()
      if (thenPlay) await this.play()
      this.log('song.open', id)
    } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
  }

  /** Runs one call that changes the song, strictly after the previous one, with the newest revision. */
  private mutate(label: string, call: (song: Song) => Promise<Song>, busy = false): Promise<Song | null> {
    const run = async (): Promise<Song | null> => {
      const song = this.store.state.song
      if (!song) return null
      if (busy) this.store.set({ busy: label })
      try {
        const next = await call(song)
        this.setSong(next)
        this.log(label, { revision: next.revision })
        return next
      } catch (e) {
        this.fail(e)
        return null
      } finally {
        if (busy) this.store.set({ busy: null })
      }
    }
    const p = this.chain.then(run, run)
    this.chain = p
    return p
  }

  edit(ops: EditOp[], busy = false) {
    return this.mutate(ops.map((o) => o.op).join('+'), (s) => this.api.edit(s.id, s.revision, ops), busy)
  }

  // ---- shape and track edits ------------------------------------------------------------------

  setVolume(track: TrackId, value: number) {
    const song = this.store.state.song
    if (song) this.audio?.setTrackGain(track, value, song.tracks[track].muted)
    return this.edit([{ op: 'setTrackVolume', track, volume: value }])
  }
  previewVolume(track: TrackId, value: number) {
    const song = this.store.state.song
    if (song) this.audio?.setTrackGain(track, value, song.tracks[track].muted)
  }
  toggleMute(track: TrackId) {
    const song = this.store.state.song
    if (!song) return null
    const muted = !song.tracks[track].muted
    this.audio?.setTrackGain(track, song.tracks[track].volume, muted)
    return this.edit([{ op: 'setTrackMute', track, muted }])
  }
  /** Solo is only in the app: it silences the other tracks while listening and is never saved. */
  toggleSolo(track: TrackId) {
    const solo = this.store.state.solo === track ? null : track
    this.store.set({ solo })
    this.audio?.setSolo?.(solo)
  }
  setControl(control: KnobControl, value: number) { return this.edit([{ op: 'setControl', control, value }], true) }
  setTempo(tempo: number) { return this.edit([{ op: 'setTempo', tempo }]) }
  setInstrument(track: TrackId, instrument: string) { return this.edit([{ op: 'setInstrument', track, instrument }]) }
  setTitle(title: string) { return this.edit([{ op: 'setTitle', title }]) }
  setCard(patch: CardPatch) {
    const p = this.edit([{ op: 'setCard', ...patch }])
    void p.then(() => this.schedulePreview())
    return p
  }
  replaceNotes(track: TrackId, from: number, to: number, notes: NoteInput[]) { return this.edit([{ op: 'replaceNotes', track, from, to, notes }]) }

  setRegion(track: TrackId, section: string, patch: { play?: boolean; complexity?: number; intensity?: number; style?: string }) {
    return this.edit([{ op: 'setRegion', track, section, ...patch }])
  }
  copyRegion(track: TrackId, section: string) { return this.edit([{ op: 'copyRegion', track, section }], true) }
  setLead(section: string, track: LeadTrack | null) { return this.edit([{ op: 'setLead', section, track }], true) }
  shiftRegister(track: TrackId, section: string, direction: 'up' | 'down') { return this.edit([{ op: 'shiftRegister', track, section, direction }]) }
  revertMelody(section: string) { return this.edit([{ op: 'revertMelody', section }], true) }
  setMaster(patch: { volume?: number; space?: SpaceId }) {
    const song = this.store.state.song
    if (song) this.audio?.setMaster?.(patch.volume ?? song.master.volume, patch.space ?? song.master.space)
    return this.edit([{ op: 'setMaster', ...patch }])
  }
  previewMaster(volume: number) {
    const song = this.store.state.song
    if (song) this.audio?.setMaster?.(volume, song.master.space)
  }

  toggleLock(track?: TrackId, section?: string) {
    const song = this.store.state.song
    if (!song) return null
    const op = hasExactLock(song, track, section) ? 'unlock' : 'lock'
    return this.edit([{ op, ...(track ? { track } : {}), ...(section ? { section } : {}) } as EditOp])
  }

  async another(section?: string, track?: TrackId) {
    const sec = section ?? this.store.state.editSection ?? this.sectionUnderPosition()?.id
    if (!sec) return
    const tr = track ?? this.store.state.selectedTrack ?? undefined
    const song = this.store.state.song
    if (song && tr && isLocked(song, tr, sec)) this.toast(`${trackName(tr)}在这一段被保留了`, 'info')
    const res = await this.mutate('another', (s) => this.api.another(s.id, s.revision, sec, tr), true)
    if (res) this.store.set({ takes: { ...this.store.state.takes, [sec]: (this.store.state.takes[sec] ?? 1) + 1 } })
  }

  async undo() { await this.mutate('undo', (s) => this.api.undo(s.id, s.revision), true) }

  // ---- capture ----------------------------------------------------------------------------------

  addInput(i: CapturedInput) { this.store.set({ inputs: [...this.store.state.inputs, i] }) }
  removeInput(id: string) {
    const s = this.store.state
    this.store.set({ inputs: s.inputs.filter((i) => i.id !== id), photoSel: s.photoSel === id ? null : s.photoSel })
  }
  removeAllPhotos() { this.store.set({ inputs: this.store.state.inputs.filter((i) => i.kind !== 'photo'), photoSel: null }) }
  photos() { return this.store.state.inputs.filter((i) => i.kind === 'photo') }

  /** Adds a photo to the strip; the tenth is refused. */
  addPhoto(blob: Blob): boolean {
    if (this.photos().length >= MAX_PHOTOS) { this.toast(`最多 ${MAX_PHOTOS} 张照片，先去掉一张吧`, 'info'); return false }
    const id = `photo-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    this.addInput({ id, kind: 'photo', label: '照片', blob, url: URL.createObjectURL(blob) })
    this.store.set({ photoSel: id })
    this.log('photo.add', this.photos().length)
    return true
  }
  /** 重拍: drops the selected photo (the last one by default) so the next shot replaces it. */
  retakePhoto() {
    const s = this.store.state
    const target = s.photoSel ?? this.photos().slice(-1)[0]?.id
    if (target) this.removeInput(target)
  }
  selectPhoto(id: string) { this.store.set({ photoSel: id }) }

  /** The one sentence of text: set, replaced or cleared. */
  setText(text: string) {
    const rest = this.store.state.inputs.filter((i) => i.kind !== 'text')
    const t = text.trim()
    this.store.set({ inputs: t ? [...rest, { id: 'text', kind: 'text', label: t, text }] : rest })
  }
  textValue() { return this.store.state.inputs.find((i) => i.kind === 'text')?.text ?? '' }

  setCaptureMode(captureMode: 'photo' | 'hum' | 'sound' | 'text') { this.store.set({ captureMode }) }

  async startRecording(kind: 'hum' | 'sound') {
    if (this.store.state.recording) return
    try {
      await this.recorder.start()
      this.store.set({ recording: kind })
      this.log('record.start', kind)
    } catch {
      this.toast('不能使用麦克风，请检查权限', 'error')
    }
  }

  async stopRecording() {
    const kind = this.store.state.recording
    if (!kind) return
    this.store.set({ recording: null })
    const blob = await this.recorder.stop()
    if (!blob) { this.toast('录得太短了，请按住久一点', 'info'); return }
    this.log('record.stop', kind)
    await this.handleRecording(kind, blob)
  }

  /** A finished recording: a new input on the capture screen, or a re-hum of the selected section on the shape and track screens. */
  async handleRecording(kind: 'hum' | 'sound', blob: Blob) {
    const s = this.store.state
    if (kind === 'hum' && s.song && (s.view === 'shape' || s.view === 'detail')) {
      try {
        this.store.set({ busy: '正在上传' })
        const asset = await this.api.uploadAsset(blob, 'hum')
        const sec = s.editSection ?? this.interpreter.sectionUnderPlatter()?.id ?? s.song.sections[0].id
        await this.mutate('rehum', (song) => this.api.rehum(song.id, song.revision, sec, asset.id), true)
      } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
      return
    }
    const n = s.inputs.filter((i) => i.kind === kind).length + 1
    this.addInput({ id: `${kind}-${Date.now()}`, kind, label: kind === 'hum' ? '哼唱' : '环境声', blob, url: URL.createObjectURL(blob) })
    void n
  }

  /** Uploads what has not been uploaded yet; returns the seed inputs. */
  private async uploadInputs(): Promise<SeedInput[]> {
    const out: SeedInput[] = []
    for (const i of this.store.state.inputs) {
      if (i.kind === 'text') { out.push({ kind: 'text', text: i.text }); continue }
      if (!i.assetId && i.blob) {
        const asset = await this.api.uploadAsset(i.blob, i.kind === 'photo' ? 'photo' : i.kind === 'hum' ? 'hum' : 'ambience')
        i.assetId = asset.id
        this.store.set({ inputs: this.store.state.inputs.map((x) => (x.id === i.id ? { ...x, assetId: asset.id } : x)) })
      }
      out.push({ kind: i.kind, assetId: i.assetId })
    }
    return out
  }

  /** 做成歌: upload, understand (seed), then three candidates. */
  async makeSong() {
    const { inputs } = this.store.state
    if (!inputs.length) { this.toast('先拍一张、哼一段或写一句话', 'info'); return }
    try {
      this.store.set({ busy: '正在整理你收集的东西' })
      const seedInputs = await this.uploadInputs()
      this.store.set({ busy: '正在理解你收集的东西' })
      const seed: SeedCard = await this.api.createSeed(seedInputs)
      this.store.set({ busy: '正在编三首歌', seed })
      const tod = this.store.state.timeOfDay
      const candidates = await this.api.candidates(seed, { bars: 16, timeOfDay: tod })
      this.showCandidates(candidates)
      this.log('candidates', { source: seed.source })
    } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
  }

  private showCandidates(candidates: Song[]) {
    this.stopPreview()
    this.store.set({ candidates, focus: 0, view: 'pick' })
  }

  /** 白天 / 黄昏 / 夜晚, or 都不像，再来三首 (with the previous group). */
  async moreCandidates(opts: { timeOfDay?: TimeOfDay; again?: boolean } = {}) {
    const s = this.store.state
    if (!s.seed) return
    const tod = opts.timeOfDay ?? s.timeOfDay
    try {
      this.store.set({ busy: '正在编三首歌', timeOfDay: tod })
      const groupId = s.candidates?.[0]?.candidate?.groupId
      const candidates = await this.api.candidates(s.seed, { bars: 16, timeOfDay: tod, ...(opts.again && groupId ? { previousGroupId: groupId } : {}) })
      this.showCandidates(candidates)
    } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
  }

  focusCandidate(index: number) { this.store.set({ focus: Math.max(0, Math.min(2, index)) }) }

  /** 15 seconds from the chorus (the vocal-led section, else the middle). Toggles if that card is already playing. */
  async previewCandidate(index: number) {
    const s = this.store.state
    const song = s.candidates?.[index]
    if (!song || !this.audio) return
    if (s.preview?.index === index && s.playing) { this.stopPreview(); return }
    this.stopPreview()
    this.audio.setLoop(null)
    await this.audio.load(song)
    const from = previewStartTick(song)
    const to = from + secondsToTicks(PREVIEW_SECONDS, song.tempo)
    this.audio.seek(from)
    this.store.set({ focus: index, preview: { index, fromTick: from, toTick: to } })
    await this.audio.play()
    this.store.set({ playing: true })
    this.log('candidate.preview', index)
  }

  stopPreview() {
    if (!this.store.state.preview) return
    this.audio?.stop()
    this.store.set({ preview: null, playing: false })
  }

  async chooseCandidate(index: number) {
    const cand = this.store.state.candidates?.[index]
    if (!cand) return
    this.stopPreview()
    try {
      this.store.set({ busy: '正在保存这首歌' })
      const song = await this.api.choose(cand.id)
      this.store.set({ candidates: null, seed: null, inputs: [], photoSel: null })
      this.setSong(song)
      this.store.set({ view: 'shape', positionTick: 0, editSection: song.sections[0].id, looping: false })
      this.applyLoop()
      void this.refreshSongs()
      this.log('candidate.choose', index)
    } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
  }

  // ---- lyrics -----------------------------------------------------------------------------------

  private setLyricsUi(patch: Partial<LyricsUi>) { this.store.set({ lyrics: { ...this.store.state.lyrics, ...patch } }) }

  async loadThemes() {
    const song = this.store.state.song
    if (!song) return
    try {
      const themes = await this.api.lyricsThemes(song.id)
      const cur = this.store.state.lyrics
      this.setLyricsUi({ themes, themeSel: cur.themeSel.length ? cur.themeSel.filter((t) => themes.some((x) => x.text === t)) : themes.map((t) => t.text) })
    } catch (e) {
      if (!(e instanceof ApiError && e.code === 'offline_unavailable')) this.log('themes.error', String(e))
    }
  }
  toggleTheme(text: string) {
    const l = this.store.state.lyrics
    this.setLyricsUi({ themeSel: l.themeSel.includes(text) ? l.themeSel.filter((t) => t !== text) : [...l.themeSel, text] })
  }
  setTone(tone: LyricsUi['tone']) { this.setLyricsUi({ tone }) }
  setRhyme(rhyme: boolean) { this.setLyricsUi({ rhyme }) }
  toggleKeep(section: string, index: number) {
    const keeps = { ...this.store.state.lyrics.keeps }
    const cur = keeps[section] ?? []
    keeps[section] = cur.includes(index) ? cur.filter((i) => i !== index) : [...cur, index].sort((a, b) => a - b)
    this.setLyricsUi({ keeps })
  }

  /** Sets the lyrics of one section, line by line. Returns the lines the server said do not fit. */
  async setSectionLyrics(section: string, lines: string[]): Promise<{ ok: boolean; misfit: number[] }> {
    let misfit: number[] = []
    const res = await this.mutate('setLyrics', async (s) => {
      try { return await this.api.edit(s.id, s.revision, [{ op: 'setLyrics', section, text: lines.join('\n') }]) }
      catch (e) {
        if (e instanceof ApiError && e.code === 'cannot_apply' && e.detail) {
          const d = e.detail as { lines?: { index: number }[] }
          misfit = d.lines?.map((l) => l.index) ?? []
          throw new ApiError('lyrics_count', 'lines do not fit', 422)
        }
        throw e
      }
    })
    const key = (i: number) => `${section}:${i}`
    const rest = this.store.state.lyrics.misfit.filter((k) => !k.startsWith(`${section}:`))
    this.setLyricsUi({ misfit: [...rest, ...misfit.map(key)] })
    if (!res && misfit.length) this.toast('有的句子字数和音数对不上', 'error')
    return { ok: !!res, misfit }
  }

  selectLine(section: string, index: number) {
    this.setLyricsUi({ selected: { section, index }, alternatives: null })
    void this.fetchAlternatives(section, index)
    this.playLine(section, index)
  }

  async fetchAlternatives(section: string, index: number) {
    const song = this.store.state.song
    if (!song) return
    const l = this.store.state.lyrics
    this.setLyricsUi({ loading: true })
    try {
      const alternatives = await this.api.lyricsAlternatives(song.id, { section, line: index, themes: l.themeSel, tone: l.tone, rhyme: l.rhyme })
      const cur = this.store.state.lyrics.selected
      if (cur && cur.section === section && cur.index === index) this.setLyricsUi({ alternatives, offline: false, loading: false })
    } catch (e) {
      const off = e instanceof ApiError && (e.code === 'offline_unavailable' || e.code === 'timeout' || e.code === 'network')
      this.setLyricsUi({ alternatives: null, offline: off ? true : this.store.state.lyrics.offline, loading: false })
      if (!off) this.fail(e)
    }
  }

  async applyAlternative(section: string, index: number, text: string) {
    const song = this.store.state.song
    if (!song) return
    const lines = sectionLines(song, section).map((l) => l.text)
    lines[index] = text
    const r = await this.setSectionLyrics(section, lines)
    if (r.ok) { this.playLine(section, index); void this.fetchAlternatives(section, index) }
  }

  /** "按这些重写没保留的句子", or one section only (整段重写, which ignores that section's keeps). */
  async rewriteLyrics(sections?: string[]) {
    const l = this.store.state.lyrics
    const keep = { ...l.keeps }
    if (sections) for (const s of sections) delete keep[s]
    const res = await this.mutate('lyrics.rewrite', async (s) => {
      try {
        return await this.api.lyricsRewrite(s.id, s.revision, { ...(sections ? { sections } : {}), keep, themes: l.themeSel, tone: l.tone, rhyme: l.rhyme })
      } catch (e) {
        if (e instanceof ApiError && (e.code === 'offline_unavailable' || e.code === 'timeout' || e.code === 'network')) this.setLyricsUi({ offline: true })
        throw e
      }
    }, true)
    if (res) this.setLyricsUi({ offline: false, misfit: [] })
  }

  /** Plays one lyric line (and a little after it) so it can be heard as sung. */
  async playLine(section: string, index: number) {
    const song = this.store.state.song
    const line = song ? sectionLines(song, section)[index] : undefined
    if (!song || !line || !this.audio) return
    this.audio.setLoop(null)
    this.audio.seek(line.fromTick)
    this.snippetEnd = line.toTick + 240
    await this.audio.play()
    this.store.set({ playing: true })
  }

  /** Characters typed for a line, for counting: the app never changes the song itself. */
  static countChars(text: string) { return syllables(text).length }

  // ---- playback -------------------------------------------------------------------------------

  async play() {
    if (!this.audio || !this.store.state.song) return
    this.snippetEnd = null
    this.applyLoop()
    await this.audio.play()
    this.store.set({ playing: true })
    this.log('play')
  }
  pause() { this.audio?.stop(); this.store.set({ playing: false }); this.log('pause') }
  async togglePlay() { if (this.store.state.playing) this.pause(); else await this.play() }

  /** Called by the engine on every animation frame while playing. */
  onPosition(tick: number) {
    const s = this.store.state
    this.store.set({ positionTick: tick })
    if (s.song) this.interpreter.setPosition(tick / barTicks(s.song.meter))
    if (s.preview && tick >= s.preview.toTick) this.stopPreview()
    if (this.snippetEnd !== null && tick >= this.snippetEnd) { this.snippetEnd = null; this.pause() }
  }
  onPlaybackEnd() { this.store.set({ playing: false, preview: null }) }

  seekToBar(bar: number) {
    const song = this.store.state.song
    if (!song) return
    const b = Math.max(0, Math.min(song.bars, bar))
    const tick = Math.round(b * barTicks(song.meter))
    this.audio?.seek(tick)
    this.store.set({ positionTick: tick })
    this.interpreter.setPosition(b)
  }

  // ---- cards ------------------------------------------------------------------------------------

  cardSignature(song: Song): string {
    const { frontAssetId: _f, printedAt: _p, share: _s, ...rest } = song.card ?? {}
    void _f; void _p; void _s
    return JSON.stringify({ ...rest, title: song.title })
  }

  /** Fills in the city from the location service the first time the card screen opens, then draws the preview. */
  private enterCard() {
    const { song, city } = this.store.state
    if (!song?.card) return
    if (!song.card.city && city) void this.setCard({ city })
    else if (!song.card.frontAssetId || this.store.state.previewSig !== this.cardSignature(song)) this.schedulePreview(100)
  }

  private previewDebounce: ReturnType<typeof setTimeout> | null = null
  /** Any change to the card clears the preview: draw a new one shortly after the last change. */
  schedulePreview(ms = 700) {
    if (this.previewDebounce) clearTimeout(this.previewDebounce)
    this.previewDebounce = setTimeout(() => { if (this.store.state.view === 'card') void this.previewCard() }, ms)
  }

  async previewCard() {
    this.store.set({ cardBusy: true })
    try {
      const res = await this.mutate('card.preview', (s) => this.api.cardPreview(s.id, s.revision))
      if (res) this.store.set({ previewSig: this.cardSignature(res) })
    } finally { this.store.set({ cardBusy: false }) }
  }

  async printCard() {
    let s = this.store.state
    if (!s.song) return
    if (!s.song.card?.frontAssetId || s.previewSig !== this.cardSignature(s.song)) {
      await this.previewCard()
      s = this.store.state
      if (!s.song?.card?.frontAssetId) return
    }
    const res = await this.mutate('card.print', (song) => this.api.cardPrint(song.id, song.revision), true)
    if (res?.card?.printedAt) { this.toast('卡片正在印出来', 'info'); void this.refreshPrinter() }
  }

  // ---- scanning ----------------------------------------------------------------------------------

  /** Handles the text of a scanned QR code: a song page URL `https://<host>/s/{shareId}`. Returns whether it was ours. */
  async handleScan(text: string): Promise<boolean> {
    const m = /\/s\/([A-Za-z0-9_-]{10,32})\/?(?:[?#].*)?$/.exec(text.trim())
    if (!m) return false
    try {
      const songId = await this.api.resolveShare(m[1])
      this.store.set({ scanning: false })
      await this.openSong(songId, true)
    } catch (e) { this.fail(e) }
    return true
  }

  // ---- panel ------------------------------------------------------------------------------------

  onPanelStatus(s: { connected: boolean; panel: boolean }) {
    this.lastLights.clear(); this.lastRing = ''
    this.store.set({ panelAttached: s.connected, panelConnected: s.panel })
  }

  onPanelMessage(msg: { type: string; t?: number; payload?: Record<string, unknown> }) {
    this.interpreter.handle(msg)
    if (msg.type === 'snapshot') { this.lastLights.clear(); this.lastRing = ''; this.syncLights() }
  }

  syncLights() {
    const panel = this.panel
    const s = this.store.state
    if (!panel || !s.panelAttached) return
    const ring = computeRing(s.song, s.song ? s.positionTick / barTicks(s.song.meter) : 0)
    const ringKey = JSON.stringify(ring)
    if (ringKey !== this.lastRing) { this.lastRing = ringKey; panel.setRing(ring) }
    for (const l of computeKeyLights({ song: s.song, selected: s.selectedTrack, recording: !!s.recording, busy: !!s.busy, playing: s.playing, view: s.view })) {
      const k = `${l.mode}|${l.color ?? ''}`
      if (this.lastLights.get(l.id) !== k) { this.lastLights.set(l.id, k); panel.setKeyLight(l.id, l.mode, l.color) }
    }
  }

  private async onIntent(i: Intent) {
    this.log(`panel.${i.type}`, i)
    const s = this.store.state
    switch (i.type) {
      case 'record.start':
        if (s.view === 'capture') { this.setCaptureMode('hum'); void this.startRecording('hum') }
        else if ((s.view === 'shape' || s.view === 'detail') && s.song) void this.startRecording('hum')
        return
      case 'record.stop': void this.stopRecording(); return
      case 'photo': {
        if (s.view !== 'capture') return
        this.setCaptureMode('photo')
        const blob = await this.photoSource?.()
        if (blob) this.addPhoto(blob)
        else this.toast('先打开相机', 'info')
        return
      }
      case 'play.toggle':
        if (s.view === 'pick') void this.previewCandidate(s.focus)
        else void this.togglePlay()
        return
      case 'undo': void this.undo(); return
      case 'another': void this.another(i.section, i.track); return
      case 'pick.more': void this.moreCandidates({ again: true }); return
      case 'pick.focus': this.focusCandidate(i.index); return
      case 'region.section': {
        const sec = s.song?.sections[i.index]
        if (sec) this.selectSection(sec.id, s.looping)
        return
      }
      case 'region.param': {
        if (!s.song || !s.selectedTrack || !s.editSection) return
        void this.setRegion(s.selectedTrack, s.editSection, { [i.param]: i.value }) // already debounced by the interpreter (400 ms)
        return
      }
      case 'card.style': {
        const style = CARD_STYLE_ORDER[i.index]
        const hasPhoto = !!s.song?.card?.photoAssetIds?.length
        if (style && (style !== 'text' ? hasPhoto : true)) void this.setCard({ style })
        return
      }
      case 'track.select': this.selectTrack(s.selectedTrack === i.track ? null : i.track); return
      case 'track.mute': void this.toggleMute(i.track); return
      case 'seek': this.seekToBar(i.bar); return
      case 'volume': void this.setVolume(i.track, i.value); return
      case 'control': void this.setControl(i.control, i.value); return
      case 'tempo': void this.setTempo(i.value); return
      case 'faders.sync': {
        const song = s.song
        if (!song) return
        const ops: EditOp[] = []
        for (const [track, v] of Object.entries(i.faders) as [TrackId, number][]) {
          if (Math.abs(song.tracks[track].volume - v) >= 0.01) ops.push({ op: 'setTrackVolume', track, volume: v })
        }
        if (ops.length) await this.edit(ops)
        return
      }
    }
  }
}

export { CARD_STYLE_ORDER }
