/** 16-bit PCM WAV file from an AudioBuffer. */
export function encodeWav(buf: AudioBuffer): Blob {
  const ch = buf.numberOfChannels, len = buf.length, rate = buf.sampleRate
  const data = new DataView(new ArrayBuffer(44 + len * ch * 2))
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) data.setUint8(o + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); data.setUint32(4, 36 + len * ch * 2, true); str(8, 'WAVE'); str(12, 'fmt ')
  data.setUint32(16, 16, true); data.setUint16(20, 1, true); data.setUint16(22, ch, true)
  data.setUint32(24, rate, true); data.setUint32(28, rate * ch * 2, true); data.setUint16(32, ch * 2, true); data.setUint16(34, 16, true)
  str(36, 'data'); data.setUint32(40, len * ch * 2, true)
  const chans = Array.from({ length: ch }, (_, i) => buf.getChannelData(i))
  let o = 44
  for (let i = 0; i < len; i++) for (let c = 0; c < ch; c++) {
    const v = Math.max(-1, Math.min(1, chans[c][i]))
    data.setInt16(o, v < 0 ? v * 0x8000 : v * 0x7fff, true); o += 2
  }
  return new Blob([data], { type: 'audio/wav' })
}

/** A recording without its first `seconds`, as a WAV file; null when this browser cannot decode it. */
export async function trimStart(blob: Blob, seconds: number): Promise<Blob | null> {
  try {
    if (typeof OfflineAudioContext === 'undefined') return null
    const src = await new OfflineAudioContext(1, 1, 44100).decodeAudioData(await blob.arrayBuffer())
    const from = Math.min(src.length - 1, Math.max(0, Math.round(seconds * src.sampleRate)))
    const out = new AudioBuffer({ length: src.length - from, numberOfChannels: src.numberOfChannels, sampleRate: src.sampleRate })
    for (let ch = 0; ch < src.numberOfChannels; ch++) out.copyToChannel(src.getChannelData(ch).subarray(from), ch)
    return encodeWav(out)
  } catch { return null }
}
