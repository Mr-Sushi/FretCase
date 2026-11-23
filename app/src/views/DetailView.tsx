import { useEffect, useState, type ReactNode } from 'react'
import { useApp, useSel } from '../app/context'
import { AXIS_TITLE, instrumentLabel, PAD_WORDS, STYLE_HELP, STYLE_TITLE, styleLabel } from '../lib/catalog'
import { sectionLines } from '../lib/lyrics'
import { barTicks, noteName, regionOf, sectionRange, songTicks, TRACKS } from '../lib/song'
import type { Note, Section, Song, TrackId, VocalNote } from '../types'
import { SoundPicker } from './ShapeView'
import { SubHeader } from './SubHeader'
import { BarSlider, PlayIcon } from './ui'

interface Mark { l: number; w: number; t: number; h: number }
/** The small picture of what a player does in a section: one mark per note. */
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
  const tall = track === 'vocal' ? 14 : 22 // the voice leaves room for its words
  for (const n of notes) {
    const key = n.start * 1000 + (track === 'guitar' ? 0 : n.pitch)
    if (seen.has(key)) continue
    seen.add(key)
    const l = ((n.start - from) / len) * 100
    if (track === 'guitar') out.push({ l, w: 0.9, t: 6, h: 28 })
    else if (track === 'drums') out.push({ l, w: 1.1, t: n.pitch === 36 ? 26 : n.pitch === 38 ? 16 : 8, h: n.pitch === 42 ? 4 : 6 })
    else out.push({ l, w: Math.max(0.8, (n.duration / len) * 100 * 0.85), t: 5 + (hi === lo ? tall / 2 : (1 - (n.pitch - lo) / (hi - lo)) * tall), h: 5 })
    if (out.length > 90) break
  }
  return out
}

/** The chords that sound in each bar of a section (the shape under the capo when there is one). */
function chordsByBar(song: Song, sec: Section, shapes: boolean): string[][] {
  const bt = barTicks(song.meter)
  return Array.from({ length: sec.endBar - sec.startBar }, (_, i) => {
    const from = (sec.startBar + i) * bt, to = from + bt
    const inBar = song.harmony.filter((c) => c.start < to && c.start + c.duration > from)
    const names = inBar.map((c) => (shapes && c.shapeSymbol) || c.symbol)
    return names.filter((n, k) => k === 0 || n !== names[k - 1])
  })
}

const DRUM_LANES: { name: string; keys: number[] }[] = [
  { name: 'Cymbals', keys: [42, 44, 46, 49, 51, 52, 53, 55, 57, 59] },
  { name: 'Snare', keys: [37, 38, 39, 40] },
  { name: 'Kick', keys: [35, 36, 41, 43] },
]
const pitchLetter = (p: number) => noteName(p).replace(/-?\d+$/, '')

/**
 * The notes one player plays in one section, large enough to read: bars and chords across the top, each note a
 * block (higher on the page is higher in pitch), and under the notes what each one is: the syllable it sings for
 * the voice, the note name for the melody and the bass. The block that is sounding lights up.
 */
function NoteView({ song, track, sec, pos, playing }: { song: Song; track: TrackId; sec: Section; pos: number; playing: boolean }) {
  const { from, to } = sectionRange(song, sec)
  const len = to - from
  const nb = sec.endBar - sec.startBar
  const chords = chordsByBar(song, sec, track === 'guitar')
  const region = regionOf(song, track, sec.id)
  const notes = track === 'ambience' ? [] : (song.tracks[track].notes as Note[]).filter((n) => n.start >= from && n.start < to).sort((a, b) => a.start - b.start || a.pitch - b.pitch)
  const x = (tick: number) => ((tick - from) / len) * 100
  const sounding = (n: Note) => playing && pos >= n.start && pos < n.start + n.duration
  const head = pos >= from && pos < to ? x(pos) : null
  let body: ReactNode
  let labels: { l: number; text: string; on: boolean }[] = []
  if (region?.play === false) {
    body = <div className="nv-empty">Silent in this section</div>
  } else if (track === 'ambience') {
    body = <div className="nv-amb"><span>The sound you recorded plays underneath the whole section</span></div>
  } else if (!notes.length) {
    body = <div className="nv-empty">No notes here</div>
  } else if (track === 'drums') {
    body = (
      <>
        {DRUM_LANES.map((lane, i) => (
          <div key={lane.name} className="nv-lane" style={{ top: `${i * 33.3}%`, height: '33.3%' }}>
            <span className="nv-lane-name">{lane.name}</span>
            {notes.filter((n) => lane.keys.includes(n.pitch)).map((n, k) => {
              const size = 7 + Math.round(((('velocity' in n && n.velocity) || 90) / 127) * 9)
              return <span key={k} className={`nv-hit ${sounding({ ...n, duration: 90 }) ? 'now' : ''}`} style={{ left: `${x(n.start)}%`, width: size, height: size }} />
            })}
          </div>
        ))}
      </>
    )
  } else {
    const lo = Math.min(...notes.map((n) => n.pitch)), hi = Math.max(...notes.map((n) => n.pitch))
    const span = Math.max(4, hi - lo)
    const h = Math.max(7, Math.min(16, 100 / (span + 1)))
    const top = (p: number) => (1 - (p - lo) / span) * (100 - h)
    if (track === 'guitar') {
      // Notes struck together are one strum: a stroke from its lowest string to its highest. Single notes stay dots.
      // (a strum is spread over a few ticks, string after string, so "together" means within a thirty-second note)
      const groups = new Map<number, Note[]>()
      let at = -1e9
      for (const n of notes) {
        if (n.start - at > 60) at = n.start
        groups.set(at, [...(groups.get(at) ?? []), n])
      }
      body = (
        <>
          {[...groups.entries()].map(([start, g]) => {
            const hiP = Math.max(...g.map((n) => n.pitch)), loP = Math.min(...g.map((n) => n.pitch))
            const now = g.some(sounding)
            return g.length >= 3
              ? <span key={start} className={`nv-strum ${now ? 'now' : ''}`} style={{ left: `${x(start)}%`, top: `${top(hiP)}%`, height: `${top(loP) - top(hiP) + h}%` }} />
              : g.map((n, k) => <span key={`${start}-${k}`} className={`nv-pick ${sounding(n) ? 'now' : ''}`} style={{ left: `${x(start)}%`, top: `calc(${top(n.pitch) + h / 2}% - 5px)` }} />)
          })}
        </>
      )
    } else {
      body = (
        <>
          {notes.map((n, k) => (
            <span key={k} className={`nv-note ${sounding(n) ? 'now' : ''}`} style={{ left: `${x(n.start)}%`, width: `calc(${Math.max(0.6, (n.duration / len) * 100)}% - 2px)`, top: `${top(n.pitch)}%`, height: `${h}%` }} />
          ))}
        </>
      )
    }
    if (track === 'vocal') labels = notes.map((n) => ({ l: x(n.start), text: ((n as VocalNote).lyric ?? '').replace(/-$/, '‑'), on: sounding(n) }))
    else if (track !== 'guitar') {
      const seen = new Set<number>()
      labels = notes.filter((n) => !seen.has(n.start) && !!seen.add(n.start)).map((n) => ({ l: x(n.start), text: pitchLetter(n.pitch), on: sounding(n) }))
    }
  }
  const caption = track === 'vocal' ? 'words' : track === 'guitar' ? '' : track === 'drums' || track === 'ambience' ? '' : 'notes'
  return (
    <div className="noteview" role="img" aria-label={`${TRACKS.find((t) => t.id === track)!.name} in the ${sec.label.toLowerCase()}: ${notes.length} notes over ${nb} bars`}>
      <div className="nv-bars" style={{ gridTemplateColumns: `repeat(${nb}, 1fr)` }}>
        {chords.map((c, i) => <span key={i}><small>bar {sec.startBar + i + 1}</small><b>{c.join('  ')}</b></span>)}
      </div>
      <div className="nv-roll">
        {Array.from({ length: nb - 1 }, (_, i) => <span key={i} className="nv-barline" style={{ left: `${((i + 1) / nb) * 100}%` }} />)}
        {body}
        {head !== null && <span className="nv-head" style={{ left: `${head}%` }} />}
      </div>
      {labels.length > 0 && (
        <div className="nv-labels" aria-hidden="true">
          <span className="nv-cap">{caption}</span>
          {labels.map((l, i) => <span key={i} className={l.on ? 'now' : ''} style={{ left: `${l.l}%` }}>{l.text}</span>)}
        </div>
      )}
    </div>
  )
}

/** Three steps of "how much", drawn so the choice can be read without the words: more dots, or taller bars. */
function Steps({ title, low, high, value, kind, onPick }: { title: string; low: string; high: string; value: number; kind: 'dots' | 'bars'; onPick: (step: number) => void }) {
  const words = [low, 'medium', high]
  return (
    <div className="ctl">
      <div className="ctl-label">{title}: <b>{words[value]}</b></div>
      <div role="radiogroup" aria-label={title} className="optgroup glyphs">
        {[0, 1, 2].map((i) => (
          <button key={i} type="button" role="radio" aria-checked={value === i} aria-label={words[i]} className={value === i ? 'on' : ''} onClick={() => onPick(i)}>
            {kind === 'dots'
              ? <span className="g-dots">{Array.from({ length: [2, 4, 7][i] }, (_, k) => <i key={k} />)}</span>
              : <span className="g-bars">{[0, 1, 2].map((k) => <i key={k} className={k <= i ? 'lit' : ''} style={{ height: 6 + k * 6 }} />)}</span>}
          </button>
        ))}
      </div>
    </div>
  )
}

export function DetailView() {
  const { c } = useApp()
  const song = useSel((s) => s.song)
  const cat = useSel((s) => s.catalog)
  const selTrack = useSel((s) => s.selectedTrack)
  const selSection = useSel((s) => s.editSection)
  const solo = useSel((s) => s.solo)
  const pos = useSel((s) => s.positionTick)
  const playing = useSel((s) => s.playing)
  /** What the last change did, in words, until another player or section is chosen. */
  const [changed, setChanged] = useState<string | null>(null)
  useEffect(() => { if (!selTrack) c.selectTrack('guitar') }, [selTrack, c])
  useEffect(() => { setChanged(null) }, [selTrack, selSection, song?.id])
  if (!song) return null
  const track = selTrack ?? 'guitar'
  const sec = song.sections.find((s) => s.id === selSection) ?? song.sections[0]
  const region = regionOf(song, track, sec.id)
  const t = TRACKS.find((x) => x.id === track)!
  const cols = song.sections.map((s) => `${s.endBar - s.startBar}fr`).join(' ')
  const words = PAD_WORDS[track]
  const busy = region ? (region.complexity < 0.34 ? 0 : region.complexity < 0.67 ? 1 : 2) : 1
  const loud = region ? (region.intensity < 0.34 ? 0 : region.intensity < 0.67 ? 1 : 2) : 1
  const hasMotif = !!song.seed?.motif?.length
  const shiftable = track !== 'drums' && track !== 'ambience'
  const silent = region?.play === false
  const pct = Math.min(100, (pos / songTicks(song)) * 100)
  const where = `the ${sec.label.toLowerCase()}`
  const plural = track === 'drums'
  const who = `The ${t.name.toLowerCase()}`
  const verb = plural ? 'are' : 'is'
  const plays = plural ? 'play' : 'plays'

  /** Makes a change, says what it did, and plays the section so it can be heard straight away. */
  const change = async (what: string, run: () => Promise<unknown> | null | undefined) => {
    await run()
    setChanged(what)
    if (!c.store.state.playing) void c.hearRegion(c.store.state.solo)
  }
  const pickStyle = (id: string) => change(`${who} ${verb} now set to “${styleLabel(cat, track, id).toLowerCase()}” in ${where}: ${(STYLE_HELP[track][id] ?? '').toLowerCase()}.`, () => c.setRegion(track, sec.id, { style: id }))
  const style = region?.style ?? ''

  const soloed = solo === track
  const help = STYLE_HELP[track][style]
  const reading = track === 'vocal' ? 'Each note sings one syllable.'
    : track === 'guitar' ? 'A tall stroke is a strum across the strings; single dots are single strings.'
    : track === 'drums' ? 'Each dot is a hit; bigger dots are louder.'
    : track === 'ambience' ? '' : 'Higher blocks are higher notes; longer blocks last longer.'

  return (
    <>
      <SubHeader tab="tracks" extra={
        <>
          <label className="topvol"><span>Volume</span><BarSlider value={song.master.volume} color="#D4AE6A" label="Master volume" onInput={(v) => c.previewMaster(v)} onCommit={(v) => void c.setMaster({ volume: v })} /></label>
          <span className="topecho"><span>Echo</span>
            <span role="radiogroup" aria-label="Room echo" className="optgroup">
              {cat.spaces.map((sp) => (
                <button key={sp.id} type="button" role="radio" aria-checked={song.master.space === sp.id} className={song.master.space === sp.id ? 'on' : ''} onClick={() => void c.setMaster({ space: sp.id as never })}>{sp.label}</button>
              ))}
            </span>
          </span>
        </>
      } />
      <main className="detail" style={{ '--tc': t.color } as React.CSSProperties}>
        <section aria-label="Each player, section by section" className="score">
          <div className="score-in">
            <div className="srow shead">
              <div className="rhead tip">Tap a part to see its notes and change how it is played.</div>
              <div className="cells" style={{ gridTemplateColumns: cols }}>
                {song.sections.map((s) => {
                  const chords = chordsByBar(song, s, false)
                  return (
                    <div key={s.id} className={`sec ${s.id === sec.id ? 'sel' : ''}`}>
                      <span className="secname">{s.label}</span>
                      <span className="secchords" aria-label={`Chords in the ${s.label.toLowerCase()}`} style={{ gridTemplateColumns: `repeat(${chords.length}, 1fr)` }}>{chords.map((ch, i) => <span key={i}>{ch.join(' ')}</span>)}</span>
                    </div>
                  )
                })}
              </div>
            </div>
            {TRACKS.map((tk) => {
              const m = song.tracks[tk.id]
              const dim = m.muted || (solo !== null && solo !== tk.id)
              return (
                <div key={tk.id} className={`srow ${dim ? 'dim' : ''}`} style={{ '--rc': tk.color } as React.CSSProperties}>
                  <div className="rhead">
                    <span className="rcolor" />
                    <span className="rname"><b>{tk.name}</b><small>{instrumentLabel(cat, tk.id, m.instrument)}</small></span>
                    <button type="button" className={`mutebtn ${m.muted ? 'on' : ''}`} aria-pressed={m.muted} aria-label={`Mute ${tk.name.toLowerCase()}`} onClick={() => void c.toggleMute(tk.id)}>
                      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M3 7h2.5L9 4v10l-3.5-3H3z" fill="currentColor" />{m.muted ? <path d="M12 6.5l4 5M16 6.5l-4 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /> : <path d="M11.5 6.5a3.5 3.5 0 010 5M13.3 4.6a6 6 0 010 8.8" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />}</svg>
                    </button>
                  </div>
                  <div className="cells lane" style={{ gridTemplateColumns: cols }}>
                    {song.sections.map((s) => {
                      const r = regionOf(song, tk.id, s.id)
                      const on = r?.play !== false
                      const isSel = track === tk.id && sec.id === s.id
                      const sung = tk.id === 'vocal' && on ? sectionLines(song, s.id).map((l) => l.text).join(' / ') : ''
                      return (
                        <button key={s.id} type="button" aria-pressed={isSel} aria-label={`${tk.name}·${s.label}${on ? '' : ', silent'}`} className={`cell ${isSel ? 'sel' : ''} ${on ? '' : 'off'}`} onClick={() => c.selectRegion(tk.id, s.id)}>
                          {on && marksFor(song, tk.id, s.id).map((mk, i) => <span key={i} className="mark" style={{ left: `${mk.l}%`, width: `${mk.w}%`, top: mk.t, height: mk.h }} />)}
                          {sung && <span className="sung">{sung}</span>}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )
            })}
            <div className="playhead" style={{ left: `calc(var(--headw) + (100% - var(--headw)) * ${pct / 100})` }} />
          </div>
        </section>

        <section aria-label="How this part is played" className="editor">
          <div className="ed-head">
            <div className="ed-title">
              <h2>{t.name} in the {sec.label.toLowerCase()}</h2>
              <p role="status">{changed ?? <>{help ? `${styleLabel(cat, track, style)}: ${help.toLowerCase()}. ` : ''}{reading}{track === 'vocal' && <> <button type="button" className="linkbtn inline" onClick={() => c.setView('lyrics')}>Change the words</button></>}</>}</p>
            </div>
            <button type="button" className={`hearbtn ${soloed && playing ? 'on' : ''}`} onClick={() => void c.hearRegion(track)}><PlayIcon size={11} color="currentColor" /> Hear it alone</button>
            <button type="button" className={`hearbtn ${!solo && playing ? 'on' : ''}`} onClick={() => void c.hearRegion(null)}><PlayIcon size={11} color="currentColor" /> With everyone</button>
          </div>
          <div className="ed-body">
            <div className="edmain">
              <NoteView song={song} track={track} sec={sec} pos={pos} playing={playing} />
              <div className="edctl">
                <div className="ctl grow">
                  <div className="ctl-label">{STYLE_TITLE[track]}</div>
                  <div role="radiogroup" aria-label={STYLE_TITLE[track]} className="optgroup">
                    {(cat.styles[track] ?? []).map((st) => (
                      <button key={st.id} type="button" role="radio" aria-checked={style === st.id} className={style === st.id ? 'on' : ''} onClick={() => void pickStyle(st.id)}>{st.label}</button>
                    ))}
                  </div>
                </div>
                <Steps title={AXIS_TITLE[track][0]} low={words[2]} high={words[3]} value={busy} kind="dots"
                  onPick={(i) => void change(`${who} ${verb} now ${[words[2], 'medium', words[3]][i]} in ${where}.`, () => c.setRegion(track, sec.id, { complexity: [0.15, 0.5, 0.85][i] }))} />
                <Steps title={AXIS_TITLE[track][1]} low={words[0]} high={words[1]} value={loud} kind="bars"
                  onPick={(i) => void change(`${who} ${verb} now ${[words[0], 'medium', words[1]][i]} in ${where}.`, () => c.setRegion(track, sec.id, { intensity: [0.15, 0.5, 0.85][i] }))} />
                <div className="ctl ctl-sound">
                  <div className="ctl-label">Instrument, whole song</div>
                  <SoundPicker track={track} up onPick={(id) => void change(`${who} ${verb} now played on ${instrumentLabel(cat, track, id).toLowerCase()}, in the whole song.`, () => c.setInstrument(track, id))} />
                </div>
              </div>
            </div>
            <div className="actcol">
              <button type="button" className="act primary" onClick={() => void change(`${who} ${plays} a new version in ${where}, with the same settings. Undo brings the old one back.`, () => c.another(sec.id, track))}>Try another version</button>
              <button type="button" className="act" onClick={() => void change(`${who} now ${plays} this way in every section.`, () => c.copyRegion(track, sec.id))}>Use in every section</button>
              {(track === 'vocal' || track === 'melody') && hasMotif && <button type="button" className="act" onClick={() => void change(`The tune you hummed is back in ${where}.`, () => c.revertMelody(sec.id))}>Back to my hum</button>}
              {shiftable && (
                <div className="row2">
                  <button type="button" className="act" onClick={() => void change(`${who} ${verb} lower in ${where}.`, () => c.shiftRegister(track, sec.id, 'down'))}>Lower</button>
                  <button type="button" className="act" onClick={() => void change(`${who} ${verb} higher in ${where}.`, () => c.shiftRegister(track, sec.id, 'up'))}>Higher</button>
                </div>
              )}
              <button type="button" className="act quiet" onClick={() => void change(silent ? `${who} ${plays} in ${where} again.` : `${who} ${verb} silent in ${where}.`, () => c.setRegion(track, sec.id, { play: silent }))}>{silent ? 'Play in this section' : 'Make it silent here'}</button>
            </div>
          </div>
        </section>
      </main>
    </>
  )
}
