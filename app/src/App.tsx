import { useEffect, useMemo } from 'react'
import { createApi } from './api'
import { PlaybackEngine } from './audio/engine'
import { AppContext, useSel } from './app/context'
import { Controller } from './app/controller'
import { Store, initialState, type View } from './app/store'
import { PanelClient, panelUrl } from './panel/client'
import { CaptureView } from './views/CaptureView'
import { SongView } from './views/SongView'
import { TrackEditView } from './views/TrackEditView'
import { CardView } from './views/CardView'
import { ScanOverlay } from './views/ScanOverlay'
import { TRACKS } from './lib/song'
import { useApp } from './app/context'

const TABS: { id: View; label: string }[] = [
  { id: 'capture', label: '采集' },
  { id: 'song', label: '整首歌' },
  { id: 'track', label: '单轨' },
  { id: 'card', label: '卡片' },
]

export function App() {
  const world = useMemo(() => {
    const api = createApi()
    const store = new Store(initialState(api.mock))
    let ctl: Controller
    const engine = new PlaybackEngine((id) => api.assetUrl(id), {
      onPosition: (t) => ctl.onPosition(t),
      onEnd: () => ctl.onPlaybackEnd(),
      onLoadError: (id) => ctl.log('audio.load_error', id),
    })
    ctl = new Controller(api, store, engine)
    return { api, store, c: ctl, engine }
  }, [])

  useEffect(() => {
    const { c, api } = world
    void c.init()
    // Mock mode runs on its own; a panel socket is only opened there when ?panel=ws://... is given.
    const wantPanel = !api.mock || new URLSearchParams(location.search).has('panel')
    let panel: PanelClient | null = null
    if (wantPanel) {
      panel = new PanelClient(panelUrl(), (m) => c.onPanelMessage(m), (s) => c.onPanelStatus(s))
      c.panel = panel
      panel.start()
    }
    const health = setInterval(() => void c.refreshHealth(), 10000)
    return () => { clearInterval(health); panel?.stop(); c.dispose(); world.engine.dispose() }
  }, [world])

  return (
    <AppContext.Provider value={{ c: world.c, store: world.store }}>
      <Shell />
    </AppContext.Provider>
  )
}

function Shell() {
  const { c } = useApp()
  const view = useSel((s) => s.view)
  const song = useSel((s) => s.song)
  const playing = useSel((s) => s.playing)
  const busy = useSel((s) => s.busy)
  const toast = useSel((s) => s.toast)
  const server = useSel((s) => s.serverOnline)
  const net = useSel((s) => s.netOnline)
  const panel = useSel((s) => s.panelConnected)
  const attached = useSel((s) => s.panelAttached)
  const mock = useSel((s) => s.mock)
  const scanning = useSel((s) => s.scanning)

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">FretCase</div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button key={t.id} className={`tab ${view === t.id ? 'on' : ''}`} onClick={() => (t.id === 'track' ? song && c.editTrack(c_selected(c), undefined) : c.setView(t.id))}>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="grow song-name">{song ? song.title : ''}</div>
        <div className="status">
          {mock && <span className="chip mockchip">演示模式</span>}
          <span className={`chip ${server ? 'ok' : server === false ? 'bad' : ''}`}>{server ? '服务器已连接' : server === false ? '服务器未连接' : '连接中'}</span>
          <span className={`chip ${panel ? 'ok' : ''}`}>{panel ? '面板已连接' : attached ? '等待面板' : '无面板'}</span>
          <span className={`chip ${net ? 'ok' : ''}`}>{net ? '在线' : '离线'}</span>
        </div>
        <button className="btn ghost" onClick={() => c.store.set({ scanning: !scanning })}>扫卡片</button>
        <button className={`btn play ${playing ? 'on' : ''}`} disabled={!song} onClick={() => void c.togglePlay()}>{playing ? '暂停' : '播放'}</button>
      </header>
      <main className="main">
        {view === 'capture' && <CaptureView />}
        {view === 'song' && <SongView />}
        {view === 'track' && <TrackEditView />}
        {view === 'card' && <CardView />}
        {scanning && <ScanOverlay />}
      </main>
      {busy && <div className="busy"><span className="spinner" />{busy}</div>}
      {toast && <div className={`toast ${toast.kind}`} key={toast.id}>{toast.text}</div>}
    </div>
  )
}

function c_selected(c: Controller) {
  return c.store.state.selectedTrack ?? TRACKS[1].id
}
