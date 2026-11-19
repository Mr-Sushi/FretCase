import { ApiError, type Api, type CardPatch, type EditOp, type KnobControl, type NoteInput } from '../api'
import { loopRangeFor } from '../audio/schedule'
import { MicRecorder } from '../lib/recorder'
import { barTicks, hasExactLock, isLocked, sectionAtBar, trackName } from '../lib/song'
import { PanelInterpreter, type Intent } from '../panel/interpreter'
import { computeKeyLights, computeRing, type KeyLightMsg } from '../panel/lights'
import type { SeedCard, SeedInput, Song, TrackId } from '../types'
import { Store, type CapturedInput, type View } from './store'

/** What the controller needs from the playback engine (the Tone.js engine, or a fake in tests). */
export interface AudioLike {
  load(song: Song): Promise<void> | void
  play(): Promise<void> | void
  stop(): void
  seek(tick: number): void
  setLoop(range: { from: number; to: number } | null): void
  setTrackGain(track: TrackId, volume: number, muted: boolean): void
}

/** What the controller needs from the panel socket. */
export interface PanelLike {
  setRing(pixels: (string | null)[], brightness?: number): boolean
  setKeyLight(id: string, mode: KeyLightMsg['mode'], color?: string): boolean
}

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
  interpreter: PanelInterpreter
  panel: PanelLike | null = null
  /** Registered by the capture view while the rear camera is open. */
  photoSource: (() => Promise<Blob | null>) | null = null

  constructor(public api: Api, public store: Store, public audio: AudioLike | null) {
    this.interpreter = new PanelInterpreter(
      {
        get bars() { return store.state.song?.bars ?? 1 },
        get sections() { return store.state.song?.sections ?? [] },
        get selectedTrack() { return store.state.selectedTrack },
        volume: (t) => store.state.song?.tracks[t].volume ?? 0.8,
        controlValue: (c) => store.state.song?.controls[c] ?? 0.5,
        tempo: () => store.state.song?.tempo ?? 84,
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
    try { store.set({ catalog: await api.catalog() }) } catch { /* the app still works with defaults */ }
    try { const loc = await api.getLocation(); store.set({ city: loc.city ?? '' }) } catch { /* optional */ }
    await this.refreshSongs()
  }

  dispose() {
    if (this.logTimer) clearInterval(this.logTimer)
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
        case 'cannot_apply': console.warn(e.message); this.toast('这一步现在做不了', 'error'); return
        case 'not_implemented': console.warn(e.message); this.toast('这个功能还没做好', 'error'); return
        default: console.warn(e.code, e.message); this.toast('出错了', 'error'); return
      }
    }
    this.toast('出错了', 'error')
  }

  // ---- navigation ---------------------------------------------------------------------------

  setView(view: View) {
    const s = this.store.state
    if ((view === 'song' || view === 'track' || view === 'card') && !s.song) { this.toast('先做一首歌', 'info'); return }
    if (view !== 'track' && s.editSection) { this.store.set({ editSection: null }); this.audio?.setLoop(null) }
    this.store.set({ view, scanning: false })
    this.log('view', view)
  }

  /** Opens the track editor on the section under the play position and loops it. */
  editTrack(track: TrackId, sectionId?: string) {
    const song = this.store.state.song
    if (!song) return
    const sec = sectionId ?? this.sectionUnderPosition()?.id ?? song.sections[0].id
    this.store.set({ view: 'track', selectedTrack: track, editSection: sec })
    this.audio?.setLoop(loopRangeFor(song, sec))
    this.log('edit.open', { track, sec })
  }

  setEditSection(sectionId: string) {
    const song = this.store.state.song
    if (!song) return
    this.store.set({ editSection: sectionId })
    this.audio?.setLoop(loopRangeFor(song, sectionId))
    const sec = song.sections.find((s) => s.id === sectionId)
    if (sec) this.seekToBar(sec.startBar)
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
    if (!sameSong) this.audio?.seek(0)
    if (this.store.state.editSection) this.audio?.setLoop(loopRangeFor(song, this.store.state.editSection))
  }

  async openSong(id: string, thenPlay = false) {
    try {
      this.store.set({ busy: '正在打开' })
      const song = await this.api.getSong(id)
      this.setSong(song)
      this.store.set({ view: 'song', positionTick: 0, selectedTrack: null, editSection: null })
      this.audio?.setLoop(null)
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

  // ---- edits used by the views and the panel --------------------------------------------------

  setVolume(track: TrackId, value: number) {
    const song = this.store.state.song
    if (song) this.audio?.setTrackGain(track, value, song.tracks[track].muted) // instant, before the round trip
    return this.edit([{ op: 'setTrackVolume', track, volume: value }])
  }
  /** Moves the gain only (while a slider is being dragged); the edit follows on release. */
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
  setControl(control: KnobControl, value: number) { return this.edit([{ op: 'setControl', control, value }], true) }
  setTempo(tempo: number) { return this.edit([{ op: 'setTempo', tempo }]) }
  setInstrument(track: TrackId, instrument: string) { return this.edit([{ op: 'setInstrument', track, instrument }]) }
  setRhythm(family: 'strumming' | 'arpeggio', presetId: string) { return this.edit([{ op: 'setRhythm', family, presetId }], true) }
  setTitle(title: string) { return this.edit([{ op: 'setTitle', title }]) }
  setCard(patch: CardPatch) { return this.edit([{ op: 'setCard', ...patch }]) }

  replaceNotes(track: TrackId, from: number, to: number, notes: NoteInput[]) {
    return this.edit([{ op: 'replaceNotes', track, from, to, notes }])
  }
  async setLyrics(section: string, text: string): Promise<{ ok: boolean; noteCount?: number; syllableCount?: number }> {
    const song = this.store.state.song
    if (!song) return { ok: false }
    let detail: { noteCount?: number; syllableCount?: number } | undefined
    const res = await this.mutate('setLyrics', async (s) => {
      try { return await this.api.edit(s.id, s.revision, [{ op: 'setLyrics', section, text }]) }
      catch (e) {
        if (e instanceof ApiError && e.code === 'cannot_apply' && e.detail && 'noteCount' in e.detail) {
          detail = e.detail as typeof detail
          throw new ApiError('lyrics_count', `这一段有 ${e.detail.noteCount} 个音，歌词有 ${e.detail.syllableCount} 个字`, 422)
        }
        throw e
      }
    })
    return res ? { ok: true } : { ok: false, ...detail }
  }

  toggleLock(track?: TrackId, section?: string) {
    const song = this.store.state.song
    if (!song) return null
    const op = hasExactLock(song, track, section) ? 'unlock' : 'lock'
    return this.edit([{ op, ...(track ? { track } : {}), ...(section ? { section } : {}) } as EditOp])
  }

  async another(section?: string, track?: TrackId) {
    const sec = section ?? this.sectionUnderPosition()?.id
    if (!sec) return
    const tr = track ?? this.store.state.selectedTrack ?? undefined
    const song = this.store.state.song
    if (song && isLocked(song, tr ?? null, sec) && tr) this.toast(`${trackName(tr)}在这一段被锁定了`, 'info')
    await this.mutate('another', (s) => this.api.another(s.id, s.revision, sec, tr), true)
  }

  async undo() { await this.mutate('undo', (s) => this.api.undo(s.id, s.revision), true) }

  // ---- capture and the seed card ---------------------------------------------------------------

  addInput(i: CapturedInput) { this.store.set({ inputs: [...this.store.state.inputs, i] }) }
  removeInput(id: string) { this.store.set({ inputs: this.store.state.inputs.filter((i) => i.id !== id) }) }
  addText(text: string) {
    const t = text.trim()
    if (!t) return
    this.addInput({ id: `text-${Date.now()}`, kind: 'text', label: t, text: t })
  }

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

  /** A finished recording: a new input, or a re-hum of one section when a song is open on the song or track view. */
  async handleRecording(kind: 'hum' | 'sound', blob: Blob) {
    const s = this.store.state
    try {
      this.store.set({ busy: '正在上传' })
      const asset = await this.api.uploadAsset(blob, kind === 'hum' ? 'hum' : 'ambience')
      if (kind === 'hum' && s.song && (s.view === 'song' || s.view === 'track')) {
        const sec = this.interpreter.sectionUnderPlatter() ?? this.sectionUnderPosition()
        if (sec) {
          await this.mutate('rehum', (song) => this.api.rehum(song.id, song.revision, sec.id, asset.id), true)
          return
        }
      }
      this.addInput({
        id: asset.id, kind, assetId: asset.id, url: this.api.assetUrl(asset.id),
        label: kind === 'hum' ? '哼唱' : '环境声',
      })
      if (s.view !== 'capture') this.store.set({ view: 'capture' })
    } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
  }

  async addPhoto(blob: Blob) {
    try {
      this.store.set({ busy: '正在上传' })
      const asset = await this.api.uploadAsset(blob, 'photo')
      this.addInput({ id: asset.id, kind: 'photo', assetId: asset.id, url: this.api.assetUrl(asset.id), label: '照片' })
    } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
  }

  async makeSeed() {
    const { inputs } = this.store.state
    if (!inputs.length) { this.toast('先哼一段、拍一张或写一句话', 'info'); return }
    const seedInputs: SeedInput[] = inputs.map((i) => (i.kind === 'text' ? { kind: 'text', text: i.text } : { kind: i.kind, assetId: i.assetId }))
    try {
      this.store.set({ busy: '正在理解你的输入' })
      const seed = await this.api.createSeed(seedInputs)
      this.store.set({ seed })
      this.log('seed', { source: seed.source })
    } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
  }

  updateSeed(seed: SeedCard) { this.store.set({ seed }) }

  async generate(bars?: number) {
    const { seed } = this.store.state
    if (!seed) return
    try {
      this.store.set({ busy: '正在写歌' })
      const song = await this.api.createSong(seed, bars)
      this.setSong(song)
      this.store.set({ view: 'song', positionTick: 0, selectedTrack: null, editSection: null, previewSig: null, inputs: [], seed: null })
      this.audio?.setLoop(null)
      this.log('song.create', song.id)
      void this.refreshSongs()
    } catch (e) { this.fail(e) } finally { this.store.set({ busy: null }) }
  }

  // ---- playback -------------------------------------------------------------------------------

  async play() {
    if (!this.audio || !this.store.state.song) return
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
  }
  onPlaybackEnd() { this.store.set({ playing: false }) }

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
    const { frontAssetId: _f, backAssetId: _b, printedAt: _p, share: _s, ...rest } = song.card ?? {}
    void _f; void _b; void _p; void _s
    return JSON.stringify({ ...rest, title: song.title })
  }

  async previewCard() {
    const res = await this.mutate('card.preview', (s) => this.api.cardPreview(s.id, s.revision), true)
    if (res) this.store.set({ previewSig: this.cardSignature(res) })
  }

  async printCard() {
    const s = this.store.state
    if (!s.song || s.previewSig !== this.cardSignature(s.song)) { this.toast('请先预览，确认后再打印', 'info'); return }
    const res = await this.mutate('card.print', (song) => this.api.cardPrint(song.id, song.revision), true)
    if (res?.card?.printedAt) this.toast('卡片已打印', 'info')
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
    this.lastLights.clear(); this.lastRing = '' // a (re)connected panel knows nothing: send everything
    this.store.set({ panelAttached: s.connected, panelConnected: s.panel }) // the store listener sends the lights
  }

  onPanelMessage(msg: { type: string; t?: number; payload?: Record<string, unknown> }) {
    this.interpreter.handle(msg)
    if (msg.type === 'snapshot') { this.lastLights.clear(); this.lastRing = ''; this.syncLights() }
  }

  /** Sends only the lights that changed since the last send. */
  syncLights() {
    const panel = this.panel
    const s = this.store.state
    if (!panel || !s.panelAttached) return
    const ring = computeRing(s.song, s.song ? s.positionTick / barTicks(s.song.meter) : 0)
    const ringKey = JSON.stringify(ring)
    if (ringKey !== this.lastRing) { this.lastRing = ringKey; panel.setRing(ring) }
    for (const l of computeKeyLights({ song: s.song, selected: s.selectedTrack, recording: !!s.recording, busy: !!s.busy, playing: s.playing })) {
      const k = `${l.mode}|${l.color ?? ''}`
      if (this.lastLights.get(l.id) !== k) { this.lastLights.set(l.id, k); panel.setKeyLight(l.id, l.mode, l.color) }
    }
  }

  private async onIntent(i: Intent) {
    this.log(`panel.${i.type}`, i)
    const s = this.store.state
    switch (i.type) {
      case 'record.start': void this.startRecording('hum'); return
      case 'record.stop': void this.stopRecording(); return
      case 'photo': {
        if (s.view !== 'capture') { this.setView('capture') }
        const blob = await this.photoSource?.()
        if (blob) await this.addPhoto(blob)
        else this.toast('先在采集页打开相机', 'info')
        return
      }
      case 'play.toggle': void this.togglePlay(); return
      case 'undo': void this.undo(); return
      case 'another': void this.another(i.section, i.track); return
      case 'track.select': this.selectTrack(s.selectedTrack === i.track ? null : i.track); return
      case 'track.mute': void this.toggleMute(i.track); return
      case 'seek': this.seekToBar(i.bar); return
      case 'volume': void this.setVolume(i.track, i.value); return
      case 'control': void this.setControl(i.control, i.value); return
      case 'tempo': void this.setTempo(i.value); return
      case 'faders.sync': {
        // Faders are not motorised: the panel's positions win, whatever the song said.
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
