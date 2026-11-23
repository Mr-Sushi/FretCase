import { useCallback, useEffect, useRef, useState } from 'react'
import { StepHeader } from '../App'
import { useApp, useSel } from '../app/context'
import { MAX_PHOTOS, type CapturedInput, type CaptureMode } from '../app/store'
import { MicRecorder } from '../lib/recorder'
import { PlayIcon } from './ui'

const MODES: { id: CaptureMode; label: string; sub: string }[] = [
  { id: 'photo', label: 'Photo', sub: 'Press the red key' },
  { id: 'hum', label: 'Hum', sub: 'Press or hold the red key' },
  { id: 'sound', label: 'Sound', sub: 'Press or hold the red key' },
  { id: 'text', label: 'Write', sub: 'or say it' },
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
    if (!navigator.mediaDevices?.getUserMedia) { setErr('This browser cannot use the camera (it needs HTTPS)'); return }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 } }, audio: false })
      stream.current = s
      if (video.current) { video.current.srcObject = s; await video.current.play() }
      c.photoSource = snap
      setOn(true)
    } catch { setErr('Cannot use the camera. Please check the permission') }
  }, [c, snap])

  // The camera opens by itself when the photo mode is shown.
  useEffect(() => { void start(); return stop }, [start, stop])

  const shown = photos.find((p) => p.id === sel) ?? photos[photos.length - 1]
  const full = photos.length >= MAX_PHOTOS
  return (
    <div className="stage photo">
      <video ref={video} playsInline muted className={on && !shown ? '' : 'hidden'} />
      {shown && <img src={shown.url} alt="The photo just taken" className="stage-img" />}
      {!on && !shown && (
        <div className="stage-empty">
          <div className="stage-title">{err ?? 'Turning on the camera'}</div>
          <div className="row">
            <button type="button" className="bigbtn" onClick={() => void start()}>Turn on camera</button>
            <button type="button" className="bigbtn ghost" onClick={() => file.current?.click()}>Choose from photos</button>
          </div>
        </div>
      )}
      <input ref={file} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) c.addPhoto(f); e.target.value = '' }} />
      {(photos.length > 0 || on) && (
        <div className="stage-bar">
          {photos.length > 0 && (
            <span className="strip">
              {photos.map((p) => (
                <button key={p.id} type="button" aria-label="See this photo" className={p.id === shown?.id ? 'on' : ''} onClick={() => c.selectPhoto(p.id)}><img src={p.url} alt="" /></button>
              ))}
            </span>
          )}
          <span className="count-pill">{photos.length} / {MAX_PHOTOS} photos{full ? ' · full' : photos.length ? ' · press the red key for another' : ' · press the red key to take one'}</span>
          <span className="grow" />
          {shown && <button type="button" className="outline" onClick={() => c.retakePhoto()}>Retake</button>}
          {on && <button type="button" className="shutter" aria-label="Take a photo" onClick={async () => { const b = await snap(); if (b) c.addPhoto(b) }} />}
          {!on && <button type="button" className="outline" onClick={() => file.current?.click()}>Choose another</button>}
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
      <div className="stage-title">{kind === 'hum' ? 'Hum the tune in your head' : 'Record the sounds around you'}</div>
      <div className="stage-sub">{kind === 'hum' ? 'No words needed, la la la is fine, 5 to 20 seconds' : 'Waves, a street, rain, anything, about 10 seconds'}. Hold the round button below, or press the red key on the case to start and again to stop</div>
      <button
        type="button" aria-label="Hold to record" className={`holdbtn ${mine ? 'rec' : ''}`} disabled={!!recording && !mine}
        onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); void c.startRecording(kind) }}
        onPointerUp={() => void c.stopRecording()} onPointerCancel={() => void c.stopRecording()} onContextMenu={(e) => e.preventDefault()}
      >{mine ? `${secs.toFixed(1)} s` : 'Hold'}</button>
      <div className={`wave ${mine ? 'live' : ''}`} aria-hidden="true">
        {heights.map((h, i) => <span key={i} style={{ height: h, animationDelay: `${(i % 7) * 70}ms` }} />)}
      </div>
      {!MicRecorder.supported() && <div className="stage-sub warn">This browser cannot record (it needs HTTPS)</div>}
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
      r.lang = 'en-GB'; r.interimResults = false
      r.onresult = (e) => { const t = [...Array.from(e.results)].map((x) => x[0].transcript).join(''); if (t) c.setText(c.textValue() + t) }
      r.onend = () => setTalking(false)
      r.onerror = () => setTalking(false) // quietly: speech recognition often needs the network
      rec.current = r; setTalking(true); r.start()
    } catch { setTalking(false) }
  }
  return (
    <div className="stage textstage">
      <label htmlFor="words" className="stage-title left">Write a line about this moment</label>
      <textarea id="words" value={text} maxLength={500} placeholder="For example: seaside at dusk, very windy, a little homesick" onChange={(e) => c.setText(e.target.value)} />
      {Speech && (
        <div className="row">
          <span className="muted">Or say it to the case</span>
          <button type="button" className={`pillbtn ${talking ? 'rec' : ''}`} onPointerDown={startSpeech} onPointerUp={() => rec.current?.stop()} onPointerCancel={() => rec.current?.stop()}>{talking ? 'Listening…' : 'Hold to speak'}</button>
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
        <div className="item-title">{i.kind === 'hum' ? 'Hum' : 'Sound'}</div>
        <div className="item-sub">{i.kind === 'hum' ? 'This becomes the tune of the chorus' : 'This plays underneath the song'}</div>
      </div>
      <button type="button" className="roundbtn" aria-label="Listen" onClick={() => void audio.current?.play()}><PlayIcon size={16} color="#F3E9DA" /></button>
      <button type="button" className="roundbtn" aria-label="Remove" onClick={() => c.removeInput(i.id)}>×</button>
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
    <aside aria-label="Collected" className="collected">
      <div className="side-title">Collected today</div>
      <div className="side-sub">One thing is enough; a line of words will do</div>
      {inputs.length === 0 && <div className="item dashed"><div className="item-icon dashed">+</div><div className="item-sub">Nothing yet</div></div>}
      {photos.length > 0 && (
        <div className="item">
          <div className="item-icon mosaic" aria-hidden="true">{photos.slice(0, 4).map((p) => <img key={p.id} src={p.url} alt="" />)}</div>
          <div className="item-text"><div className="item-title">Photos · {photos.length}</div><div className="item-sub">Up to {MAX_PHOTOS}; their colours set the mood</div></div>
          <button type="button" className="roundbtn" aria-label="Remove all photos" onClick={() => c.removeAllPhotos()}>×</button>
        </div>
      )}
      {hums.map((h) => <AudioItem key={h.id} i={h} />)}
      {text && (
        <div className="item">
          <div className="item-icon" aria-hidden="true" style={{ background: '#33291C', color: '#D4AE6A', fontFamily: 'var(--serif)', fontSize: 28 }}>Aa</div>
          <div className="item-text"><div className="item-title">A line</div><div className="item-sub ellipsis">“{text.text}”</div></div>
          <button type="button" className="roundbtn" aria-label="Remove this line" onClick={() => c.setText('')}>×</button>
        </div>
      )}
      {sounds.map((h) => <AudioItem key={h.id} i={h} />)}
      {sounds.length === 0 && (
        <button type="button" className="item dashed" onClick={() => c.setCaptureMode('sound')}>
          <div className="item-icon dashed">+</div><div className="item-sub">Sound (optional): waves, a street, rain</div>
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
        <section aria-label="Capture" className="capture-main">
          {mode === 'photo' && <PhotoStage />}
          {(mode === 'hum' || mode === 'sound') && <HoldStage kind={mode} key={mode} />}
          {mode === 'text' && <TextStage />}
          <div role="tablist" aria-label="How to capture" className="modes">
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
            <button type="button" className="gobtn" disabled={!inputs.length} onClick={() => void c.makeSong()}>Make songs</button>
            <div className="muted center">About 10 seconds, then three to choose from</div>
          </div>
        </div>
      </main>
      <footer className="footbar">
        <span>On the case:</span><span>red key captures as chosen above</span><span>undo key goes back a step</span>
        {songs.length > 0 && <button type="button" className="linkbtn right" onClick={() => c.store.set({ showSongs: !showSongs })}>Open earlier songs</button>}
        {showSongs && (
          <div className="songs-pop" role="menu">
            {songs.map((s) => <button key={s.id} type="button" role="menuitem" onClick={() => void c.openSong(s.id)}>{s.title}</button>)}
          </div>
        )}
      </footer>
    </>
  )
}
