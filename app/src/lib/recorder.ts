/** Hold-to-record microphone capture. Safari records audio/mp4, other browsers audio/webm. */
export class MicRecorder {
  private rec: MediaRecorder | null = null
  private stream: MediaStream | null = null
  private chunks: Blob[] = []
  private startedAt = 0

  static supported() { return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined' }

  get active() { return this.rec?.state === 'recording' }

  async start(): Promise<void> {
    if (this.active) return
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } })
    const mime = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm'].find((m) => MediaRecorder.isTypeSupported(m))
    this.chunks = []
    this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined)
    this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data) }
    this.startedAt = performance.now()
    this.rec.start()
  }

  /** Resolves with the recording, or null if it was shorter than minMs (an accidental tap). */
  stop(minMs = 500): Promise<Blob | null> {
    return new Promise((resolve) => {
      const rec = this.rec
      if (!rec || rec.state === 'inactive') { resolve(null); return }
      const ms = performance.now() - this.startedAt
      rec.onstop = () => {
        this.stream?.getTracks().forEach((t) => t.stop())
        const blob = new Blob(this.chunks, { type: rec.mimeType || 'audio/webm' })
        this.rec = null; this.stream = null; this.chunks = []
        resolve(ms < minMs ? null : blob)
      }
      rec.stop()
    })
  }
}
