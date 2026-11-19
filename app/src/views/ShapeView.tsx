import { useState } from 'react'
import { StepHeader } from '../App'
import { useApp, useSel } from '../app/context'
import { describeSection } from '../lib/describe'
import { instrumentLabel } from '../lib/catalog'
import { sectionLines } from '../lib/lyrics'
import { formatLong, isLocked, songSeconds, TRACKS } from '../lib/song'
import type { LeadTrack } from '../api'
import type { TrackId } from '../types'
import { BarSlider, KnobDial, PauseIcon, PlayIcon } from './ui'

const LEADABLE: TrackId[] = ['vocal', 'melody', 'guitar']

function SoundPicker({ track }: { track: TrackId }) {
  const { c } = useApp()
  const song = useSel((s) => s.song)!
  const cat = useSel((s) => s.catalog)
  const [open, setOpen] = useState(false)
  const items = cat.instruments[track] ?? []
  return (
    <span className="sound">
      <button type="button" aria-label={`换${TRACKS.find((t) => t.id === track)!.name}的音色`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="grow">{instrumentLabel(cat, track, song.tracks[track].instrument)}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M1 3l4 4 4-4" stroke="#BFAE98" strokeWidth="1.6" fill="none" /></svg>
      </button>
      {open && (
        <span className="menu" role="menu">
          {items.map((it) => (
            <button key={it.id} type="button" role="menuitemradio" aria-checked={it.id === song.tracks[track].instrument} className={it.id === song.tracks[track].instrument ? 'on' : ''}
              onClick={() => { setOpen(false); void c.setInstrument(track, it.id) }}>{it.label}</button>
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
          <button type="button" className="playbtn big" aria-label={playing ? '暂停' : '播放'} onClick={() => void c.togglePlay()}>{playing ? <PauseIcon size={20} /> : <PlayIcon size={20} />}</button>
          <div>
            <h1>{song.title}</h1>
            <div className="tiny2">{song.candidate?.name ? `${song.candidate.name} · ` : ''}{formatLong(songSeconds(song))} · {looping ? <button type="button" className="linkbtn inline" onClick={() => c.listenAll()}>现在只听这一段，点这里听整首</button> : '点一段只听那一段'}</div>
          </div>
          <div className="grow" />
          <button type="button" className="outline" onClick={() => void c.undo()}>撤销</button>
          <button type="button" className="outline" onClick={() => c.setView('detail')}>音轨和歌词</button>
          <button type="button" className="gobtn small" onClick={() => c.setView('card')}>做卡</button>
        </div>

        <section aria-label="段落" className="tiles">
          {song.sections.map((s) => {
            const on = s.id === selSec.id
            const lines = sectionLines(song, s.id)
            const locked = isLocked(song, null, s.id)
            return (
              <div key={s.id} className={`tile ${on ? 'on' : ''}`}>
                <button type="button" aria-pressed={on} className="tile-body" onClick={() => c.selectSection(s.id)}>
                  <span className="tile-head">
                    <span className="tile-name">{s.label}</span>
                    <span className="muted13">第 {takes[s.id] ?? 1} 版</span>
                    {locked && <span className="kept">已保留</span>}
                  </span>
                  <span className="muted13">{describeSection(song, cat, s.id)}</span>
                  <span className="tile-lyrics">{lines.length ? lines.map((l) => l.text).join('\n') : '（没有歌词）'}</span>
                </button>
                {on && (
                  <div className="tile-actions">
                    <button type="button" className="whitebtn" onClick={() => void c.another(s.id)}>换一段</button>
                    <button type="button" className={`outline ${locked ? 'fill' : ''}`} aria-pressed={locked} onClick={() => void c.toggleLock(undefined, s.id)}>{locked ? '已保留' : '保留'}</button>
                  </div>
                )}
              </div>
            )
          })}
        </section>

        <div className="shape-bottom">
          <section aria-label="乐手" className="panel players">
            <div className="panel-head">
              <h2>乐手</h2>
              <span className="muted13">{leadName ? `${selSec.label}由${leadName}当主角，其他乐手让一让` : `点「主角」，让一个乐手在${selSec.label}里领头`}</span>
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
                    <button type="button" className={`leadbtn ${isLead ? 'on' : ''}`} aria-pressed={isLead} onClick={() => void c.setLead(selSec.id, isLead ? null : (t.id as LeadTrack))}>主角</button>
                  ) : <span className="leadbtn ghost" />}
                  <BarSlider value={tr.volume} color={t.color} label={`${t.name}音量`} onInput={(v) => c.previewVolume(t.id, v)} onCommit={(v) => void c.setVolume(t.id, v)} />
                  <button type="button" className={`mutebtn ${tr.muted ? 'on' : ''}`} aria-pressed={tr.muted} onClick={() => void c.toggleMute(t.id)}>{tr.muted ? '已静音' : '静音'}</button>
                </div>
              )
            })}
          </section>
          <section aria-label="感觉" className="panel feel">
            <div className="panel-head"><h2>感觉</h2><span className="muted13">对应箱子上的四个旋钮</span></div>
            <div className="knobs">
              <KnobDial name="明暗" value={knobs.brightness} step={0.1} text={(v) => word(v, '偏暗', '适中', '偏亮')} onCommit={(v) => void c.setControl('brightness', v)} />
              <KnobDial name="简繁" value={knobs.complexity} step={0.1} text={(v) => word(v, '简单', '适中', '丰富')} onCommit={(v) => void c.setControl('complexity', v)} />
              <KnobDial name="疏密" value={knobs.density} step={0.1} text={(v) => word(v, '偏疏', '中等', '偏密')} onCommit={(v) => void c.setControl('density', v)} />
              <KnobDial name="速度" value={song.tempo} min={40} max={220} step={4} text={(v) => `每分钟 ${Math.round(v)} 拍`} onCommit={(v) => void c.setTempo(Math.round(v))} />
            </div>
          </section>
        </div>
      </main>
    </>
  )
}
