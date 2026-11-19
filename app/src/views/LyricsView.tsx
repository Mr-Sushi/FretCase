import { useEffect, useState } from 'react'
import { useApp, useSel } from '../app/context'
import { countLine, rhymeLabel, rhymeNote, sectionLines } from '../lib/lyrics'
import { PlayIcon, Segmented } from './ui'
import { SubHeader } from './SubHeader'

const SOURCE: Record<string, string> = { photo: '照片', text: '你写的', sound: '声音', hum: '哼唱' }
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
      <SubHeader tab="lyrics" hint="整首歌词都在这里，改完点一句就能听到唱出来的样子" />
      <main className="lyrics">
        <section aria-label="整首歌词" className="lyr-main">
          {sections.length === 0 && <div className="panel empty-note">这首歌还没有人声的音，所以没有歌词可写。</div>}
          {sections.map(({ s, lines }) => {
            const texts = lines.map((l) => drafts[key(s.id, l.index)] ?? l.text)
            const note = rhymeNote(texts)
            const keeps = ui.keeps[s.id] ?? []
            return (
              <div key={s.id} className="panel lyr-sec">
                <div className="lyr-sec-head">
                  <h2>{s.label}</h2>
                  <span className="muted13" style={{ color: note.good ? OK : WARN }}>{note.text}</span>
                  <button type="button" className="outline small gold" onClick={() => void c.rewriteLyrics([s.id])}>整段重写</button>
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
                      <button type="button" className="sqbtn" aria-label="选这一句并试听" onClick={() => c.selectLine(s.id, l.index)}><PlayIcon size={14} color="#D4AE6A" /></button>
                      <label htmlFor={id} className="sr">{s.label}第 {l.index + 1} 句</label>
                      <input
                        id={id} value={text} onChange={(e) => setDrafts((d) => ({ ...d, [key(s.id, l.index)]: e.target.value }))}
                        onBlur={() => void commit(s.id, lines)} onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                        aria-invalid={bad || undefined}
                      />
                      <span className="lcount" style={{ color: bad ? WARN : OK }}>{cnt.label}{'\n'}{cnt.hint}</span>
                      <span className="lrhyme">{rhymeLabel(text)}</span>
                      <button type="button" className={`keepbtn ${kept ? 'on' : ''}`} aria-pressed={kept} onClick={() => c.toggleKeep(s.id, l.index)}>{kept ? '已保留' : '保留'}</button>
                    </div>
                  )
                })}
              </div>
            )
          })}
        </section>

        <aside className="lyr-side">
          <section aria-label="换个说法" className="panel alt">
            {selLine ? (
              <>
                <h2>“{selLine.text}”换个说法</h2>
                <div className="muted13">都是 {selLine.noteCount} 个字，不用改旋律</div>
                {ui.loading && <div className="muted13">正在想…</div>}
                {ui.alternatives?.map((a) => (
                  <button key={a.text} type="button" className="altbtn" onClick={() => void c.applyAlternative(ui.selected!.section, ui.selected!.index, a.text)}>
                    <span className="grow">{a.text}</span><span className="muted12">{a.note}</span>
                  </button>
                ))}
              </>
            ) : <><h2>换个说法</h2><div className="muted13">点一句左边的播放键，就能看到别的说法</div></>}
            {ui.offline && <div className="offnote" role="status">换说法需要联网，现在没有网络。可以直接在左边改字。</div>}
          </section>

          <section aria-label="重写的方向" className="panel dir">
            <h2>这首歌在说什么</h2>
            <div className="chips">
              {ui.themes.map((t) => {
                const on = ui.themeSel.includes(t.text)
                return <button key={t.text} type="button" aria-pressed={on} className={`chip sm ${on ? 'on' : ''}`} onClick={() => c.toggleTheme(t.text)}>{t.text}<small>{SOURCE[t.source] ?? ''}</small></button>
              })}
            </div>
            <div><div className="b14">语气</div>
              <Segmented label="语气" value={ui.tone} onPick={(v) => c.setTone(v)} options={[{ id: 'plain', label: '直白' }, { id: 'subtle', label: '含蓄' }, { id: 'playful', label: '俏皮' }]} className="round" /></div>
            <div><div className="b14">押韵</div>
              <Segmented label="押韵" value={ui.rhyme ? 'yes' : 'no'} onPick={(v) => c.setRhyme(v === 'yes')} options={[{ id: 'yes', label: '每段押韵' }, { id: 'no', label: '不强求' }]} className="round" /></div>
            <button type="button" className="gobtn rewrite" onClick={() => void c.rewriteLyrics()}>按这些重写没保留的句子</button>
            {ui.offline && <div className="offnote" role="status">重写需要联网，现在没有网络。歌词不会变，你可以直接改字。</div>}
            <div className="tiny center">字数会跟着旋律走，每一句都和音数一样</div>
          </section>
        </aside>
      </main>
    </>
  )
}
