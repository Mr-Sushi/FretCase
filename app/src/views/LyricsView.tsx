import { lyricsFailureText } from '../app/controller'
import { useEffect, useState } from 'react'
import { useApp, useSel } from '../app/context'
import { countLine, rhymeLabel, rhymeNote, sectionLines } from '../lib/lyrics'
import { PlayIcon, Segmented } from './ui'
import { SubHeader } from './SubHeader'

const SOURCE: Record<string, string> = { photo: 'photo', text: 'your words', sound: 'sound', hum: 'hum' }
const OK = '#9FC98A', WARN = '#F0A07A'

export function LyricsView() {
  const { c } = useApp()
  const song = useSel((s) => s.song)
  const ui = useSel((s) => s.lyrics)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [misfit, setMisfit] = useState<Record<string, boolean>>({})
  // A new song or a rewrite replaces the text: typed drafts that now match the song are dropped.
  useEffect(() => { setDrafts({}); setMisfit({}) }, [song?.id, song?.revision])
  if (!song) return null

  const sections = song.sections.map((s) => ({ s, lines: sectionLines(song, s.id) })).filter((x) => x.lines.length)
  const selLine = ui.selected ? sectionLines(song, ui.selected.section)[ui.selected.index] : undefined
  const key = (sec: string, i: number) => `${sec}:${i}`

  const commit = async (secId: string, lines: { index: number; text: string; noteCount: number }[]) => {
    const texts = lines.map((l) => drafts[key(secId, l.index)] ?? l.text)
    const bad = lines.filter((l, i) => countLine(texts[i], l.noteCount).diff !== 0).map((l) => l.index)
    if (bad.length) { setMisfit((m) => ({ ...m, ...Object.fromEntries(lines.map((l) => [key(secId, l.index), bad.includes(l.index)])) })); return }
    if (!lines.some((l, i) => texts[i] !== l.text)) return
    const r = await c.setSectionLyrics(secId, texts)
    if (r.ok) setDrafts((d) => Object.fromEntries(Object.entries(d).filter(([k]) => !k.startsWith(`${secId}:`))))
  }

  return (
    <>
      <SubHeader tab="lyrics" hint="All the lyrics are here. After a change, tap a line to hear it sung" />
      <main className="lyrics">
        <section aria-label="All lyrics" className="lyr-main">
          {sections.length === 0 && <div className="panel empty-note">This song has no vocal notes yet, so there are no lyrics to write.</div>}
          {sections.map(({ s, lines }) => {
            const texts = lines.map((l) => drafts[key(s.id, l.index)] ?? l.text)
            const note = rhymeNote(texts)
            const keeps = ui.keeps[s.id] ?? []
            return (
              <div key={s.id} className="panel lyr-sec">
                <div className="lyr-sec-head">
                  <h2>{s.label}</h2>
                  <span className="muted13" style={{ color: note.good ? OK : WARN }}>{note.text}</span>
                  <button type="button" className="outline small gold" onClick={() => void c.rewriteLyrics([s.id])}>Rewrite section</button>
                </div>
                {lines.map((l) => {
                  const text = drafts[key(s.id, l.index)] ?? l.text
                  const cnt = countLine(text, l.noteCount)
                  const selected = ui.selected?.section === s.id && ui.selected.index === l.index
                  const bad = !cnt.ok || ui.misfit.includes(key(s.id, l.index)) || misfit[key(s.id, l.index)]
                  const kept = keeps.includes(l.index)
                  const id = `lyr-${s.id}-${l.index}`
                  return (
                    <div key={l.index} className={`lyr-line ${selected ? 'sel' : ''}`}>
                      <button type="button" className="sqbtn" aria-label="Choose this line and listen" onClick={() => c.selectLine(s.id, l.index)}><PlayIcon size={14} color="#D4AE6A" /></button>
                      <label htmlFor={id} className="sr">{s.label} line {l.index + 1}</label>
                      <input
                        id={id} value={text} onChange={(e) => setDrafts((d) => ({ ...d, [key(s.id, l.index)]: e.target.value }))}
                        onBlur={() => void commit(s.id, lines)} onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                        aria-invalid={bad || undefined}
                      />
                      <span className="lcount" style={{ color: bad ? WARN : OK }}>{cnt.label}{'\n'}{cnt.hint}</span>
                      <span className="lrhyme">{rhymeLabel(text)}</span>
                      <button type="button" className={`keepbtn ${kept ? 'on' : ''}`} aria-pressed={kept} onClick={() => c.toggleKeep(s.id, l.index)}>{kept ? 'Kept' : 'Keep'}</button>
                    </div>
                  )
                })}
              </div>
            )
          })}
        </section>

        <aside className="lyr-side">
          <section aria-label="Other wordings" className="panel alt">
            {selLine ? (
              <>
                <h2>Other ways to say “{selLine.text}”</h2>
                <div className="muted13">All {selLine.noteCount} syllables, so the tune stays the same</div>
                {ui.loading && <div className="muted13">Thinking…</div>}
                {ui.alternatives?.map((a) => (
                  <button key={a.text} type="button" className="altbtn" onClick={() => void c.applyAlternative(ui.selected!.section, ui.selected!.index, a.text)}>
                    <span className="grow">{a.text}</span><span className="muted12">{a.note}</span>
                  </button>
                ))}
              </>
            ) : <><h2>Other wordings</h2><div className="muted13">Tap the play key left of a line to see other wordings</div></>}
            {ui.offline && <div className="offnote" role="status">{lyricsFailureText(ui.offlineReason) ?? 'Other wordings need the internet, and there is no connection now'}. You can still edit the words on the left.</div>}
          </section>

          <section aria-label="Rewrite direction" className="panel dir">
            <h2>What this song is about</h2>
            <div className="chips">
              {ui.themes.map((t) => {
                const on = ui.themeSel.includes(t.text)
                return <button key={t.text} type="button" aria-pressed={on} className={`chip sm ${on ? 'on' : ''}`} onClick={() => c.toggleTheme(t.text)}>{t.text}<small>{SOURCE[t.source] ?? ''}</small></button>
              })}
            </div>
            <div><div className="b14">Tone</div>
              <Segmented label="Tone" value={ui.tone} onPick={(v) => c.setTone(v)} options={[{ id: 'plain', label: 'Plain' }, { id: 'subtle', label: 'Subtle' }, { id: 'playful', label: 'Playful' }]} className="round" /></div>
            <div><div className="b14">Rhyme</div>
              <Segmented label="Rhyme" value={ui.rhyme ? 'yes' : 'no'} onPick={(v) => c.setRhyme(v === 'yes')} options={[{ id: 'yes', label: 'Rhyme each section' }, { id: 'no', label: 'No need' }]} className="round" /></div>
            <button type="button" className="gobtn rewrite" disabled={ui.writing} onClick={() => void c.rewriteLyrics()}>{ui.writing ? 'Writing…' : 'Rewrite the lines not kept'}</button>
            {ui.offline && <div className="offnote" role="status">{lyricsFailureText(ui.offlineReason) ?? 'Rewriting needs the internet, and there is no connection now'}. The lyrics stay as they are; you can edit the words yourself.</div>}
            <div className="tiny center">Each line keeps one syllable per note, so it fits the tune</div>
          </section>
        </aside>
      </main>
    </>
  )
}
