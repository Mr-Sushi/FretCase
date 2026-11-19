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
    if (!shareId) { setLoad({ state: 'error', text: '这个链接不完整，请重新扫一次卡片上的二维码。' }); return }
    api.sharePage(shareId).then(
      (r) => setLoad({ state: 'ready', page: r.page, song: r.song }),
      (e) => setLoad({ state: 'error', text: e instanceof ApiError && e.status === 404 ? '找不到这首歌。它可能还没有分享出来。' : '现在打不开这首歌，请稍后再试。' }),
    )
  }, [api, shareId])
  if (load.state === 'loading') return <div className="sp-wrap"><div className="sp-msg">正在打开…</div></div>
  if (load.state === 'error') return <div className="sp-wrap"><div className="sp-msg">{load.text}</div></div>
  return <Ready page={load.page} song={load.song} shareId={shareId!} assetUrl={(id) => (mock ? api.assetUrl(id) : `/api/share/${encodeURIComponent(shareId!)}/assets/${encodeURIComponent(id)}`)} />
}

function Ready({ page, song, shareId, assetUrl }: { page: SharePage; song: Song; shareId: string; assetUrl: (id: string) => string }) {
  const model: PageModel = useMemo(() => buildModel(page, song), [page, song])
  const [tick, setTick] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [photo, setPhoto] = useState(0)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')
  const engine = useRef<PlaybackEngine | null>(null)
  useEffect(() => {
    const e = new PlaybackEngine(assetUrl, { onPosition: setTick, onEnd: () => setPlaying(false) })
    engine.current = e
    void e.load(song)
    return () => e.dispose()
  }, [song, assetUrl])

  const total = songSeconds(song)
  const secs = ticksToSeconds(tick, song.tempo)
  const toggle = async () => {
    const e = engine.current
    if (!e) return
    if (playing) { e.stop(); setPlaying(false) } else { await e.play(); setPlaying(true) }
  }
  const seek = (frac: number) => { engine.current?.seek(Math.round(frac * (total / 60) * song.tempo * 480)) }
  const curLine = currentLineIndex(model, tick)
  const curSection = currentSectionIndex(model, tick)
  const flash = (t: string) => { setNote(t); setTimeout(() => setNote(''), 3000) }

  const save = async () => {
    if (saving) return
    setSaving(true)
    try {
      const wav = encodeWav(await renderSong(song, assetUrl))
      const a = document.createElement('a')
      a.href = URL.createObjectURL(wav)
      a.download = `${model.title || 'FretCase'}.wav`
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(a.href), 10000)
      flash('已保存，在“下载”里可以找到')
    } catch { flash('保存没有成功，请再试一次') } finally { setSaving(false) }
  }
  const share = async () => {
    const link = location.href
    try {
      if (navigator.share) await navigator.share({ title: model.title, text: model.line ?? model.title, url: link })
      else { await navigator.clipboard.writeText(link); flash('链接已复制') }
    } catch (e) { if ((e as Error).name !== 'AbortError') flash('转发没有成功') }
  }

  return (
    <div className="sp-wrap">
      <div className="sp">
        {model.photos.length > 0 && (
          <>
            <img className="sp-hero" src={model.photos[photo] ?? model.photos[0]} alt="写歌时拍下的照片" />
            {model.photos.length > 1 && (
              <div role="group" aria-label="写歌时拍的照片" className="sp-thumbs">
                {model.photos.map((p, i) => (
                  <button key={p} type="button" aria-label={`看第 ${i + 1} 张`} aria-pressed={i === photo} className={i === photo ? 'on' : ''} onClick={() => setPhoto(i)}><img src={p} alt="" /></button>
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

        <section aria-label="播放" className="sp-player">
          <div className="sp-row">
            <button type="button" className="sp-play" aria-label={playing ? '暂停' : '播放'} onClick={() => void toggle()}>
              {playing ? <svg width="20" height="20" viewBox="0 0 18 18" aria-hidden="true"><rect x="3" y="2" width="4" height="14" fill="#1C1410" /><rect x="11" y="2" width="4" height="14" fill="#1C1410" /></svg>
                : <svg width="20" height="20" viewBox="0 0 18 18" aria-hidden="true"><path d="M4 2l12 7-12 7z" fill="#1C1410" /></svg>}
            </button>
            <div className="sp-grow">
              <div className="sp-bar" onPointerDown={(e) => { const r = e.currentTarget.getBoundingClientRect(); seek((e.clientX - r.left) / r.width) }}><div style={{ width: `${Math.min(100, (secs / total) * 100)}%` }} /></div>
              <div className="sp-times"><span>{formatClock(secs)}</span><span>{formatClock(total)}</span></div>
            </div>
          </div>
          <div className="sp-secs" style={{ gridTemplateColumns: model.sections.map((s) => `${s.endTick - s.startTick}fr`).join(' ') }}>
            {model.sections.map((s, i) => <span key={s.id} className={i === curSection ? 'on' : ''}>{s.label}</span>)}
          </div>
        </section>

        {model.lyrics.length > 0 && (
          <section aria-label="歌词" className="sp-lyrics">
            {model.lyrics.flatMap((g) => g.lines).map((l, i) => <p key={i} className={i === curLine ? 'now' : i < curLine ? 'past' : ''}>{l.text}</p>)}
          </section>
        )}

        {model.message && <section aria-label="留言" className="sp-msg-card"><p>{model.message}</p></section>}
        {model.card && <section aria-label="这张卡片" className="sp-card"><img src={model.card} alt="印出来的卡片" /></section>}

        <div className="sp-actions">
          <button type="button" className="sp-save" onClick={() => void save()} disabled={saving}>{saving ? '正在保存…' : '保存这首歌'}</button>
          <button type="button" className="sp-share" onClick={() => void share()}>转给别人</button>
        </div>
        {note && <div className="sp-note" role="status">{note}</div>}
        <div className="sp-foot">FretCase</div>
      </div>
    </div>
  )
}
