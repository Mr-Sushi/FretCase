import { ApiError, type Api, type CardPatch, type EditOp, type KnobControl, type LeadTrack, type NoteInput } from '../api'
import { loopRangeFor } from '../audio/schedule'
import { MicRecorder } from '../lib/recorder'
import { trimStart } from '../audio/wav'
import { barTicks, hasExactLock, isLocked, previewStartTick, regionOf, sectionAtBar, secondsToTicks, trackName } from '../lib/song'
import { sectionLines, syllables } from '../lib/lyrics'
import { PanelInterpreter, type Intent } from '../panel/interpreter'
import { computeKeyLights, computeRing, type KeyLightMsg } from '../panel/lights'
import type { CardStyle, SeedCard, SeedInput, Song, SpaceId, TimeOfDay, TrackId } from '../types'
import { initialLyrics, MAX_PHOTOS, Store, type AppState, type CapturedInput, type LyricsUi, type View } from './store'

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
  /** Platter while playing: true when the song is played like a record; false means "seek instead". */
  jog?(delta: number): boolean
  /** Prepares what jog needs (a rendered copy of the song) in the background. */
  prepareJog?(): void
  /** Seconds between scheduling a sound and the user hearing it, plus the microphone's delay (for lining up a take). */
  latency?(): number
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
        playing: () => st.state.playing && !st.state.preview,
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
      this.store.set({ serverOnline: true, netOnline: h.online, lyricsAvailable: !!h.lyrics, renderAvailable: !!h.render })
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
          this.toast('The song has just changed; it is up to date now, so please try again', 'error'); return
        case 'offline_unavailable': this.toast(lyricsFailureText(lyricsFailure(e)) ?? 'This step needs the internet, and there is no connection now', 'error'); return
        case 'network': this.toast('Cannot reach the server', 'error'); this.store.set({ serverOnline: false }); return
        case 'timeout': this.toast('The server did not answer in time', 'error'); return
        // Server messages are English and meant for logs, so the toast stays in Chinese.
        case 'cannot_apply': {
          console.warn(e.message)
          const detail = (e as ApiError & { detail?: Record<string, unknown> }).detail ?? {}
          if (detail.printer) { this.toast('Something is wrong with the printer: not connected or out of film. Please check it', 'error'); return }
          if (/range/i.test(e.message)) { this.toast('This instrument cannot go any higher or lower', 'error'); return }
          if (detail.reason === 'no_motif') { this.toast('This song has no hum, so there is no tune to go back to', 'error'); return }
          this.toast('That cannot be done right now', 'error'); return
        }
        case 'not_implemented': console.warn(e.message); this.toast('This is not ready yet', 'error'); return
        default: console.warn(e.code, e.message); this.toast('Something went wrong', 'error'); return
      }
    }
    this.toast('Something went wrong', 'error')
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
    if (!this.canGo(view)) { this.toast(view === 'pick' ? 'Make songs from what you captured first' : 'Choose a song first', 'info'); return }
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

  /** Plays the chosen section from its start, in a loop: one player alone (`track`) or everyone (null). */
  async hearRegion(track: TrackId | null) {
    const s = this.store.state
    const sec = s.editSection ?? s.song?.sections[0]?.id
    if (!s.song || !sec) return
    if (s.solo !== track) { this.store.set({ solo: track }); this.audio?.setSolo?.(track) }
    this.selectSection(sec, true)
    await this.play()
    this.log('region.hear', { track, sec })
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
    if (!sameSong) { this.stopStudio(); this.audio?.seek(0); this.store.set({ solo: null, takes: {}, previewSig: null, lyrics: initialLyrics(), selectedTrack: null }); this.audio?.setSolo?.(null) }
    this.applyLoop()
  }

  async openSong(id: string, thenPlay = false) {
    try {
      this.store.set({ busy: 'Opening' })
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
    if (song && tr && isLocked(song, tr, sec)) this.toast(`${trackName(tr)} is kept as it is in this section`, 'info')
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
    if (this.photos().length >= MAX_PHOTOS) { this.toast(`Up to ${MAX_PHOTOS} photos. Remove one first`, 'info'); return false }
    const id = `photo-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    this.addInput({ id, kind: 'photo', label: 'Photo', blob, url: URL.createObjectURL(blob) })
    this.store.set({ photoSel: id })
    this.log('photo.add', this.photos().length)
    return true
  }
  /** Retake: drops the selected photo (the last one by default) so the next shot replaces it. */
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
      this.toast('Cannot use the microphone. Please check the permission', 'error')
    }
  }

  async stopRecording() {
    const kind = this.store.state.recording
    if (!kind) return
    this.store.set({ recording: null })
    const blob = await this.recorder.stop()
    if (!blob) { this.toast('That was too short. Hold it a little longer', 'info'); return }
    this.log('record.stop', kind)
    await this.handleRecording(kind, blob)
  }

  /** A finished recording: a new input on the capture screen, or a re-hum of the selected section on the shape and track screens. */
  async handleRecording(kind: 'hum' | 'sound', blob: Blob) {
    const s = this.store.state
    if (kind === 'hum' && s.song && (s.view === 'shape' || s.view === 'detail')) {
      try {
        this.store.set({ busy: 'Uploading' })
        const asset = await this.api.uploadAsset(blob, 'hum')
        const sec = s.editSection ?? this.interpreter.sectionUnderPlatter()?.id ?? s.song.sections[0].id
        await this.mutate('rehum', (song) => this.api.rehum(song.id, song.revision, sec, asset.id), true)
      } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
      return
    }
    const n = s.inputs.filter((i) => i.kind === kind).length + 1
    this.addInput({ id: `${kind}-${Date.now()}`, kind, label: kind === 'hum' ? 'Hum' : 'Sound', blob, url: URL.createObjectURL(blob) })
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

  /** Make songs: upload, understand (seed), then three candidates. */
  async makeSong() {
    const { inputs } = this.store.state
    if (!inputs.length) { this.toast('Take a photo, hum a tune or write a line first', 'info'); return }
    try {
      this.store.set({ busy: 'Gathering what you captured' })
      const seedInputs = await this.uploadInputs()
      this.store.set({ busy: 'Reading what you captured' })
      const seed: SeedCard = await this.api.createSeed(seedInputs)
      this.store.set({ busy: 'Making three songs', seed })
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

  /** Day / Dusk / Night, or None of these, three more (with the previous group). */
  async moreCandidates(opts: { timeOfDay?: TimeOfDay; again?: boolean } = {}) {
    const s = this.store.state
    if (!s.seed) return
    const tod = opts.timeOfDay ?? s.timeOfDay
    try {
      this.store.set({ busy: 'Making three songs', timeOfDay: tod })
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
      this.store.set({ busy: 'Saving the song' })
      const song = await this.api.choose(cand.id)
      this.store.set({ candidates: null, seed: null, inputs: [], photoSel: null })
      this.setSong(song)
      this.store.set({ view: 'shape', positionTick: 0, editSection: song.sections[0].id, looping: false })
      this.applyLoop()
      void this.refreshSongs()
      this.log('candidate.choose', index)
      // New songs sing "la". With a lyrics model on the server, words are written in the background right away.
      if (this.store.state.lyricsAvailable) void this.writeFirstLyrics(song.id)
    } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
  }

  private async writeFirstLyrics(songId: string) {
    const song = this.store.state.song
    if (!song || song.id !== songId) return
    this.setLyricsUi({ writing: true })
    this.toast('Writing the lyrics…')
    try {
      const themes = (await this.api.lyricsThemes(songId)).slice(0, 4).map((t) => t.text)
      const cur = this.store.state.song
      if (!cur || cur.id !== songId) return
      const written = await this.api.lyricsRewrite(songId, cur.revision, { themes, tone: 'plain', rhyme: true })
      // Only apply it if nothing changed meanwhile; otherwise the user's edits win and words can be asked for again.
      if (this.store.state.song?.id === songId && this.store.state.song.revision === cur.revision) {
        this.setSong(written)
        this.toast('The lyrics are written; change them on the lyrics page')
      }
      this.log('lyrics.first', 'ok')
    } catch (e) {
      const reason = lyricsFailure(e)
      this.setLyricsUi({ offline: true, offlineReason: reason })
      if (reason !== 'conflict') this.toast(`No lyrics this time: ${lyricsFailureText(reason) ?? 'try again on the lyrics page'}`, 'error')
      this.log('lyrics.first', reason)
    } finally { this.setLyricsUi({ writing: false }) }
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
    if (!res && misfit.length) this.toast('Some lines do not have as many syllables as notes', 'error')
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
      if (cur && cur.section === section && cur.index === index) this.setLyricsUi({ alternatives, offline: false, offlineReason: null, loading: false })
    } catch (e) {
      const off = e instanceof ApiError && (e.code === 'offline_unavailable' || e.code === 'timeout' || e.code === 'network')
      this.setLyricsUi({ alternatives: null, offline: off ? true : this.store.state.lyrics.offline, offlineReason: off ? lyricsFailure(e) : this.store.state.lyrics.offlineReason, loading: false })
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

  /** "Rewrite the lines not kept", or one section only (rewrite the whole section, which ignores that section's keeps). */
  async rewriteLyrics(sections?: string[]) {
    const l = this.store.state.lyrics
    const keep = { ...l.keeps }
    if (sections) for (const s of sections) delete keep[s]
    this.setLyricsUi({ writing: true })
    const res = await this.mutate('lyrics.rewrite', async (s) => {
      try {
        return await this.api.lyricsRewrite(s.id, s.revision, { ...(sections ? { sections } : {}), keep, themes: l.themeSel, tone: l.tone, rhyme: l.rhyme })
      } catch (e) {
        if (e instanceof ApiError && (e.code === 'offline_unavailable' || e.code === 'timeout' || e.code === 'network')) this.setLyricsUi({ offline: true, offlineReason: lyricsFailure(e) })
        throw e
      }
    }, true)
    this.setLyricsUi({ writing: false })
    if (res) this.setLyricsUi({ offline: false, offlineReason: null, misfit: [] })
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

  // ---- the studio version ---------------------------------------------------------------------

  private studioAudio: HTMLAudioElement | null = null
  private studioAudioId: string | null = null
  /** How often a running render is asked about, and for how long. */
  studioPollMs = 1500
  studioTimeoutMs = 6 * 60 * 1000

  private setStudio(patch: Partial<AppState['studio']>) { this.store.set({ studio: { ...this.store.state.studio, ...patch } }) }

  /** Asks the server's music model to sing and play the whole song, and waits for the job. */
  async makeStudioVersion() {
    const song = this.store.state.song
    if (!song || this.store.state.studio.working) return
    this.stopStudio()
    this.setStudio({ working: true, startedAt: Date.now() })
    this.log('studio.start', { revision: song.revision })
    try {
      let job = await this.api.render(song.id, song.revision)
      const deadline = Date.now() + this.studioTimeoutMs
      while (job.state === 'running') {
        if (Date.now() > deadline) throw new ApiError('timeout', 'The studio version took too long', 0)
        await new Promise((r) => setTimeout(r, this.studioPollMs))
        job = await this.api.job(job.id)
      }
      if (job.state === 'failed') throw new ApiError(job.error?.code ?? 'http_error', job.error?.message ?? 'The render failed', 503, undefined, job.error?.detail)
      const done = job.result?.song
      if (done && this.store.state.song?.id === done.id) this.setSong(done)
      this.toast('The studio version is ready: press its play button to hear it sung')
      this.log('studio.done')
    } catch (e) {
      if (e instanceof ApiError && e.code === 'revision_conflict' && e.song) { this.setSong(e.song); this.toast('The song had just changed; it is up to date now, so please try again', 'error') }
      else this.toast(studioFailureText(e), 'error')
      this.log('studio.failed', { code: e instanceof ApiError ? e.code : 'error', reason: e instanceof ApiError ? e.detail?.reason : undefined })
    } finally {
      this.setStudio({ working: false, startedAt: null })
    }
  }

  /** Plays or stops the studio version (the arrangement stops while it plays). */
  toggleStudio() { if (this.store.state.studio.playing) this.stopStudio(); else this.playStudio() }

  playStudio() {
    const render = this.store.state.song?.render
    if (!render || typeof Audio === 'undefined') return
    if (this.store.state.playing) this.pause()
    if (!this.studioAudio || this.studioAudioId !== render.assetId) {
      this.studioAudio?.pause()
      this.studioAudio = new Audio(this.api.assetUrl(render.assetId))
      this.studioAudioId = render.assetId
      this.studioAudio.onended = () => this.setStudio({ playing: false })
      this.studioAudio.onerror = () => { this.setStudio({ playing: false }); this.toast('The studio version could not be played', 'error') }
    }
    this.studioAudio.currentTime = 0
    void this.studioAudio.play().catch(() => this.setStudio({ playing: false }))
    this.setStudio({ playing: true })
    this.log('studio.play')
  }

  stopStudio() {
    if (!this.store.state.studio.playing && !this.studioAudio) return
    this.studioAudio?.pause()
    if (this.store.state.studio.playing) this.setStudio({ playing: false })
  }

  // ---- singing one's own vocal ---------------------------------------------------------------------

  private takePlayStart = 0

  /** Records the user singing over the whole song (the guide voice plays so they can follow it). */
  async recordVocalTake() {
    const s = this.store.state
    if (!s.song || !this.audio || s.vocalTake || s.recording) return
    if (!MicRecorder.supported()) { this.toast('This browser cannot record (it needs HTTPS)', 'error'); return }
    this.stopStudio()
    this.pause()
    try { await this.recorder.start() } catch { this.toast('Cannot use the microphone. Please check the permission', 'error'); return }
    this.store.set({ vocalTake: 'recording' })
    this.audio.setLoop(null)
    this.audio.seek(0)
    await this.audio.play()
    this.takePlayStart = performance.now()
    this.store.set({ playing: true })
    this.log('take.start')
  }

  /** Stops recording, lines the take up with the song and puts it on the vocal track. */
  async finishVocalTake() {
    if (this.store.state.vocalTake !== 'recording') return
    this.store.set({ vocalTake: 'saving' })
    const recStart = this.recorder.startedAt
    const blob = await this.recorder.stop(1000)
    this.pause()
    try {
      if (!blob) { this.toast('That was too short to keep', 'info'); return }
      const lead = Math.max(0, (this.takePlayStart - recStart) / 1000) + (this.audio?.latency?.() ?? 0.06)
      const wav = await trimStart(blob, lead)
      const asset = await this.api.uploadAsset(wav ?? blob, 'vocal_take')
      await this.mutate('take.save', (song) => this.api.edit(song.id, song.revision, [{ op: 'setVocalTake', assetId: asset.id }]), true)
      this.toast('Your vocal is on the song now')
      this.log('take.saved')
    } catch (e) { this.fail(e) } finally { this.store.set({ vocalTake: null }) }
  }

  /** Back to the guide voice playing the vocal notes. */
  async removeVocalTake() {
    await this.mutate('take.remove', (song) => this.api.edit(song.id, song.revision, [{ op: 'setVocalTake', assetId: null }]), true)
  }

  /** Characters typed for a line, for counting: the app never changes the song itself. */
  static countChars(text: string) { return syllables(text).length }

  // ---- playback -------------------------------------------------------------------------------

  async play() {
    if (!this.audio || !this.store.state.song) return
    this.stopStudio()
    this.snippetEnd = null
    this.applyLoop()
    await this.audio.play()
    this.store.set({ playing: true })
    this.audio.prepareJog?.()
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
  onPlaybackEnd() {
    this.store.set({ playing: false, preview: null })
    if (this.store.state.vocalTake === 'recording') void this.finishVocalTake()
  }

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
    if (res?.card?.printedAt) { this.toast('The card is printing', 'info'); void this.refreshPrinter() }
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
        if (s.view === 'capture') {
          // Holding the red key records the sound mode's ambience when that mode is chosen, a hum otherwise.
          const kind = s.captureMode === 'sound' ? 'sound' : 'hum'
          this.setCaptureMode(kind)
          void this.startRecording(kind)
        } else if ((s.view === 'shape' || s.view === 'detail') && s.song) void this.startRecording('hum')
        return
      case 'record.stop': void this.stopRecording(); return
      case 'photo': {
        if (s.view !== 'capture') return
        // In the hum and sound modes a short press starts the recording and the next short press stops it.
        if (s.captureMode === 'hum' || s.captureMode === 'sound') {
          if (s.recording) void this.stopRecording()
          else void this.startRecording(s.captureMode)
          return
        }
        this.setCaptureMode('photo')
        const blob = await this.photoSource?.()
        if (blob) this.addPhoto(blob)
        else this.toast('Turn on the camera first', 'info')
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
      case 'pick.choose': if (s.view === 'pick') void this.chooseCandidate(i.index); return
      case 'card.print': if (s.view === 'card' && !s.cardBusy) void this.printCard(); return
      case 'card.printHint': if (s.view === 'card') this.toast('Hold the red key for about a second to print', 'info'); return
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
      case 'jog': if (!this.audio?.jog?.(i.delta)) this.seekToBar(i.bar); return
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

/** Why a lyrics call failed: the server's error.detail.reason, "network" when the server could not be reached in time. */
export function lyricsFailure(e: unknown): string {
  if (!(e instanceof ApiError)) return 'network'
  if (e.code === 'revision_conflict') return 'conflict'
  if (e.code === 'timeout' || e.code === 'network') return 'network'
  const reason = (e.detail as { reason?: string } | undefined)?.reason
  return reason ?? 'network'
}

/** Plain words for each reason; null when the generic network text fits. */
/** A plain sentence for a studio version that could not be made. */
export function studioFailureText(e: unknown): string {
  const reason = e instanceof ApiError ? (e.detail?.reason as string | undefined) ?? (e.code === 'timeout' || e.code === 'network' ? 'network' : undefined) : undefined
  switch (reason) {
    case 'not_configured': return 'The studio version needs a music model on the server (a Gemini API key for Lyria)'
    case 'auth': return 'The music model key is wrong. Please check the settings'
    case 'rate_limited': return 'The music model is busy. Try again in a while'
    case 'blocked': return 'The music model would not make this song. Try changing the lyrics or the title'
    case 'timeout': return 'The music model took too long. Try again'
    case 'bad_answer': return 'The music model sent no audio this time. Try again'
    case 'unreachable': case 'network': return 'Making the studio version needs the internet, which is not available now'
    default: return 'The studio version could not be made'
  }
}

export function lyricsFailureText(reason: string | null): string | null {
  switch (reason) {
    case 'not_configured': return 'No lyrics model is connected yet'
    case 'auth': return 'The lyrics model key is wrong. Please check the settings'
    case 'rate_limited': return 'The lyrics model is busy. Try again in a while'
    case 'bad_answer': return 'The lines did not come out the right length. Try again'
    case 'timeout': return 'The lyrics model took too long. Try again'
    case 'unreachable': case 'network': return 'Writing lyrics needs the internet, which is not available now'
    default: return null
  }
}
