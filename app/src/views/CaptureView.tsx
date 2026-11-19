import { useCallback, useEffect, useRef, useState } from 'react'
import { useApp, useSel } from '../app/context'
import { MicRecorder } from '../lib/recorder'
import { SeedEditor } from './SeedEditor'

/** Rear camera preview that can take a still photo. Registers itself as the panel's photo source. */
function Camera() {
  const { c } = useApp()
  const video = useRef<HTMLVideoElement>(null)
  const stream = useRef<MediaStream | null>(null)
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

  const start = async () => {
    setErr(null)
    if (!navigator.mediaDevices?.getUserMedia) { setErr('这个浏览器不能使用相机（需要 HTTPS）'); return }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 } }, audio: false })
      stream.current = s
      if (video.current) { video.current.srcObject = s; await video.current.play() }
      c.photoSource = snap
      setOn(true)
    } catch {
      setErr('不能使用相机，请检查权限')
    }
  }
  useEffect(() => stop, [stop])

  return (
    <div className="card-panel camera">
      <div className="viewfinder">
        <video ref={video} playsInline muted />
        {!on && <div className="vf-empty">{err ?? '相机没有打开'}</div>}
      </div>
      <div className="row">
        {!on ? <button className="btn" onClick={() => void start()}>打开后置相机</button> : (
          <>
            <button className="btn primary" onClick={async () => { const b = await snap(); if (b) await c.addPhoto(b) }}>拍照</button>
            <button className="btn ghost" onClick={stop}>关闭相机</button>
          </>
        )}
      </div>
    </div>
  )
}

/** Press and hold to record; release to keep. Works with touch and mouse. */
function HoldToRecord({ kind, label, hint }: { kind: 'hum' | 'sound'; label: string; hint: string }) {
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
  return (
    <div className="hold-wrap">
      <button
        className={`hold ${kind} ${mine ? 'rec' : ''}`}
        disabled={!!recording && !mine}
        onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); void c.startRecording(kind) }}
        onPointerUp={() => void c.stopRecording()}
        onPointerCancel={() => void c.stopRecording()}
        onContextMenu={(e) => e.preventDefault()}
      >
        <span className="hold-dot" />
        <span>{mine ? `录音中 ${secs.toFixed(1)} 秒` : label}</span>
      </button>
      <div className="hint">{hint}</div>
      {!MicRecorder.supported() && <div className="hint warn">这个浏览器不能录音（需要 HTTPS）</div>}
    </div>
  )
}

export function CaptureView() {
  const { c } = useApp()
  const inputs = useSel((s) => s.inputs)
  const seed = useSel((s) => s.seed)
  const recent = useSel((s) => s.recentSongs)
  const [text, setText] = useState('')

  if (seed) return <SeedEditor />

  return (
    <div className="capture">
      <section className="col">
        <h2>看一看</h2>
        <Camera />
      </section>
      <section className="col">
        <h2>哼一哼，听一听</h2>
        <HoldToRecord kind="hum" label="按住哼唱" hint="按住红色按钮哼几小节，松开就停" />
        <HoldToRecord kind="sound" label="按住录环境声" hint="海浪、街道、雨声，十秒左右" />
        <h2>写一句话</h2>
        <div className="card-panel">
          <textarea className="text" rows={3} placeholder="例如：傍晚的海边，风有一点凉" value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
          <div className="row"><button className="btn" disabled={!text.trim()} onClick={() => { c.addText(text); setText('') }}>加入</button></div>
        </div>
      </section>
      <section className="col">
        <h2>已经有了</h2>
        <div className="card-panel inputs">
          {inputs.length === 0 && <div className="empty">还没有内容。哼一段、拍一张或写一句话都可以。</div>}
          {inputs.map((i) => (
            <div key={i.id} className="input-item">
              <span className="kind">{{ hum: '哼唱', sound: '环境声', photo: '照片', text: '文字' }[i.kind]}</span>
              {i.kind === 'photo' && i.url && <img src={i.url} alt="" />}
              {(i.kind === 'hum' || i.kind === 'sound') && i.url && <audio controls src={i.url} />}
              {i.kind === 'text' && <span className="txt">{i.text}</span>}
              <button className="btn small ghost" onClick={() => c.removeInput(i.id)}>去掉</button>
            </div>
          ))}
        </div>
        <button className="btn primary big" disabled={!inputs.length} onClick={() => void c.makeSeed()}>生成种子卡</button>
        {recent.length > 0 && (
          <>
            <h3>本机的歌</h3>
            <div className="recent">
              {recent.map((r) => <button key={r.id} className="btn ghost small" onClick={() => void c.openSong(r.id)}>{r.title}</button>)}
            </div>
          </>
        )}
      </section>
    </div>
  )
}
