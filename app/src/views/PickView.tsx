import { StepHeader } from '../App'
import { useApp, useSel } from '../app/context'
import { PREVIEW_SECONDS } from '../app/controller'
import { formatLong, songFeel, songSeconds, TRACKS } from '../lib/song'
import type { TimeOfDay } from '../types'
import { PauseIcon, PlayIcon } from './ui'

const TIMES: { id: TimeOfDay; label: string }[] = [{ id: 'day', label: 'Day' }, { id: 'dusk', label: 'Dusk' }, { id: 'night', label: 'Night' }]

export function PickView() {
  const { c } = useApp()
  const candidates = useSel((s) => s.candidates) ?? []
  const tod = useSel((s) => s.timeOfDay)
  const focus = useSel((s) => s.focus)
  const preview = useSel((s) => s.preview)
  const playing = useSel((s) => s.playing)
  const pos = useSel((s) => s.positionTick)
  return (
    <>
      <StepHeader />
      <main className="pick">
        <div className="pick-head">
          <div>
            <h1>Listen to these three and pick the one most like today</h1>
            <div className="lead">All three use what you captured, arranged in different ways. Turn the platter to move between them; press the red key to choose.</div>
            <div className="feelkey" aria-hidden="true"><span>The colour shows the feel:</span><span>calm</span><i /><span>lively</span></div>
          </div>
          <div role="group" aria-label="Time of day" className="seg timeseg">
            {TIMES.map((t) => (
              <button key={t.id} type="button" aria-pressed={tod === t.id} className={tod === t.id ? 'on' : ''} onClick={() => void c.moreCandidates({ timeOfDay: t.id })}>{t.label}</button>
            ))}
          </div>
        </div>
        <div className="cands">
          {candidates.map((song, i) => {
            const cand = song.candidate
            const isPlaying = preview?.index === i && playing
            const progress = preview?.index === i ? Math.max(0, Math.min(100, ((pos - preview.fromTick) / (preview.toTick - preview.fromTick)) * 100)) : 0
            const focused = focus === i
            const feel = songFeel(song)
            return (
              <article key={song.id} className={`cand feel-${feel.id} ${focused ? 'focus' : ''}`} style={{ '--feel': feel.color } as React.CSSProperties} onClick={() => c.focusCandidate(i)}>
                <div className="cand-title">
                  <span className="no">{i + 1}</span>
                  <h2>{cand?.name ?? song.title}</h2>
                </div>
                <div className="tags"><span className="feeltag">{feel.label} · {song.tempo} BPM</span>{cand?.tags.map((t) => <span key={t}>{t}</span>)}</div>
                <div className="parts" aria-label="Who is playing">
                  {TRACKS.map((t) => {
                    const p = cand?.parts?.[t.id]
                    return (
                      <div key={t.id} className="part">
                        <span className="pname">{t.name}</span>
                        <span className="pbar"><span style={{ width: `${Math.round((p?.level ?? 0) * 100)}%`, background: t.color }} /></span>
                        <span className="psound">{p?.sound ?? ''}</span>
                      </div>
                    )
                  })}
                </div>
                <div className="why">{cand?.why}</div>
                <div className="cand-foot">
                  <div className="row">
                    <button type="button" className="playbtn" aria-label={isPlaying ? 'Pause' : 'Listen'} onClick={(e) => { e.stopPropagation(); void c.previewCandidate(i) }}>
                      {isPlaying ? <PauseIcon /> : <PlayIcon />}
                    </button>
                    <div className="grow">
                      <div className="progress"><div style={{ width: `${progress}%` }} /></div>
                      <div className="tiny">{PREVIEW_SECONDS} s preview · whole song {formatLong(songSeconds(song))}</div>
                    </div>
                  </div>
                  <button type="button" className={`ctabtn ${focused ? 'fill' : ''}`} onClick={(e) => { e.stopPropagation(); void c.chooseCandidate(i) }}>This one</button>
                </div>
              </article>
            )
          })}
        </div>
        <div className="pick-foot">
          <button type="button" className="outline big" onClick={() => void c.moreCandidates({ again: true })}>None of these, three more</button>
          <button type="button" className="linkbtn" onClick={() => c.setView('capture')}>Go back to add a photo or hum again</button>
          <span className="tiny right">After choosing, you can still change every section and every player</span>
        </div>
      </main>
    </>
  )
}
