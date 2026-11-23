import { useEffect, useRef, useState } from 'react'
import jsQR from 'jsqr'
import { useApp } from '../app/context'

type Detector = { detect(src: CanvasImageSource): Promise<{ rawValue: string }[]> }

/** Front camera QR scan: BarcodeDetector where it exists (Safari 17+ on iPad does not always have it), jsQR otherwise. */
export function ScanOverlay() {
  const { c } = useApp()
  const video = useRef<HTMLVideoElement>(null)
  const [err, setErr] = useState<string | null>(null)
  const [manual, setManual] = useState('')
  const [engine, setEngine] = useState('')

  useEffect(() => {
    let stop = false
    let stream: MediaStream | null = null
    let timer = 0
    let busy = false
    const BD = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => Detector }).BarcodeDetector
    const detector = BD ? new BD({ formats: ['qr_code'] }) : null
    setEngine(detector ? 'BarcodeDetector' : 'jsQR')
    const canvas = document.createElement('canvas')

    const loop = async () => {
      if (stop) return
      const v = video.current
      if (v && v.readyState >= 2 && !busy) {
        busy = true
        try {
          let text: string | null = null
          if (detector) {
            const r = await detector.detect(v)
            text = r[0]?.rawValue ?? null
          } else {
            const w = Math.min(640, v.videoWidth), h = Math.round((w / v.videoWidth) * v.videoHeight)
            canvas.width = w; canvas.height = h
            const ctx = canvas.getContext('2d', { willReadFrequently: true })!
            ctx.drawImage(v, 0, 0, w, h)
            text = jsQR(ctx.getImageData(0, 0, w, h).data, w, h)?.data ?? null
          }
          if (text) {
            const ours = await c.handleScan(text)
            if (ours) return
            c.toast('This is not a FretCase card', 'info')
            await new Promise((r) => setTimeout(r, 1500))
          }
        } catch { /* a frame that cannot be read is skipped */ }
        busy = false
      }
      timer = window.setTimeout(loop, 200)
    }

    ;(async () => {
      if (!navigator.mediaDevices?.getUserMedia) { setErr('This browser cannot use the camera (it needs HTTPS)'); return }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false })
        if (stop) { stream.getTracks().forEach((t) => t.stop()); return }
        if (video.current) { video.current.srcObject = stream; await video.current.play() }
        loop()
      } catch { setErr('Cannot use the front camera. Check the permission, or type the card address below') }
    })()

    return () => { stop = true; clearTimeout(timer); stream?.getTracks().forEach((t) => t.stop()) }
  }, [c])

  return (
    <div className="overlay">
      <div className="scan">
        <h2>Hold the QR code on the card up to the camera above the screen</h2>
        <div className="viewfinder scanvf">
          <video ref={video} playsInline muted />
          {err && <div className="vf-empty">{err}</div>}
          <div className="reticle" />
        </div>
        <div className="hint" hidden={!engine}>{engine ? "" : ""}</div>
        <form className="row" onSubmit={async (e) => { e.preventDefault(); if (!(await c.handleScan(manual))) c.toast('That address is wrong. It should look like https://…/s/xxxxxxxxxx', 'info') }}>
          <input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="Or type the address on the card" />
          <button className="btn small" disabled={!manual.trim()}>Load</button>
        </form>
        <button className="btn ghost" onClick={() => c.store.set({ scanning: false })}>Close</button>
      </div>
    </div>
  )
}
