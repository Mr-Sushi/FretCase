import { useEffect, useState } from 'react'
import { StepHeader } from '../App'
import { useApp, useSel } from '../app/context'
import { describeSection } from '../lib/describe'
import { instrumentLabel } from '../lib/catalog'
import { sectionLines } from '../lib/lyrics'
import { formatLong, isLocked, songSeconds, studioState, TRACKS } from '../lib/song'
import type { LeadTrack } from '../api'
import type { TrackId } from '../types'
import { BarSlider, KnobDial, PauseIcon, PlayIcon } from './ui'

const LEADABLE: TrackId[] = ['vocal', 'melody', 'guitar']

/** The instrument of one track, as a small menu; `up` opens it upwards, `onPick` replaces the plain change. */
export function SoundPicker({ track, up, onPick }: { track: TrackId; up?: boolean; onPick?: (id: string) => void }) {
  const { c } = useApp()
  const song = useSel((s) => s.song)!
  const cat = useSel((s) => s.catalog)
  const [open, setOpen] = useState(false)
  const items = cat.instruments[track] ?? []
  return (
    <span className="sound">
      <button type="button" aria-label={`Change the ${TRACKS.find((t) => t.id === track)!.name.toLowerCase()} sound`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="grow">{instrumentLabel(cat, track, song.tracks[track].instrument)}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M1 3l4 4 4-4" stroke="#BFAE98" strokeWidth="1.6" fill="none" /></svg>
      </button>
      {open && (
        <span className={`menu ${up ? 'up' : ''}`} role="menu">
          {items.map((it) => (
            <button key={it.id} type="button" role="menuitemradio" aria-checked={it.id === song.tracks[track].instrument} className={it.id === song.tracks[track].instrument ? 'on' : ''}
              onClick={() => { setOpen(false); if (onPick) onPick(it.id); else void c.setInstrument(track, it.id) }}>{it.label}</button>
          ))}
        </span>
      )}
    </span>
  )
}

export function ShapeView() {
  const { c } = useApp()
  const song = useSel((s) => s.song)
  const cat = useSel((s) => s.catalog)
  const sel = useSel((s) => s.editSection)
  const playing = useSel((s) => s.playing)
  const looping = useSel((s) => s.looping)
  const takes = useSel((s) => s.takes)
  if (!song) return null
  const selSec = song.sections.find((s) => s.id === sel) ?? song.sections[0]
  const leadTrack = selSec.lead
  const leadName = leadTrack ? TRACKS.find((t) => t.id === leadTrack)!.name : null
  const knobs = song.controls
  const word = (v: number, lo: string, mid: string, hi: string) => (v < 0.34 ? lo : v < 0.67 ? mid : hi)
  return (
    <>
      <StepHeader />
      <main className="shape">
        <div className="shape-top">
          <button type="button" className="playbtn big" aria-label={playing ? 'Pause' : 'Play'} onClick={() => void c.togglePlay()}>{playing ? <PauseIcon size={20} /> : <PlayIcon size={20} />}</button>
          <div>
            <h1>{song.title}</h1>
            <div className="tiny2">{song.candidate?.name ? `${song.candidate.name} · ` : ''}{formatLong(songSeconds(song))} · {looping ? <button type="button" className="linkbtn inline" onClick={() => c.listenAll()}>Playing one section; tap here for the whole song</button> : 'Tap a section to hear only that section'}</div>
          </div>
          <div className="grow" />
          <StudioButton />
          <button type="button" className="outline" onClick={() => void c.undo()}>Undo</button>
          <button type="button" className="outline" onClick={() => c.setView('detail')}>Tracks and lyrics</button>
          <button type="button" className="gobtn small" onClick={() => c.setView('card')}>Make card</button>
        </div>

        <section aria-label="Sections" className="tiles">
          {song.sections.map((s) => {
            const on = s.id === selSec.id
            const lines = sectionLines(song, s.id)
            const locked = isLocked(song, null, s.id)
            return (
              <div key={s.id} className={`tile ${on ? 'on' : ''}`}>
                <button type="button" aria-pressed={on} className="tile-body" onClick={() => c.selectSection(s.id)}>
                  <span className="tile-head">
                    <span className="tile-name">{s.label}</span>
                    <span className="muted13">take {takes[s.id] ?? 1}</span>
                    {locked && <span className="kept">Kept</span>}
                  </span>
                  <span className="muted13">{describeSection(song, cat, s.id)}</span>
                  <span className="tile-lyrics">{lines.length ? lines.map((l) => l.text).join('\n') : '(no lyrics)'}</span>
                </button>
                {on && (
                  <div className="tile-actions">
                    <button type="button" className="whitebtn" onClick={() => void c.another(s.id)}>Another take</button>
                    <button type="button" className={`outline ${locked ? 'fill' : ''}`} aria-pressed={locked} onClick={() => void c.toggleLock(undefined, s.id)}>{locked ? 'Kept' : 'Keep'}</button>
                  </div>
                )}
              </div>
            )
          })}
        </section>

        <div className="shape-bottom">
          <section aria-label="Players" className="panel players">
            <div className="panel-head">
              <h2>Players</h2>
              <span className="muted13">{leadName ? `${leadName} leads the ${selSec.label.toLowerCase()}; the others make room` : `Tap “Lead” to let one player lead the ${selSec.label.toLowerCase()}`}</span>
            </div>
            {TRACKS.map((t) => {
              const tr = song.tracks[t.id]
              const dim = tr.muted
              const isLead = leadTrack === t.id
              return (
                <div key={t.id} className="player" style={{ opacity: dim ? 0.45 : 1 }}>
                  <span className="pcolor" style={{ background: t.color }} />
                  <span className="pn">{t.name}</span>
                  <SoundPicker track={t.id} />
                  {LEADABLE.includes(t.id) ? (
                    <button type="button" className={`leadbtn ${isLead ? 'on' : ''}`} aria-pressed={isLead} onClick={() => void c.setLead(selSec.id, isLead ? null : (t.id as LeadTrack))}>Lead</button>
                  ) : <span className="leadbtn ghost" />}
                  <BarSlider value={tr.volume} color={t.color} label={`${t.name} volume`} onInput={(v) => c.previewVolume(t.id, v)} onCommit={(v) => void c.setVolume(t.id, v)} />
                  <button type="button" className={`mutebtn ${tr.muted ? 'on' : ''}`} aria-pressed={tr.muted} onClick={() => void c.toggleMute(t.id)}>{tr.muted ? 'Muted' : 'Mute'}</button>
                </div>
              )
            })}
          </section>
          <section aria-label="Feel" className="panel feel">
            <div className="panel-head"><h2>Feel</h2><span className="muted13">The four knobs on the case</span></div>
            <div className="knobs">
              <KnobDial name="Brightness" value={knobs.brightness} step={0.1} text={(v) => word(v, 'darker', 'medium', 'brighter')} onCommit={(v) => void c.setControl('brightness', v)} />
              <KnobDial name="Complexity" value={knobs.complexity} step={0.1} text={(v) => word(v, 'simple', 'medium', 'rich')} onCommit={(v) => void c.setControl('complexity', v)} />
              <KnobDial name="Density" value={knobs.density} step={0.1} text={(v) => word(v, 'sparse', 'medium', 'dense')} onCommit={(v) => void c.setControl('density', v)} />
              <KnobDial name="Tempo" value={song.tempo} min={40} max={220} step={4} text={(v) => `${Math.round(v)} BPM`} onCommit={(v) => void c.setTempo(Math.round(v))} />
            </div>
          </section>
        </div>
      </main>
    </>
  )
}

/** The studio version: make it (a music model sings the whole song), wait for it, then play it. */
function StudioButton() {
  const { c } = useApp()
  const song = useSel((s) => s.song)
  const studio = useSel((s) => s.studio)
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!studio.working) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [studio.working])
  if (!song) return null
  const state = studioState(song)
  if (studio.working) {
    const secs = Math.max(0, Math.round((now - (studio.startedAt ?? now)) / 1000))
    return <button type="button" className="studiobtn working" disabled aria-live="polite">Singing… {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, '0')}</button>
  }
  if (state === 'none') return <button type="button" className="studiobtn" title="A music model sings and plays the whole song (needs the internet)" onClick={() => void c.makeStudioVersion()}>✦ Studio version</button>
  return (
    <span className="studiogroup">
      <button type="button" className={`studiobtn ${studio.playing ? 'on' : ''}`} aria-pressed={studio.playing} title={state === 'older' ? 'Made before your last changes' : 'The whole song, sung'} onClick={() => c.toggleStudio()}>
        {studio.playing ? <PauseIcon size={14} /> : <PlayIcon size={14} />} Studio{state === 'older' ? ' (older)' : ''}
      </button>
      <button type="button" className="studiobtn again" aria-label="Make the studio version again" title="Make it again from the song as it is now" onClick={() => void c.makeStudioVersion()}>↻</button>
    </span>
  )
}
