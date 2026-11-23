import { useEffect, useMemo } from 'react'
import { useApp, useSel } from '../app/context'
import { instrumentLabel, PAD_WORDS, STYLE_TITLE } from '../lib/catalog'
import { barTicks, regionOf, sectionRange, songTicks, TRACKS } from '../lib/song'
import type { Note, Song, TrackId } from '../types'
import { BarSlider } from './ui'
import { SubHeader } from './SubHeader'

/** One bar per song bar, as tall as everything that plays there. */
function energy(song: Song): number[] {
  const bt = barTicks(song.meter)
  const out = Array(song.bars).fill(0)
  for (const t of TRACKS) {
    if (t.id === 'ambience') { out.forEach((_, i) => { out[i] += 0.3 }); continue }
    for (const n of song.tracks[t.id].notes) {
      const b = Math.floor(n.start / bt)
      if (b >= 0 && b < song.bars) out[b] += (('velocity' in n && n.velocity) || 90) / 127
    }
  }
  const max = Math.max(1, ...out)
  return out.map((v) => v / max)
}

interface Mark { l: number; w: number; t: number; h: number }
function marksFor(song: Song, track: TrackId, sectionId: string): Mark[] {
  if (track === 'ambience') return [{ l: 1, w: 98, t: 16, h: 10 }]
  const sec = song.sections.find((s) => s.id === sectionId)!
  const { from, to } = sectionRange(song, sec)
  const notes = (song.tracks[track].notes as Note[]).filter((n) => n.start >= from && n.start < to)
  const len = to - from
  if (!notes.length) return []
  const lo = Math.min(...notes.map((n) => n.pitch)), hi = Math.max(...notes.map((n) => n.pitch))
  const seen = new Set<number>()
  const out: Mark[] = []
  for (const n of notes) {
    const key = n.start * 1000 + (track === 'guitar' ? 0 : n.pitch)
    if (seen.has(key)) continue
    seen.add(key)
    const l = ((n.start - from) / len) * 100
    if (track === 'guitar') out.push({ l, w: 0.9, t: 6, h: 28 })
    else if (track === 'drums') out.push({ l, w: 1.1, t: n.pitch === 36 ? 26 : n.pitch === 38 ? 16 : 8, h: n.pitch === 42 ? 4 : 6 })
    else out.push({ l, w: Math.max(0.8, (n.duration / len) * 100 * 0.85), t: 6 + (hi === lo ? 10 : (1 - (n.pitch - lo) / (hi - lo)) * 22), h: 5 })
    if (out.length > 90) break
  }
  return out
}

export function DetailView() {
  const { c } = useApp()
  const song = useSel((s) => s.song)
  const cat = useSel((s) => s.catalog)
  const selTrack = useSel((s) => s.selectedTrack)
  const selSection = useSel((s) => s.editSection)
  const solo = useSel((s) => s.solo)
  const pos = useSel((s) => s.positionTick)
  useEffect(() => { if (!selTrack) c.selectTrack('guitar') }, [selTrack, c])
  const bars = useMemo(() => (song ? energy(song) : []), [song])
  if (!song) return null
  const track = selTrack ?? 'guitar'
  const sec = song.sections.find((s) => s.id === selSection) ?? song.sections[0]
  const region = regionOf(song, track, sec.id)
  const t = TRACKS.find((x) => x.id === track)!
  const cols = song.sections.map((s) => `${s.endBar - s.startBar}fr`).join(' ')
  const words = PAD_WORDS[track]
  const tr = song.tracks[track]
  const padCol = region ? (region.complexity < 0.34 ? 0 : region.complexity < 0.67 ? 1 : 2) : 1
  const padRow = region ? (region.intensity >= 0.67 ? 0 : region.intensity >= 0.34 ? 1 : 2) : 1
  const rowWord = (r: number) => (r === 0 ? words[1] : r === 2 ? words[0] : 'medium')
  const colWord = (k: number) => (k === 0 ? words[2] : k === 2 ? words[3] : 'medium')
  const hasMotif = !!song.seed?.motif?.length
  const shiftable = track !== 'drums' && track !== 'ambience'
  const pct = Math.min(100, (pos / songTicks(song)) * 100)
  return (
    <>
      <SubHeader tab="tracks" hint="Tap a cell to choose a section, then set how this player plays it below" />
      <main className="detail">
        <section aria-label="Whole song" className="whole">
          <div className="whole-left">
            <div className="b700">Whole song</div>
            <div className="vol"><span>Master volume</span><BarSlider value={song.master.volume} color="#D4AE6A" label="Master volume" onInput={(v) => c.previewMaster(v)} onCommit={(v) => void c.setMaster({ volume: v })} /></div>
          </div>
          <div className="whole-mid" style={{ gridTemplateColumns: cols }}>
            {song.sections.map((s) => {
              const from = s.startBar, to = s.endBar
              return (
                <div key={s.id} className="wsec">
                  <span className="wname">{s.label} <small>{to - from} bars</small></span>
                  <span className="wbars" aria-hidden="true">{bars.slice(from, to).map((v, i) => <span key={i} style={{ height: 4 + Math.round(v * 26) }} />)}</span>
                </div>
              )
            })}
            <div className="playhead" style={{ left: `${pct}%` }} />
          </div>
          <div className="whole-right">
            <span className="muted12">Space</span>
            <div role="radiogroup" aria-label="Space" className="space">
              {cat.spaces.map((sp) => (
                <button key={sp.id} type="button" role="radio" aria-checked={song.master.space === sp.id} className={song.master.space === sp.id ? 'on' : ''} onClick={() => void c.setMaster({ space: sp.id as never })}>{sp.label}</button>
              ))}
            </div>
          </div>
        </section>

        <section aria-label="Each player" className="rows">
          {TRACKS.map((tk) => {
            const m = song.tracks[tk.id]
            const dim = m.muted || (solo !== null && solo !== tk.id)
            return (
              <div key={tk.id} className="row6" style={{ opacity: dim ? 0.4 : 1 }}>
                <div className="rhead">
                  <span className="rcolor" style={{ background: tk.color }} />
                  <span className="rname"><b>{tk.name}</b><small>{instrumentLabel(cat, tk.id, m.instrument)}</small></span>
                  <button type="button" className={`sq ${m.muted ? 'on' : ''}`} aria-pressed={m.muted} aria-label={`Mute ${tk.name.toLowerCase()}`} onClick={() => void c.toggleMute(tk.id)}>M</button>
                  <button type="button" className={`sq solo ${solo === tk.id ? 'on' : ''}`} aria-pressed={solo === tk.id} aria-label={`Solo ${tk.name.toLowerCase()}`} onClick={() => c.toggleSolo(tk.id)}>S</button>
                </div>
                <div className="cells" style={{ gridTemplateColumns: cols }}>
                  {song.sections.map((s) => {
                    const r = regionOf(song, tk.id, s.id)
                    const on = r?.play !== false
                    const isSel = track === tk.id && sec.id === s.id
                    return (
                      <button key={s.id} type="button" aria-pressed={isSel} aria-label={`${tk.name}·${s.label}`} className={`cell ${isSel ? 'sel' : ''} ${on ? '' : 'off'}`} onClick={() => c.selectRegion(tk.id, s.id)}>
                        {!on && <span className="empty">silent</span>}
                        {on && marksFor(song, tk.id, s.id).map((mk, i) => <span key={i} className="mark" style={{ left: `${mk.l}%`, width: `${mk.w}%`, top: mk.t, height: mk.h, background: tk.color }} />)}
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </section>

        <section aria-label="How this section is played" className="editor">
          <div className="padcol">
            <div className="muted13">{words[1]}</div>
            <div role="group" aria-label="Complexity and intensity" className="pad">
              {Array.from({ length: 9 }, (_, i) => {
                const col = i % 3, row = Math.floor(i / 3)
                const on = col === padCol && row === padRow
                return (
                  <button key={i} type="button" aria-pressed={on} aria-label={`${rowWord(row)}、${colWord(col)}`} onClick={() => void c.setRegion(track, sec.id, { complexity: [0.15, 0.5, 0.85][col], intensity: [0.85, 0.5, 0.15][row] })}>
                    {on ? <span className="dot on" style={{ background: t.color }} /> : <span className="dot" />}
                  </button>
                )
              })}
            </div>
            <div className="muted13 between"><span>{words[2]}</span><span>{words[0]} · {words[3]}</span></div>
          </div>
          <div className="edcol">
            <div className="ed-head"><h2>{t.name} · {sec.label}</h2><span className="muted13">Move the dot right for {words[3]}, up for {words[1]}; this section only</span></div>
            <div>
              <div className="muted13 mb">{STYLE_TITLE[track]}</div>
              <div role="radiogroup" aria-label={STYLE_TITLE[track]} className="chips">
                {(cat.styles[track] ?? []).map((st) => (
                  <button key={st.id} type="button" role="radio" aria-checked={region?.style === st.id} className={`chip ${region?.style === st.id ? 'on' : ''}`} onClick={() => void c.setRegion(track, sec.id, { style: st.id })}>{st.label}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="muted13 mb">Sound (whole track)</div>
              <div className="chips">
                {(cat.instruments[track] ?? []).map((it) => (
                  <button key={it.id} type="button" aria-pressed={tr.instrument === it.id} className={`chip rect ${tr.instrument === it.id ? 'on' : ''}`} onClick={() => void c.setInstrument(track, it.id)}>{it.label}</button>
                ))}
              </div>
            </div>
          </div>
          <div className="actcol">
            <button type="button" className="whitebtn" onClick={() => void c.another(sec.id, track)}>Play it again</button>
            <button type="button" className="outline" onClick={() => void c.copyRegion(track, sec.id)}>Same in every section</button>
            {(track === 'vocal' || track === 'melody') && hasMotif && <button type="button" className="outline" onClick={() => void c.revertMelody(sec.id)}>Back to my hum</button>}
            {shiftable && (
              <div className="row2">
                <button type="button" className="outline" onClick={() => void c.shiftRegister(track, sec.id, 'down')}>Lower</button>
                <button type="button" className="outline" onClick={() => void c.shiftRegister(track, sec.id, 'up')}>Higher</button>
              </div>
            )}
            <button type="button" className="outline mutedtext" style={{ marginTop: 'auto' }} onClick={() => void c.setRegion(track, sec.id, { play: region?.play === false })}>{region?.play === false ? 'Play in this section' : 'Silent in this section'}</button>
          </div>
        </section>
      </main>
    </>
  )
}
