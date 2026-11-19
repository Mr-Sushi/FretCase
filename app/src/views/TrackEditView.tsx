import { useEffect, useMemo, useRef, useState } from 'react'
import { useApp, useSel } from '../app/context'
import { TRACKS, barTicks, hasExactLock, isLocked, noteName, sectionRange, snapToKey, trackColor, trackName } from '../lib/song'
import type { Note, RhythmPreset, Song, TrackId, VocalNote } from '../types'

const GRID = 240 // an eighth note
const DRUM_ROWS = [
  { pitch: 49, label: '吊镲' }, { pitch: 46, label: '开镲' }, { pitch: 42, label: '闭镲' },
  { pitch: 38, label: '军鼓' }, { pitch: 36, label: '底鼓' },
]

type EditNote = Note & { lyric?: string; lineEnd?: boolean }

function presetsOf(catalog: ReturnType<typeof useCatalog>): RhythmPreset[] {
  const r = catalog?.rhythmPresets
  return !r ? [] : Array.isArray(r) ? r : r.presets
}
function useCatalog() { return useSel((s) => s.catalog) }

export function TrackEditView() {
  const { c } = useApp()
  const song = useSel((s) => s.song)!
  const track = useSel((s) => s.selectedTrack) ?? 'melody'
  const secId = useSel((s) => s.editSection) ?? song.sections[0].id
  const pos = useSel((s) => s.positionTick)
  const catalog = useCatalog()
  const section = song.sections.find((s) => s.id === secId) ?? song.sections[0]
  const range = sectionRange(song, section)
  const color = trackColor(track)
  const trackLocked = isLocked(song, track, null)
  const exactLock = hasExactLock(song, track, section.id)
  const tr = song.tracks[track]
  const instruments = catalog?.instruments[track] ?? [tr.instrument]
  const presets = presetsOf(catalog).filter((p) => p.meter === `${song.meter.numerator}/${song.meter.denominator}`)

  return (
    <div className="trackedit" style={{ ['--tc' as string]: color }}>
      <div className="te-bar">
        <div className="tracktabs">
          {TRACKS.map((t) => (
            <button key={t.id} className={track === t.id ? 'on' : ''} style={{ ['--tc' as string]: t.color }} onClick={() => c.editTrack(t.id, section.id)}>
              <span className="swatch" style={{ background: t.color }} />{t.name}
            </button>
          ))}
        </div>
        <div className="sectabs">
          {song.sections.map((s) => (
            <button key={s.id} className={s.id === section.id ? 'on' : ''} onClick={() => c.setEditSection(s.id)}>
              {s.label}{isLocked(song, track, s.id) ? ' 锁' : ''}
            </button>
          ))}
        </div>
      </div>

      <div className="te-tools">
        <label>音色
          <select value={tr.instrument} onChange={(e) => void c.setInstrument(track, e.target.value)}>
            {instruments.map((i) => <option key={i}>{i}</option>)}
          </select>
        </label>
        {track === 'guitar' && presets.length > 0 && (
          <label>节奏型
            <select value={song.tracks.guitar.rhythm.presetId} onChange={(e) => { const p = presets.find((x) => x.id === e.target.value)!; void c.setRhythm(p.family, p.id) }}>
              {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </label>
        )}
        <span className="grow" />
        <button className={`btn small ${exactLock ? 'on' : ''}`} onClick={() => void c.toggleLock(track, section.id)}>{exactLock ? '解锁这一段' : '锁定这一段'}</button>
        <button className={`btn small ${trackLocked ? 'on' : ''}`} onClick={() => void c.toggleLock(track)}>{trackLocked ? '解锁整轨' : '锁定整轨'}</button>
        <button className="btn small" onClick={() => void c.another(section.id, track)}>这一轨换一个</button>
        <button className="btn small" onClick={() => void c.undo()}>撤销</button>
      </div>

      {track === 'ambience'
        ? <div className="empty big">环境声是你录的声音，不能改音符。用推子调音量，或者在整首歌页静音。</div>
        : <Roll song={song} track={track} sectionId={section.id} range={range} color={color} pos={pos} />}

      {track === 'vocal' && <Lyrics song={song} sectionId={section.id} range={range} />}
      <div className="te-foot">循环播放「{section.label}」，改动后会马上听到。{trackName(track)}手动改过的段落会被锁定，「换一个」不会动它。</div>
    </div>
  )
}

function Roll({ song, track, sectionId, range, color, pos }: { song: Song; track: Exclude<TrackId, 'ambience'>; sectionId: string; range: { from: number; to: number }; color: string; pos: number }) {
  const { c } = useApp()
  const drums = track === 'drums'
  const base = useMemo<EditNote[]>(
    () => (song.tracks[track].notes as EditNote[]).filter((n) => n.start >= range.from && n.start < range.to),
    [song, track, range.from, range.to],
  )
  const [draft, setDraft] = useState<EditNote[] | null>(null)
  const [sel, setSel] = useState<number | null>(null)
  const notes = draft ?? base
  const roll = useRef<HTMLDivElement>(null)
  const drag = useRef<{ idx: number; mode: 'move' | 'resize'; x0: number; y0: number; orig: EditNote; w: number; h: number; moved: boolean } | null>(null)

  useEffect(() => { setDraft(null) }, [song.revision, track, sectionId])
  useEffect(() => { setSel(null) }, [track, sectionId])

  const rows = useMemo(() => {
    if (drums) return DRUM_ROWS.map((r) => r.pitch)
    const ps = base.map((n) => n.pitch)
    const lo = (ps.length ? Math.min(...ps) : 60) - 3
    const hi = (ps.length ? Math.max(...ps) : 72) + 3
    const mid = Math.round((lo + hi) / 2)
    const a = Math.min(lo, mid - 8), b = Math.max(hi, mid + 8)
    return Array.from({ length: b - a + 1 }, (_, i) => b - i)
  }, [base, drums])
  const rowOf = (p: number) => rows.indexOf(p)
  const rowH = 100 / rows.length
  const span = range.to - range.from
  const bt = barTicks(song.meter)

  const commit = async (next: EditNote[]) => {
    const clean = next
      .map((n) => ({ ...n, start: Math.min(Math.max(n.start, range.from), range.to - GRID) }))
      .sort((a, b) => a.start - b.start || a.pitch - b.pitch)
      .map((n) => ({ start: n.start, duration: n.duration, pitch: n.pitch, ...(n.velocity ? { velocity: n.velocity } : {}), ...(track === 'vocal' && n.lyric ? { lyric: n.lyric } : {}), ...(track === 'vocal' && n.lineEnd ? { lineEnd: true } : {}) }))
    setDraft(next)
    await c.replaceNotes(track, range.from, range.to, clean)
    setDraft(null)
  }

  const down = (e: React.PointerEvent, idx: number, mode: 'move' | 'resize') => {
    e.stopPropagation()
    const r = roll.current!.getBoundingClientRect()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    drag.current = { idx, mode, x0: e.clientX, y0: e.clientY, orig: { ...notes[idx] }, w: r.width, h: r.height, moved: false }
  }
  const move = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x0, dy = e.clientY - d.y0
    if (!d.moved && Math.abs(dx) < 4 && Math.abs(dy) < 4) return
    d.moved = true
    const dTicks = Math.round(((dx / d.w) * span) / GRID) * GRID
    const next = notes.map((n) => ({ ...n }))
    const n = next[d.idx]
    if (d.mode === 'resize') {
      n.duration = Math.max(GRID, d.orig.duration + dTicks)
    } else {
      n.start = Math.max(range.from, Math.min(range.to - GRID, d.orig.start + dTicks))
      if (drums) {
        const r0 = rowOf(d.orig.pitch)
        const r = Math.max(0, Math.min(rows.length - 1, r0 + Math.round(dy / ((d.h / rows.length)))))
        n.pitch = rows[r]
      } else {
        const steps = -Math.round(dy / (d.h / rows.length))
        n.pitch = snapToKey(Math.max(0, Math.min(127, d.orig.pitch + steps)), song.key)
      }
    }
    setDraft(next)
  }
  const up = () => {
    const d = drag.current
    drag.current = null
    if (!d) return
    if (!d.moved) { setSel(d.idx); return }
    setSel(d.idx)
    void commit(draft ?? notes)
  }

  const addAt = (e: React.MouseEvent) => {
    if (e.target !== e.currentTarget && !(e.target as HTMLElement).classList.contains('gridline')) return
    const r = roll.current!.getBoundingClientRect()
    const tick = range.from + Math.floor((((e.clientX - r.left) / r.width) * span) / GRID) * GRID
    const rowIdx = Math.min(rows.length - 1, Math.max(0, Math.floor(((e.clientY - r.top) / r.height) * rows.length)))
    const pitch = drums ? rows[rowIdx] : snapToKey(rows[rowIdx], song.key)
    const duration = drums ? 120 : 480
    void commit([...notes, { start: tick, duration, pitch, velocity: 90 }])
  }

  const removeSel = () => {
    if (sel === null) return
    setSel(null)
    void commit(notes.filter((_, i) => i !== sel))
  }

  const head = pos >= range.from && pos < range.to ? ((pos - range.from) / span) * 100 : null

  return (
    <div className="roll-wrap">
      <div className="roll-labels">
        {rows.map((p, i) => (
          <div key={p} className="rl" style={{ height: `${rowH}%` }} data-row={i}>
            {drums ? DRUM_ROWS.find((r) => r.pitch === p)?.label : (inKey(p, song) ? noteName(p) : '')}
          </div>
        ))}
      </div>
      <div className="roll" ref={roll} onClick={addAt}>
        {rows.map((p, i) => <div key={p} className={`gridrow ${!drums && !inKey(p, song) ? 'off' : ''}`} style={{ top: `${i * rowH}%`, height: `${rowH}%` }} />)}
        {Array.from({ length: Math.round(span / bt) + 1 }, (_, b) => <div key={b} className="gridline bar" style={{ left: `${(b * bt / span) * 100}%` }} />)}
        {Array.from({ length: Math.round(span / 480) }, (_, b) => <div key={`q${b}`} className="gridline beat" style={{ left: `${(b * 480 / span) * 100}%` }} />)}
        {notes.map((n, i) => {
          const r = rowOf(n.pitch)
          if (r < 0) return null
          return (
            <div key={i} className={`note ${sel === i ? 'sel' : ''}`}
              style={{ left: `${((n.start - range.from) / span) * 100}%`, width: `${(n.duration / span) * 100}%`, top: `${r * rowH}%`, height: `${rowH}%`, background: color }}
              onPointerDown={(e) => down(e, i, 'move')} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
              {track === 'vocal' && (n as VocalNote).lyric ? <span className="lyric">{(n as VocalNote).lyric}</span> : null}
              <div className="grip" onPointerDown={(e) => down(e, i, 'resize')} onPointerMove={move} onPointerUp={up} onPointerCancel={up} />
            </div>
          )
        })}
        {head !== null && <div className="roll-head" style={{ left: `${head}%` }} />}
      </div>
      <div className="roll-side">
        <div className="hint">点空白处加音符，拖动改音高和位置，拖右边缘改长短。{drums ? '' : '音高会吸附到调内音。'}</div>
        <button className="btn small" disabled={sel === null} onClick={removeSel}>删除选中的音</button>
        {sel !== null && notes[sel] && <div className="sel-info">{drums ? '' : noteName(notes[sel].pitch)}</div>}
      </div>
    </div>
  )
}

function inKey(pitch: number, song: Song) { return snapToKey(pitch, song.key) === pitch }

function Lyrics({ song, sectionId, range }: { song: Song; sectionId: string; range: { from: number; to: number } }) {
  const { c } = useApp()
  const notes = song.tracks.vocal.notes.filter((n) => n.start >= range.from && n.start < range.to)
  const current = notes.map((n) => n.lyric ?? '').join('')
  const [text, setText] = useState(current)
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => { setText(current); setMsg(null) }, [current, sectionId])
  const count = [...text.replace(/\s+/g, '')].length
  const ok = count === notes.length

  return (
    <div className="lyrics">
      <label>歌词（这一段 {notes.length} 个音，一个字一个音）</label>
      <div className="lyric-row">
        <input value={text} onChange={(e) => { setText(e.target.value); setMsg(null) }} placeholder="一个字对应一个音" />
        <span className={`count ${ok ? 'ok' : 'bad'}`}>{count} / {notes.length}</span>
        <button className="btn small" disabled={!text.trim()} onClick={async () => {
          const r = await c.setLyrics(sectionId, text)
          if (!r.ok && r.noteCount !== undefined) setMsg(`这一段有 ${r.noteCount} 个音，歌词有 ${r.syllableCount} 个字。请增减歌词，或在上面加、删音符。`)
          else if (r.ok) setMsg('歌词已写入')
        }}>写入歌词</button>
      </div>
      {msg && <div className="hint">{msg}</div>}
      {song.tracks.vocal.source === 'none' && <div className="hint">现在人声是提示音，联网合成人声是第二版的功能。</div>}
    </div>
  )
}
