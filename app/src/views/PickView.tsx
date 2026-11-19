import { StepHeader } from '../App'
import { useApp, useSel } from '../app/context'
import { PREVIEW_SECONDS } from '../app/controller'
import { formatLong, songSeconds, TRACKS } from '../lib/song'
import type { TimeOfDay } from '../types'
import { PauseIcon, PlayIcon } from './ui'

const TIMES: { id: TimeOfDay; label: string }[] = [{ id: 'day', label: '白天' }, { id: 'dusk', label: '黄昏' }, { id: 'night', label: '夜晚' }]

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
            <h1>听听这三首，挑最像今天的</h1>
            <div className="lead">三首都用了你收集的东西，只是编法不同。转唱盘在三首之间切换，按红键选定。</div>
          </div>
          <div role="group" aria-label="时段" className="seg timeseg">
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
            return (
              <article key={song.id} className={`cand ${focused ? 'focus' : ''}`} onClick={() => c.focusCandidate(i)}>
                <div className="cand-title">
                  <span className="no">{i + 1}</span>
                  <h2>{cand?.name ?? song.title}</h2>
                </div>
                <div className="tags">{cand?.tags.map((t) => <span key={t}>{t}</span>)}</div>
                <div className="parts" aria-label="谁在演奏">
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
                    <button type="button" className="playbtn" aria-label={isPlaying ? '暂停' : '试听'} onClick={(e) => { e.stopPropagation(); void c.previewCandidate(i) }}>
                      {isPlaying ? <PauseIcon /> : <PlayIcon />}
                    </button>
                    <div className="grow">
                      <div className="progress"><div style={{ width: `${progress}%` }} /></div>
                      <div className="tiny">试听 {PREVIEW_SECONDS} 秒 · 全曲 {formatLong(songSeconds(song))}</div>
                    </div>
                  </div>
                  <button type="button" className={`ctabtn ${focused ? 'fill' : ''}`} onClick={(e) => { e.stopPropagation(); void c.chooseCandidate(i) }}>就要这首</button>
                </div>
              </article>
            )
          })}
        </div>
        <div className="pick-foot">
          <button type="button" className="outline big" onClick={() => void c.moreCandidates({ again: true })}>都不像，再来三首</button>
          <button type="button" className="linkbtn" onClick={() => c.setView('capture')}>回去补一张照片或再哼一段</button>
          <span className="tiny right">选好之后每一段、每个乐手都还能再换</span>
        </div>
      </main>
    </>
  )
}
