import { useCallback, useEffect, useRef, useState } from 'react'
import { StepHeader } from '../App'
import { useApp, useSel } from '../app/context'
import { MAX_PHOTOS, type CapturedInput, type CaptureMode } from '../app/store'
import { MicRecorder } from '../lib/recorder'
import { PlayIcon } from './ui'

const MODES: { id: CaptureMode; label: string; sub: string }[] = [
  { id: 'photo', label: '拍照', sub: '红键短按' },
  { id: 'hum', label: '哼一段', sub: '红键按一下或按住' },
  { id: 'sound', label: '录声音', sub: '红键按一下或按住' },
  { id: 'text', label: '写一句', sub: '也可以说' },
]

/** Rear camera with a photo strip. Registers itself as the panel's photo source. */
function PhotoStage() {
  const { c } = useApp()
  const inputs = useSel((s) => s.inputs)
  const photos = inputs.filter((i) => i.kind === 'photo')
  const sel = useSel((s) => s.photoSel)
  const video = useRef<HTMLVideoElement>(null)
  const stream = useRef<MediaStream | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const [on, setOn] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const snap = useCallback(async (): Promise<Blob | null> => {
    const v = video.current
    if (!v || !v.videoWidth) return null
    const scale = Math.min(1, 1600 / v.videoWidth)
    const cv = document.createElement('canvas')
    cv.width = Math.round(v.videoWidth * scale)
    cv.height = Math.round(v.videoHeight * scale)
    cv.getContext('2d')!.drawImage(v, 0, 0, cv.width, cv.height)
    return new Promise((res) => cv.toBlob((b) => res(b), 'image/jpeg', 0.85))
  }, [])

  const stop = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    c.photoSource = null
    setOn(false)
  }, [c])

  const start = useCallback(async () => {
    setErr(null)
    if (!navigator.mediaDevices?.getUserMedia) { setErr('这个浏览器不能使用相机（需要 HTTPS）'); return }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 } }, audio: false })
      stream.current = s
      if (video.current) { video.current.srcObject = s; await video.current.play() }
      c.photoSource = snap
      setOn(true)
    } catch { setErr('不能使用相机，请检查权限') }
  }, [c, snap])

  // The camera opens by itself when the photo mode is shown.
  useEffect(() => { void start(); return stop }, [start, stop])

  const shown = photos.find((p) => p.id === sel) ?? photos[photos.length - 1]
  const full = photos.length >= MAX_PHOTOS
  return (
    <div className="stage photo">
      <video ref={video} playsInline muted className={on && !shown ? '' : 'hidden'} />
      {shown && <img src={shown.url} alt="刚拍的照片" className="stage-img" />}
      {!on && !shown && (
        <div className="stage-empty">
          <div className="stage-title">{err ?? '正在打开相机'}</div>
          <div className="row">
            <button type="button" className="bigbtn" onClick={() => void start()}>打开相机</button>
            <button type="button" className="bigbtn ghost" onClick={() => file.current?.click()}>从相册选一张</button>
          </div>
        </div>
      )}
      <input ref={file} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) c.addPhoto(f); e.target.value = '' }} />
      {(photos.length > 0 || on) && (
        <div className="stage-bar">
          {photos.length > 0 && (
            <span className="strip">
              {photos.map((p) => (
                <button key={p.id} type="button" aria-label="看这张照片" className={p.id === shown?.id ? 'on' : ''} onClick={() => c.selectPhoto(p.id)}><img src={p.url} alt="" /></button>
              ))}
            </span>
          )}
          <span className="count-pill">{photos.length} / {MAX_PHOTOS} 张{full ? ' · 已满' : ' · 按红键再拍'}</span>
          <span className="grow" />
          {shown && <button type="button" className="outline" onClick={() => c.retakePhoto()}>重拍</button>}
          {on && <button type="button" className="shutter" aria-label="拍一张" onClick={async () => { const b = await snap(); if (b) c.addPhoto(b) }} />}
          {!on && <button type="button" className="outline" onClick={() => file.current?.click()}>再选一张</button>}
        </div>
      )}
    </div>
  )
}

function HoldStage({ kind }: { kind: 'hum' | 'sound' }) {
  const { c } = useApp()
  const recording = useSel((s) => s.recording)
  const mine = recording === kind
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    if (!mine) { setSecs(0); return }
    const t0 = performance.now()
    const id = setInterval(() => setSecs((performance.now() - t0) / 1000), 100)
    return () => clearInterval(id)
  }, [mine])
  const heights = [10, 18, 30, 22, 40, 52, 34, 26, 44, 58, 48, 30, 20, 36, 50, 62, 44, 28, 18, 26, 38, 54, 46, 32, 22, 14, 24, 40, 56, 42, 30, 20, 34, 48, 36, 24, 16, 28, 20, 12]
  return (
    <div className="stage listen">
      <div className="stage-title">{kind === 'hum' ? '哼几句你脑子里的调子' : '录下周围的声音'}</div>
      <div className="stage-sub">{kind === 'hum' ? '不用歌词，啦啦啦就行，5 到 20 秒' : '海浪、街道、雨声都可以，10 秒左右'}；按住下面的圆钮，或按一下箱子上的红键开始、再按一下结束</div>
      <button
        type="button" aria-label="按住录音" className={`holdbtn ${mine ? 'rec' : ''}`} disabled={!!recording && !mine}
        onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); void c.startRecording(kind) }}
        onPointerUp={() => void c.stopRecording()} onPointerCancel={() => void c.stopRecording()} onContextMenu={(e) => e.preventDefault()}
      >{mine ? `${secs.toFixed(1)} 秒` : '按住'}</button>
      <div className={`wave ${mine ? 'live' : ''}`} aria-hidden="true">
        {heights.map((h, i) => <span key={i} style={{ height: h, animationDelay: `${(i % 7) * 70}ms` }} />)}
      </div>
      {!MicRecorder.supported() && <div className="stage-sub warn">这个浏览器不能录音（需要 HTTPS）</div>}
    </div>
  )
}

type SpeechCtor = new () => { lang: string; interimResults: boolean; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onend: (() => void) | null; onerror: (() => void) | null; start(): void; stop(): void }
const speechCtor = (): SpeechCtor | null => {
  const w = window as unknown as { SpeechRecognition?: SpeechCtor; webkitSpeechRecognition?: SpeechCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

function TextStage() {
  const { c } = useApp()
  const text = useSel((s) => s.inputs.find((i) => i.kind === 'text')?.text ?? '')
  const Speech = speechCtor()
  const rec = useRef<InstanceType<SpeechCtor> | null>(null)
  const [talking, setTalking] = useState(false)
  const startSpeech = () => {
    if (!Speech) return
    try {
      const r = new Speech()
      r.lang = 'zh-CN'; r.interimResults = false
      r.onresult = (e) => { const t = [...Array.from(e.results)].map((x) => x[0].transcript).join(''); if (t) c.setText(c.textValue() + t) }
      r.onend = () => setTalking(false)
      r.onerror = () => setTalking(false) // quietly: speech recognition often needs the network
      rec.current = r; setTalking(true); r.start()
    } catch { setTalking(false) }
  }
  return (
    <div className="stage textstage">
      <label htmlFor="words" className="stage-title left">写一句此刻的话</label>
      <textarea id="words" value={text} maxLength={500} placeholder="例如：海边的傍晚，风很大，有点想家" onChange={(e) => c.setText(e.target.value)} />
      {Speech && (
        <div className="row">
          <span className="muted">也可以对着箱子说出来</span>
          <button type="button" className={`pillbtn ${talking ? 'rec' : ''}`} onPointerDown={startSpeech} onPointerUp={() => rec.current?.stop()} onPointerCancel={() => rec.current?.stop()}>{talking ? '正在听…' : '按住说话'}</button>
        </div>
      )}
    </div>
  )
}

function Waveform({ color }: { color: string }) {
  return (
    <div className="item-icon" aria-hidden="true" style={{ background: '#3A2620' }}>
      {[18, 34, 24, 40, 16].map((h, i) => <span key={i} style={{ width: 4, height: h, borderRadius: 2, background: color, margin: '0 1.5px' }} />)}
    </div>
  )
}

function AudioItem({ i }: { i: CapturedInput }) {
  const { c } = useApp()
  const audio = useRef<HTMLAudioElement>(null)
  return (
    <div className="item">
      <Waveform color={i.kind === 'hum' ? '#E2725B' : '#86B068'} />
      <div className="item-text">
        <div className="item-title">{i.kind === 'hum' ? '哼唱' : '环境声'}</div>
        <div className="item-sub">{i.kind === 'hum' ? '这段会成为副歌的旋律' : '会垫在歌的底下'}</div>
      </div>
      <button type="button" className="roundbtn" aria-label="试听" onClick={() => void audio.current?.play()}><PlayIcon size={16} color="#F3E9DA" /></button>
      <button type="button" className="roundbtn" aria-label="去掉" onClick={() => c.removeInput(i.id)}>×</button>
      <audio ref={audio} src={i.url} hidden />
    </div>
  )
}

function Collected() {
  const { c } = useApp()
  const inputs = useSel((s) => s.inputs)
  const photos = inputs.filter((i) => i.kind === 'photo')
  const hums = inputs.filter((i) => i.kind === 'hum')
  const sounds = inputs.filter((i) => i.kind === 'sound')
  const text = inputs.find((i) => i.kind === 'text')
  return (
    <aside aria-label="已收集" className="collected">
      <div className="side-title">今天收集到的</div>
      <div className="side-sub">一样就够；不拍照，写一句话也行</div>
      {inputs.length === 0 && <div className="item dashed"><div className="item-icon dashed">+</div><div className="item-sub">还什么都没有</div></div>}
      {photos.length > 0 && (
        <div className="item">
          <div className="item-icon mosaic" aria-hidden="true">{photos.slice(0, 4).map((p) => <img key={p.id} src={p.url} alt="" />)}</div>
          <div className="item-text"><div className="item-title">照片 · {photos.length} 张</div><div className="item-sub">最多 {MAX_PHOTOS} 张；颜色会影响歌的气氛</div></div>
          <button type="button" className="roundbtn" aria-label="去掉全部照片" onClick={() => c.removeAllPhotos()}>×</button>
        </div>
      )}
      {hums.map((h) => <AudioItem key={h.id} i={h} />)}
      {text && (
        <div className="item">
          <div className="item-icon" aria-hidden="true" style={{ background: '#33291C', color: '#D4AE6A', fontFamily: 'var(--serif)', fontSize: 28 }}>字</div>
          <div className="item-text"><div className="item-title">一句话</div><div className="item-sub ellipsis">「{text.text}」</div></div>
          <button type="button" className="roundbtn" aria-label="去掉这句话" onClick={() => c.setText('')}>×</button>
        </div>
      )}
      {sounds.map((h) => <AudioItem key={h.id} i={h} />)}
      {sounds.length === 0 && (
        <button type="button" className="item dashed" onClick={() => c.setCaptureMode('sound')}>
          <div className="item-icon dashed">+</div><div className="item-sub">环境声（可选）：海浪、街道、雨声</div>
        </button>
      )}
    </aside>
  )
}

export function CaptureView() {
  const { c } = useApp()
  const mode = useSel((s) => s.captureMode)
  const inputs = useSel((s) => s.inputs)
  const songs = useSel((s) => s.recentSongs)
  const showSongs = useSel((s) => s.showSongs)
  return (
    <>
      <StepHeader />
      <main className="capture">
        <section aria-label="采集" className="capture-main">
          {mode === 'photo' && <PhotoStage />}
          {(mode === 'hum' || mode === 'sound') && <HoldStage kind={mode} key={mode} />}
          {mode === 'text' && <TextStage />}
          <div role="tablist" aria-label="采集方式" className="modes">
            {MODES.map((m) => (
              <button key={m.id} type="button" role="tab" aria-selected={m.id === mode} className={m.id === mode ? 'on' : ''} onClick={() => c.setCaptureMode(m.id)}>
                <span>{m.label}</span><small>{m.sub}</small>
              </button>
            ))}
          </div>
        </section>
        <div className="capture-side">
          <Collected />
          <div className="make">
            <button type="button" className="gobtn" disabled={!inputs.length} onClick={() => void c.makeSong()}>做成歌</button>
            <div className="muted center">约 10 秒，会给你三首挑</div>
          </div>
        </div>
      </main>
      <footer className="footbar">
        <span>箱子上：</span><span>红键 按上面选的方式采集</span><span>撤销键 退回上一步</span>
        {songs.length > 0 && <button type="button" className="linkbtn right" onClick={() => c.store.set({ showSongs: !showSongs })}>打开以前的歌</button>}
        {showSongs && (
          <div className="songs-pop" role="menu">
            {songs.map((s) => <button key={s.id} type="button" role="menuitem" onClick={() => void c.openSong(s.id)}>{s.title}</button>)}
          </div>
        )}
      </footer>
    </>
  )
}
