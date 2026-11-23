import { useEffect, useRef, useState } from 'react'
import { StepHeader } from '../App'
import { useApp, useSel } from '../app/context'
import type { CardStyle } from '../types'
import { CARD_STYLE_ORDER } from '../app/controller'

const STYLE_NAME: Record<CardStyle, string> = { original: 'Original', xieyi: 'Painterly', comic: 'Comic', ink: 'Ink', text: 'Words only' }
const STYLE_FILTER: Record<CardStyle, string> = {
  original: 'none', xieyi: 'saturate(1.2) contrast(0.9) sepia(0.25) blur(0.6px)', comic: 'saturate(1.8) contrast(1.5)', ink: 'grayscale(1) contrast(1.4)', text: 'none',
}

function Toggle({ label, on, disabled, onFlip }: { label: string; on: boolean; disabled?: boolean; onFlip: () => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} disabled={disabled} className="switch" onClick={onFlip}>
      <span className="track" style={{ background: on ? '#D4AE6A' : '#4A3A2D' }}><span style={{ left: on ? 21 : 3 }} /></span>
      <span>{label}</span>
    </button>
  )
}

export function CardView() {
  const { c } = useApp()
  const song = useSel((s) => s.song)
  const printer = useSel((s) => s.printer)
  const busy = useSel((s) => s.cardBusy)
  const [title, setTitle] = useState('')
  const [line, setLine] = useState('')
  const [msg, setMsg] = useState('')
  const [city, setCity] = useState('')
  // The last photo cover, so switching back from words-only to a picture style keeps the user's choice.
  const lastCover = useRef<string | undefined>(undefined)
  useEffect(() => { if (song) { setTitle(song.title); setLine(song.card?.line ?? ''); setMsg(song.card?.message ?? ''); setCity(song.card?.city ?? '') } }, [song?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!song?.card) return null
  const card = song.card
  const photos = (card.photoAssetIds ?? []) as string[]
  const hasPhotos = photos.length > 0
  const cover = card.coverAssetId
  if (cover) lastCover.current = cover
  const thumb = cover ?? lastCover.current ?? photos[0]
  const front = card.frontAssetId
  const date = (card.capturedAt ?? song.createdAt).slice(0, 10).replace(/-/g, '.')
  const shareId = card.share?.shareId
  const pageHref = shareId ? (c.api.mock ? `song.html?mock=1&share=${shareId}` : `/s/${shareId}`) : undefined
  const out = printer?.paper === 'out' || printer?.remaining === 0
  const offline = !!printer && !printer.connected
  const chip = printer ? (out ? 'Out of film' : printer.kind === 'dry_run' ? 'Test mode, no film used' : printer.remaining != null ? `${printer.remaining} sheets of film left` : printer.connected ? 'Printer connected' : 'Printer not connected') : 'Checking the printer'
  const styles = (hasPhotos ? CARD_STYLE_ORDER : (['text'] as CardStyle[]))
  return (
    <>
      <StepHeader right={<span className={`pill ${out ? 'bad' : ''}`}>{chip}</span>} />
      <main className="cardscreen">
        <section aria-label="Card preview" className="cardprev">
          <div className="muted14">This is how it prints (Instax Wide film, 108 × 86 mm)</div>
          <div className="paper">
            {front ? <img src={c.api.assetUrl(front)} alt="Card preview: a styled photo on top; below it the song title, a line, the city and the date, with a QR code made of notes on the right" /> : <div className="drawing">{busy ? 'Drawing the preview…' : 'The preview will appear here'}</div>}
            {front && busy && <div className="refresh">Updating…</div>}
          </div>
          {pageHref && (
            <a href={pageHref} target="_blank" rel="noreferrer" className="pagelink">
              {cover ? <img src={c.api.assetUrl(cover)} alt="" /> : <span className="pl-ph">Aa</span>}
              <span className="grow"><b>The song page the QR code opens</b><span className="muted13">The song, the real photos, the city and your message</span></span>
              <span className="gold14">Look</span>
            </a>
          )}
        </section>

        <aside aria-label="Card content" className="cardside">
          {hasPhotos && (
            <div>
              <div className="b15">Cover<span className="muted13 f400"> (one of {photos.length} photos goes on the card; the rest are on the song page)</span></div>
              <div role="radiogroup" aria-label="Cover photo" className="covers">
                {photos.map((id, i) => (
                  <button key={id} type="button" role="radio" aria-checked={cover === id} aria-label={`Photo ${i + 1}`} className={cover === id ? 'on' : ''} disabled={card.style === 'text'} onClick={() => void c.setCard({ coverAssetId: id })}>
                    <img src={c.api.assetUrl(id)} alt="" />
                  </button>
                ))}
              </div>
            </div>
          )}
          <div>
            <div className="b15">Style</div>
            <div role="radiogroup" aria-label="Style" className="styles5">
              {styles.map((st) => (
                <button key={st} type="button" role="radio" aria-checked={card.style === st} className={card.style === st ? 'on' : ''} onClick={() => void c.setCard(st !== 'text' && !cover && lastCover.current ? { style: st, coverAssetId: lastCover.current } : { style: st })}>
                  {st === 'text' || !thumb ? <span className="sty-ph">Aa</span> : <img src={c.api.assetUrl(thumb)} alt="" style={{ filter: STYLE_FILTER[st] }} />}
                  <span>{STYLE_NAME[st]}</span>
                </button>
              ))}
            </div>
          </div>
          <label className="field"><span className="b15">Title</span>
            <input value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} onBlur={() => { if (title.trim() && title !== song.title) { void c.setTitle(title.trim()).then(() => c.schedulePreview()) } }} />
          </label>
          <label className="field"><span className="b15">Line on the card</span>
            <input value={line} maxLength={60} onChange={(e) => setLine(e.target.value)} onBlur={() => { if (line !== (card.line ?? '')) void c.setCard({ line }) }} />
          </label>
          <label className="field"><span className="b15">A message for the listener<span className="muted13 f400"> (only on the song page)</span></span>
            <textarea value={msg} maxLength={500} onChange={(e) => setMsg(e.target.value)} onBlur={() => { if (msg !== (card.message ?? '')) void c.setCard({ message: msg }) }} />
          </label>
          <div className="toggles">
            <div className="cityrow">
              <Toggle label={`Show the city and date (${date})`} on={!!card.city && card.showCity} disabled={!card.city} onFlip={() => void c.setCard({ showCity: !card.showCity })} />
              <input aria-label="City" placeholder="City" value={city} maxLength={60} onChange={(e) => setCity(e.target.value)} onBlur={() => { const v = city.trim(); if (v !== (card.city ?? '')) void c.setCard(v ? { city: v, showCity: true } : { showCity: false }) }} />
            </div>
            <Toggle label="Show the real photos on the song page" on={hasPhotos && card.showPhoto} disabled={!hasPhotos} onFlip={() => void c.setCard({ showPhoto: !card.showPhoto })} />
          </div>
          <div className="printbox">
            <button type="button" className="gobtn" disabled={busy || out || offline} onClick={() => void c.printCard()}>Print</button>
            <div className="muted13 center">{out ? 'Out of film. Load a new pack to print' : offline ? 'Printer not connected: turn it on and bring it near the case' : 'About 15 s, out of the side slot. Or hold the red key for a second'}</div>
          </div>
        </aside>
      </main>
    </>
  )
}
