import { useEffect, useMemo, useRef, useState } from 'react'
import { HttpApi, MockApi, isMockMode } from '../api'
import { ApiError } from '../api/types'
import { PlaybackEngine } from '../audio/engine'
import { encodeWav, renderSong } from '../audio/offline'
import { formatClock, songSeconds, ticksToSeconds } from '../lib/song'
import type { SharePage, Song } from '../types'
import { buildModel, currentLineIndex, currentSectionIndex, shareIdFromLocation, type PageModel } from './model'

type Load = { state: 'loading' } | { state: 'error'; text: string } | { state: 'ready'; page: SharePage; song: Song }

/** The page the QR code opens, on a phone. It shows what /api/share/{shareId}/page gives and plays the song with the app's own player. */
export function SongPage() {
  const shareId = useMemo(() => shareIdFromLocation(location), [])
  const mock = isMockMode()
  const api = useMemo(() => (mock ? new MockApi(0) : new HttpApi('')), [mock])
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  useEffect(() => {
    if (!shareId) { setLoad({ state: 'error', text: 'This link is incomplete. Please scan the QR code on the card again.' }); return }
    api.sharePage(shareId).then(
      (r) => setLoad({ state: 'ready', page: r.page, song: r.song }),
      (e) => setLoad({ state: 'error', text: e instanceof ApiError && e.status === 404 ? 'This song cannot be found. It may not be shared yet.' : 'This song cannot be opened right now. Please try again later.' }),
    )
  }, [api, shareId])
  if (load.state === 'loading') return <div className="sp-wrap"><div className="sp-msg">Opening…</div></div>
  if (load.state === 'error') return <div className="sp-wrap"><div className="sp-msg">{load.text}</div></div>
  return <Ready page={load.page} song={load.song} assetUrl={(id) => (mock ? api.assetUrl(id) : `/api/share/${encodeURIComponent(shareId!)}/assets/${encodeURIComponent(id)}`)} />
}

function Ready({ page, song, assetUrl }: { page: SharePage; song: Song; assetUrl: (id: string) => string }) {
  const model: PageModel = useMemo(() => buildModel(page, song), [page, song])
  const [tick, setTick] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [photo, setPhoto] = useState(0)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')
  const engine = useRef<PlaybackEngine | null>(null)
  // The studio version (sung by a music model) is what the listener hears first when the song has one.
  const render = page.render
  const [mode, setMode] = useState<'studio' | 'arrangement'>(render ? 'studio' : 'arrangement')
  const studio = useRef<HTMLAudioElement | null>(null)
  const [studioSecs, setStudioSecs] = useState(0)
  const [studioTotal, setStudioTotal] = useState(song.render?.durationSec ?? 0)
  useEffect(() => {
    const e = new PlaybackEngine(assetUrl, { onPosition: setTick, onEnd: () => setPlaying(false) })
    engine.current = e
    void e.load(song)
    return () => e.dispose()
  }, [song, assetUrl])
  useEffect(() => {
    if (!render) return
    const a = new Audio(render.audio)
    a.preload = 'metadata'
    a.ontimeupdate = () => setStudioSecs(a.currentTime)
    a.onloadedmetadata = () => { if (Number.isFinite(a.duration)) setStudioTotal(a.duration) }
    a.onended = () => setPlaying(false)
    studio.current = a
    return () => { a.pause(); studio.current = null }
  }, [render])

  const isStudio = mode === 'studio' && !!render
  const total = isStudio ? studioTotal || 1 : songSeconds(song)
  const secs = isStudio ? studioSecs : ticksToSeconds(tick, song.tempo)
  const stopAll = () => { engine.current?.stop(); studio.current?.pause(); setPlaying(false) }
  const toggle = async () => {
    if (playing) { stopAll(); return }
    if (isStudio) { try { await studio.current?.play(); setPlaying(true) } catch { flash('This phone would not play the song. Tap play again') } return }
    const e = engine.current
    if (!e) return
    await e.play(); setPlaying(true)
  }
  const seek = (frac: number) => {
    if (isStudio) { if (studio.current && studioTotal) studio.current.currentTime = frac * studioTotal; return }
    engine.current?.seek(Math.round(frac * (total / 60) * song.tempo * 480))
  }
  const switchMode = (m: 'studio' | 'arrangement') => { if (m !== mode) { stopAll(); setMode(m) } }
  const curLine = isStudio ? -1 : currentLineIndex(model, tick)
  const curSection = isStudio ? -1 : currentSectionIndex(model, tick)
  const shownLyrics = isStudio && render ? render.lyrics.map((g) => ({ section: g.section, lines: g.lines.map((text) => ({ text })) })) : model.lyrics
  const flash = (t: string) => { setNote(t); setTimeout(() => setNote(''), 3000) }

  const save = async () => {
    if (saving) return
    setSaving(true)
    try {
      const file = isStudio && render ? await (await fetch(render.audio)).blob() : encodeWav(await renderSong(song, assetUrl))
      const ext = file.type.includes('wav') ? 'wav' : file.type.includes('mpeg') || file.type.includes('mp3') ? 'mp3' : 'wav'
      const a = document.createElement('a')
      a.href = URL.createObjectURL(file)
      a.download = `${model.title || 'FretCase'}.${ext}`
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(a.href), 10000)
      flash('Saved. You will find it in Downloads')
    } catch { flash('Saving did not work. Please try again') } finally { setSaving(false) }
  }
  const share = async () => {
    const link = location.href
    try {
      if (navigator.share) await navigator.share({ title: model.title, text: model.line ?? model.title, url: link })
      else { await navigator.clipboard.writeText(link); flash('Link copied') }
    } catch (e) { if ((e as Error).name !== 'AbortError') flash('Sharing did not work') }
  }

  return (
    <div className="sp-wrap">
      <div className="sp">
        {model.photos.length > 0 && (
          <>
            <img className="sp-hero" src={model.photos[photo] ?? model.photos[0]} alt="Photo taken while writing the song" />
            {model.photos.length > 1 && (
              <div role="group" aria-label="Photos taken while writing the song" className="sp-thumbs">
                {model.photos.map((p, i) => (
                  <button key={p} type="button" aria-label={`See photo ${i + 1}`} aria-pressed={i === photo} className={i === photo ? 'on' : ''} onClick={() => setPhoto(i)}><img src={p} alt="" /></button>
                ))}
              </div>
            )}
          </>
        )}
        <div className="sp-title">
          {model.subtitle && <div className="sp-sub">{model.subtitle}</div>}
          <h1>{model.title}</h1>
          {model.meta && <div className="sp-meta">{model.meta}</div>}
        </div>

        <section aria-label="Player" className="sp-player">
          {render && (
            <div role="group" aria-label="Which version" className="sp-modes">
              <button type="button" aria-pressed={isStudio} className={isStudio ? 'on' : ''} onClick={() => switchMode('studio')}>Sung</button>
              <button type="button" aria-pressed={!isStudio} className={!isStudio ? 'on' : ''} onClick={() => switchMode('arrangement')}>Arrangement</button>
            </div>
          )}
          <div className="sp-row">
            <button type="button" className="sp-play" aria-label={playing ? 'Pause' : 'Play'} onClick={() => void toggle()}>
              {playing ? <svg width="20" height="20" viewBox="0 0 18 18" aria-hidden="true"><rect x="3" y="2" width="4" height="14" fill="#1C1410" /><rect x="11" y="2" width="4" height="14" fill="#1C1410" /></svg>
                : <svg width="20" height="20" viewBox="0 0 18 18" aria-hidden="true"><path d="M4 2l12 7-12 7z" fill="#1C1410" /></svg>}
            </button>
            <div className="sp-grow">
              <div className="sp-bar" onPointerDown={(e) => { const r = e.currentTarget.getBoundingClientRect(); seek((e.clientX - r.left) / r.width) }}><div style={{ width: `${Math.min(100, (secs / total) * 100)}%` }} /></div>
              <div className="sp-times"><span>{formatClock(secs)}</span><span>{formatClock(total)}</span></div>
            </div>
          </div>
          {!isStudio && <div className="sp-secs" style={{ gridTemplateColumns: model.sections.map((s) => `${s.endTick - s.startTick}fr`).join(' ') }}>
            {model.sections.map((s, i) => <span key={s.id} className={i === curSection ? 'on' : ''}>{s.label}</span>)}
          </div>}
        </section>

        {shownLyrics.length > 0 && (
          <section aria-label="Lyrics" className="sp-lyrics">
            {shownLyrics.flatMap((g) => g.lines).map((l, i) => <p key={i} className={i === curLine ? 'now' : i < curLine ? 'past' : ''}>{l.text}</p>)}
          </section>
        )}

        {model.message && <section aria-label="Message" className="sp-msg-card"><p>{model.message}</p></section>}
        {model.card && <section aria-label="This card" className="sp-card"><img src={model.card} alt="The printed card" /></section>}

        <div className="sp-actions">
          <button type="button" className="sp-save" onClick={() => void save()} disabled={saving}>{saving ? 'Saving…' : 'Save this song'}</button>
          <button type="button" className="sp-share" onClick={() => void share()}>Share</button>
        </div>
        {note && <div className="sp-note" role="status">{note}</div>}
        <div className="sp-foot">FretCase</div>
      </div>
    </div>
  )
}
