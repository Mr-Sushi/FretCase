import { useEffect, useMemo } from 'react'
import { createApi } from './api'
import { PlaybackEngine } from './audio/engine'
import { AppContext, useApp, useSel } from './app/context'
import { Controller } from './app/controller'
import { Store, initialState, type View } from './app/store'
import { PanelClient, panelUrl } from './panel/client'
import { CaptureView } from './views/CaptureView'
import { PickView } from './views/PickView'
import { ShapeView } from './views/ShapeView'
import { DetailView } from './views/DetailView'
import { LyricsView } from './views/LyricsView'
import { CardView } from './views/CardView'
import { ScanOverlay } from './views/ScanOverlay'

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
    // A shortcut for demos and screenshots: ?view=shape opens the demo song on that screen.
    const q = new URLSearchParams(location.search).get('view')
    if (api.mock && q) void (async () => {
      await c.init()
      if (q !== 'capture' && q !== 'pick') await c.openSong('song-demo-0001')
      if (q !== 'shape' && q !== 'capture' && q !== 'pick') c.setView(q as View)
    })()
    const health = setInterval(() => void c.refreshHealth(), 10000)
    return () => { clearInterval(health); panel?.stop(); c.dispose(); world.engine.dispose() }
  }, [world])

  return (
    <AppContext.Provider value={{ c: world.c, store: world.store }}>
      <Shell />
    </AppContext.Provider>
  )
}

const STEPS: { view: View; no: string; label: string }[] = [
  { view: 'capture', no: '①', label: 'Capture' },
  { view: 'pick', no: '②', label: 'Pick' },
  { view: 'shape', no: '③', label: 'Shape' },
  { view: 'card', no: '④', label: 'Card' },
]
const STEP_OF: Record<View, View> = { capture: 'capture', pick: 'pick', shape: 'shape', detail: 'shape', lyrics: 'shape', card: 'card' }

/** The top bar of the four main steps. */
export function StepHeader({ right }: { right?: React.ReactNode }) {
  const { c } = useApp()
  const view = useSel((s) => s.view)
  const song = useSel((s) => s.song)
  const candidates = useSel((s) => s.candidates)
  const server = useSel((s) => s.serverOnline)
  const net = useSel((s) => s.netOnline)
  const panel = useSel((s) => s.panelConnected)
  const mock = useSel((s) => s.mock)
  const active = STEP_OF[view]
  const enabled = (v: View) => v === 'capture' || (v === 'pick' ? !!candidates : !!song)
  return (
    <header className="topbar">
      <div className="brand">FretCase</div>
      <nav aria-label="Steps" className="steps">
        {STEPS.map((s) => (
          <button key={s.view} type="button" className={`step ${active === s.view ? 'on' : ''}`} disabled={!enabled(s.view)} aria-current={active === s.view ? 'step' : undefined} onClick={() => c.setView(s.view)}>
            {s.no} {s.label}
          </button>
        ))}
      </nav>
      <div className="status">
        {right}
        {mock && <span className="pill">Demo</span>}
        {server === false && <span className="pill bad">Server unreachable</span>}
        <span className="pill">{net ? 'Online' : 'Offline'}</span>
        <span className="pill">{panel ? 'Panel connected' : 'No panel'}</span>
        <button type="button" className="ghostbtn" onClick={() => c.store.set({ scanning: true })}>Scan card</button>
      </div>
    </header>
  )
}

function Shell() {
  const view = useSel((s) => s.view)
  const busy = useSel((s) => s.busy)
  const toast = useSel((s) => s.toast)
  const scanning = useSel((s) => s.scanning)
  return (
    <div className="shell">
      {view === 'capture' && <CaptureView />}
      {view === 'pick' && <PickView />}
      {view === 'shape' && <ShapeView />}
      {view === 'detail' && <DetailView />}
      {view === 'lyrics' && <LyricsView />}
      {view === 'card' && <CardView />}
      {scanning && <ScanOverlay />}
      {busy && <div className="busy" role="status"><span className="spinner" />{busy}</div>}
      {toast && <div className={`toast ${toast.kind}`} key={toast.id} role="status">{toast.text}</div>}
    </div>
  )
}
