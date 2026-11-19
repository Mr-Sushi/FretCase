import { useRef } from 'react'
import { useApp, useSel } from '../app/context'
import { songEndTick } from '../audio/schedule'
import { TRACKS, barTicks, isLocked, hasExactLock, sectionAtBar, trackName } from '../lib/song'
import type { Song, TrackId } from '../types'
import { DraftSlider } from './ui'

const PX_PER_BAR_MIN = 44

function laneNotes(song: Song, id: TrackId) {
  if (id === 'ambience') return []
  return song.tracks[id].notes
}

/** Compact piano-roll thumbnail of one track. Percent positions so it scales with the timeline. */
function LaneBody({ song, id, color }: { song: Song; id: TrackId; color: string }) {
  const total = songEndTick(song)
  if (id === 'ambience') {
    return <>{song.tracks.ambience.clips.map((c, i) => (
      <div key={i} className="clip" style={{ left: `${(c.start / total) * 100}%`, width: `${(Math.min(c.duration, total - c.start) / total) * 100}%`, background: color }} />
    ))}</>
  }
  const notes = laneNotes(song, id)
  if (!notes.length) return null
  const drums = id === 'drums'
  const lo = Math.min(...notes.map((n) => n.pitch)), hi = Math.max(...notes.map((n) => n.pitch))
  const span = Math.max(1, hi - lo)
  return <>{notes.map((n, i) => {
    const y = drums ? ({ 36: 80, 35: 80, 38: 50, 40: 50, 42: 20, 46: 20 } as Record<number, number>)[n.pitch] ?? 35 : 12 + (1 - (n.pitch - lo) / span) * 70
    return <div key={i} className={`nb ${drums ? 'dr' : ''}`} style={{ left: `${(n.start / total) * 100}%`, width: `${Math.max(0.25, (n.duration / total) * 100)}%`, top: `${y}%`, background: color }} />
  })}</>
}

export function SongView() {
  const { c } = useApp()
  const song = useSel((s) => s.song)!
  const pos = useSel((s) => s.positionTick)
  const selected = useSel((s) => s.selectedTrack)
  const catalogReady = useSel((s) => !!s.catalog)
  const area = useRef<HTMLDivElement>(null)
  void catalogReady

  const total = songEndTick(song)
  const bt = barTicks(song.meter)
  const barNow = pos / bt
  const section = sectionAtBar(song.sections, Math.min(barNow, song.bars - 1e-6))
  const pct = (t: number) => `${(t / total) * 100}%`
  const innerW = `max(100%, ${song.bars * PX_PER_BAR_MIN}px)`

  const seekFromPointer = (e: React.PointerEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    c.seekToBar(((e.clientX - r.left) / r.width) * song.bars)
  }

  return (
    <div className="songview">
      <div className="timeline-scroll" ref={area}>
        <div className="timeline" style={{ width: innerW }}>
          <div className="lane-head spacer" />
          <div className="tl-grid">
            <div className="ruler" onPointerDown={seekFromPointer}>
              {Array.from({ length: song.bars }, (_, b) => <div key={b} className="tick" style={{ left: pct(b * bt) }}>{b % 4 === 0 ? b + 1 : ''}</div>)}
            </div>
            <div className="sections">
              {song.sections.map((s) => {
                const locked = hasExactLock(song, undefined, s.id)
                return (
                  <div key={s.id} className={`sec ${section?.id === s.id ? 'cur' : ''} ${locked ? 'locked' : ''}`} style={{ left: pct(s.startBar * bt), width: pct((s.endBar - s.startBar) * bt) }}
                    onClick={() => c.seekToBar(s.startBar)}>
                    <span>{s.label}</span>
                    <button className="mini" title="锁定这一段" onClick={(e) => { e.stopPropagation(); void c.toggleLock(undefined, s.id) }}>{locked ? '已锁' : '锁'}</button>
                  </div>
                )
              })}
            </div>
            <div className="chords" onPointerDown={seekFromPointer}>
              {song.harmony.map((h, i) => (
                <div key={i} className="chord" style={{ left: pct(h.start), width: pct(h.duration) }}>{h.symbol}</div>
              ))}
            </div>
          </div>

          {TRACKS.map((t) => {
            const tr = song.tracks[t.id]
            const locked = isLocked(song, t.id, null)
            return (
              <div key={t.id} className={`lane ${selected === t.id ? 'sel' : ''} ${tr.muted ? 'muted' : ''}`} style={{ ['--tc' as string]: t.color }}>
                <div className="lane-head" onClick={() => c.selectTrack(selected === t.id ? null : t.id)}>
                  <div className="lh-top">
                    <span className="swatch" style={{ background: t.color }} />
                    <b>{t.name}</b>
                    {locked && <span className="lockflag">锁</span>}
                  </div>
                  <DraftSlider value={tr.volume} label={`${t.name}音量`} onInput={(v) => c.previewVolume(t.id, v)} onCommit={(v) => void c.setVolume(t.id, v)} />
                  <div className="lh-btns">
                    <button className={`mini ${tr.muted ? 'on' : ''}`} onClick={(e) => { e.stopPropagation(); void c.toggleMute(t.id) }}>{tr.muted ? '已静音' : '静音'}</button>
                    <button className={`mini ${locked ? 'on' : ''}`} onClick={(e) => { e.stopPropagation(); void c.toggleLock(t.id) }}>{locked ? '解锁' : '锁定'}</button>
                    <button className="mini" onClick={(e) => { e.stopPropagation(); c.editTrack(t.id) }}>编辑</button>
                  </div>
                </div>
                <div className="lane-body" onPointerDown={seekFromPointer}>
                  {song.sections.map((s) => isLocked(song, t.id, s.id) && !locked && (
                    <div key={s.id} className="lockshade" style={{ left: pct(s.startBar * bt), width: pct((s.endBar - s.startBar) * bt) }} />
                  ))}
                  <LaneBody song={song} id={t.id} color={t.color} />
                </div>
              </div>
            )
          })}
          <div className="playhead" style={{ left: `calc(var(--head-w) + (100% - var(--head-w)) * ${Math.min(1, pos / total)})` }} />
        </div>
      </div>

      <div className="dock">
        <div className="knobs">
          {([['brightness', '明暗'], ['complexity', '简繁'], ['density', '疏密']] as const).map(([k, label]) => (
            <label key={k} className="knob">
              <span>{label}</span>
              <DraftSlider value={song.controls[k]} step={0.02} label={label} onCommit={(v) => void c.setControl(k, v)} />
            </label>
          ))}
          <label className="knob">
            <span>速度 {Math.round(song.tempo)}</span>
            <DraftSlider value={song.tempo} min={40} max={220} step={1} label="速度" onCommit={(v) => void c.setTempo(v)} />
          </label>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => void c.undo()}>撤销</button>
          <button className="btn" onClick={() => void c.another()}>
            换一个<small>{section?.label}{selected ? `·${trackName(selected)}` : ''}</small>
          </button>
          <button className="btn" onClick={() => c.setView('card')}>做卡片</button>
        </div>
      </div>
    </div>
  )
}
