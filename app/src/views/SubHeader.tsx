import { useApp, useSel } from '../app/context'
import { PauseIcon, PlayIcon } from './ui'

/** Top bar of the track and lyrics screens: back to the whole song, the two tabs, play, undo. */
export function SubHeader({ tab, hint }: { tab: 'tracks' | 'lyrics'; hint: string }) {
  const { c } = useApp()
  const playing = useSel((s) => s.playing)
  return (
    <header className="topbar sub">
      <button type="button" className="backbtn" onClick={() => c.setView('shape')}>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M8 1L3 6l5 5" stroke="#F3E9DA" strokeWidth="1.8" fill="none" /></svg>
        Whole song
      </button>
      <div role="tablist" aria-label="What to change" className="seg tabs2">
        <button type="button" role="tab" aria-selected={tab === 'tracks'} className={tab === 'tracks' ? 'on' : ''} onClick={() => c.setView('detail')}>Tracks</button>
        <button type="button" role="tab" aria-selected={tab === 'lyrics'} className={tab === 'lyrics' ? 'on' : ''} onClick={() => c.setView('lyrics')}>Lyrics</button>
      </div>
      {tab === 'tracks' && <button type="button" className="playbtn" aria-label={playing ? 'Pause' : 'Play'} onClick={() => void c.togglePlay()}>{playing ? <PauseIcon size={16} /> : <PlayIcon size={16} />}</button>}
      <span className="hint-top">{hint}</span>
      <button type="button" className="outline right" onClick={() => void c.undo()}>Undo</button>
    </header>
  )
}
