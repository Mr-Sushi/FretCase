import type { Catalog, SeedCard, SeedInput, SharePage, Song, TrackId } from '../types'
import { ApiError, type Api, type AssetRole, type CandidateRequest, type EditOp, type Health, type LyricsAlternative, type LyricsRequest, type LyricsRewriteRequest, type LyricsTheme, type PrinterStatus, type SongListItem } from './types'

const TIMEOUT_MS = 8000

/** Client for docs/api.md. Every call has a timeout; failures surface as ApiError. */
export class HttpApi implements Api {
  readonly mock = false
  constructor(private base = '') {}

  private async request<T>(method: string, path: string, body?: unknown, form?: FormData, timeout = TIMEOUT_MS): Promise<T> {
    const ctl = new AbortController()
    const timer = setTimeout(() => ctl.abort(), timeout)
    try {
      const res = await fetch(this.base + path, {
        method,
        signal: ctl.signal,
        headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
        body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
      })
      const text = await res.text()
      let json: any = {}
      try { json = text ? JSON.parse(text) : {} } catch {
        // A plain-text or HTML body (a crash page, a proxy error) still means the server answered.
        throw new ApiError('http_error', `服务器出错（${res.status}）`, res.status)
      }
      if (!res.ok) {
        const e = json.error ?? {}
        throw new ApiError(e.code ?? 'http_error', e.message ?? `HTTP ${res.status}`, res.status, e.song, e.detail)
      }
      return json as T
    } catch (e) {
      if (e instanceof ApiError) throw e
      if ((e as Error).name === 'AbortError') throw new ApiError('timeout', '服务器没有响应', 0)
      throw new ApiError('network', '连不上服务器', 0)
    } finally {
      clearTimeout(timer)
    }
  }

  health() { return this.request<Health>('GET', '/health', undefined, undefined, 3000) }
  catalog() { return this.request<Catalog>('GET', '/api/catalog') }
  async uploadAsset(file: Blob, role: AssetRole) {
    const form = new FormData()
    form.append('file', file, role === 'photo' ? 'photo.jpg' : 'recording.webm')
    form.append('role', role)
    return (await this.request<{ asset: { id: string; role: string; mime: string; durationSec?: number } }>('POST', '/api/assets', undefined, form, 30000)).asset
  }
  assetUrl(id: string) { return `${this.base}/api/assets/${id}` }
  async createSeed(inputs: SeedInput[]) { return (await this.request<{ seed: SeedCard }>('POST', '/api/seed', { inputs }, undefined, 60000)).seed }
  async candidates(seed: SeedCard, req: CandidateRequest = {}) {
    return (await this.request<{ candidates: Song[] }>('POST', '/api/candidates', { seed, ...req }, undefined, 60000)).candidates
  }
  async choose(id: string) { return (await this.request<{ song: Song }>('POST', `/api/songs/${id}/choose`, {}, undefined, 30000)).song }
  async listSongs() { return (await this.request<{ songs: SongListItem[] }>('GET', '/api/songs')).songs }
  async getSong(id: string) { return (await this.request<{ song: Song }>('GET', `/api/songs/${id}`)).song }
  async edit(id: string, baseRevision: number, ops: EditOp[]) {
    return (await this.request<{ song: Song }>('POST', `/api/songs/${id}/edits`, { baseRevision, ops }, undefined, 30000)).song
  }
  async another(id: string, baseRevision: number, section: string, track?: TrackId) {
    return (await this.request<{ song: Song }>('POST', `/api/songs/${id}/another`, track ? { baseRevision, section, track } : { baseRevision, section }, undefined, 30000)).song
  }
  async rehum(id: string, baseRevision: number, section: string, assetId: string) {
    return (await this.request<{ song: Song }>('POST', `/api/songs/${id}/rehum`, { baseRevision, section, assetId }, undefined, 60000)).song
  }
  async undo(id: string, baseRevision: number) { return (await this.request<{ song: Song }>('POST', `/api/songs/${id}/undo`, { baseRevision })).song }
  async cardPreview(id: string, baseRevision: number) { return (await this.request<{ song: Song }>('POST', `/api/songs/${id}/card/preview`, { baseRevision }, undefined, 30000)).song }
  async cardPrint(id: string, baseRevision: number) { return (await this.request<{ song: Song }>('POST', `/api/songs/${id}/card/print`, { baseRevision }, undefined, 90000)).song }
  async lyricsRewrite(id: string, baseRevision: number, req: LyricsRewriteRequest) {
    return (await this.request<{ song: Song }>('POST', `/api/songs/${id}/lyrics`, { baseRevision, ...req }, undefined, 25000)).song
  }
  async lyricsAlternatives(id: string, req: LyricsRequest & { section: string; line: number }) {
    return (await this.request<{ alternatives: LyricsAlternative[] }>('POST', `/api/songs/${id}/lyrics/alternatives`, req, undefined, 25000)).alternatives
  }
  async lyricsThemes(id: string) { return (await this.request<{ themes: LyricsTheme[] }>('GET', `/api/songs/${id}/lyrics/themes`)).themes }
  // A Bluetooth printer check can take several seconds on the Pi.
  async printer() { return (await this.request<{ printer: PrinterStatus }>('GET', '/api/printer', undefined, undefined, 15000)).printer }
  sharePage(shareId: string) { return this.request<{ page: SharePage; song: Song }>('GET', `/api/share/${encodeURIComponent(shareId)}/page`) }
  async resolveShare(shareId: string) { return (await this.request<{ songId: string }>('GET', `/api/share/${encodeURIComponent(shareId)}`)).songId }
  getLocation() { return this.request<{ city: string | null; source: 'gps' | 'manual' | 'none' }>('GET', '/api/location') }
  async putLocation(city: string) { await this.request('PUT', '/api/location', { city }) }
  async studyLog(events: { at: string; type: string; detail?: unknown }[]) { await this.request('POST', '/api/study/log', { events }) }
}
