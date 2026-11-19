import { useEffect, useRef, useState } from 'react'
import { StepHeader } from '../App'
import { useApp, useSel } from '../app/context'
import type { CardStyle } from '../types'
import { CARD_STYLE_ORDER } from '../app/controller'

const STYLE_NAME: Record<CardStyle, string> = { original: '原图', xieyi: '写意', comic: '漫画', ink: '水墨', text: '只有字' }
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
  // The last photo cover, so switching back from 只有字 to a picture style keeps the user's choice.
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
  const chip = printer ? (out ? '相纸用完了' : printer.kind === 'dry_run' ? '试印模式，不出纸' : printer.remaining != null ? `相纸还剩 ${printer.remaining} 张` : printer.connected ? '打印机已连接' : '打印机没连上') : '正在看打印机'
  const styles = (hasPhotos ? CARD_STYLE_ORDER : (['text'] as CardStyle[]))
  return (
    <>
      <StepHeader right={<span className={`pill ${out ? 'bad' : ''}`}>{chip}</span>} />
      <main className="cardscreen">
        <section aria-label="卡片预览" className="cardprev">
          <div className="muted14">印出来就是这样（拍立得宽幅相纸，108 × 86 毫米）</div>
          <div className="paper">
            {front ? <img src={c.api.assetUrl(front)} alt="卡片预览：上面是风格化的照片，下面的留白里是歌名、一句话、城市和日期，右边是带音符的二维码" /> : <div className="drawing">{busy ? '正在画预览…' : '预览会在这里出现'}</div>}
            {front && busy && <div className="refresh">更新中…</div>}
          </div>
          {pageHref && (
            <a href={pageHref} target="_blank" rel="noreferrer" className="pagelink">
              {cover ? <img src={c.api.assetUrl(cover)} alt="" /> : <span className="pl-ph">字</span>}
              <span className="grow"><b>扫码打开的歌曲页</b><span className="muted13">这首歌、真实照片、城市和你的留言</span></span>
              <span className="gold14">看看</span>
            </a>
          )}
        </section>

        <aside aria-label="卡片内容" className="cardside">
          {hasPhotos && (
            <div>
              <div className="b15">封面<span className="muted13 f400">（{photos.length} 张照片里选一张印在卡上，其余在歌曲页）</span></div>
              <div role="radiogroup" aria-label="封面照片" className="covers">
                {photos.map((id, i) => (
                  <button key={id} type="button" role="radio" aria-checked={cover === id} aria-label={`第 ${i + 1} 张`} className={cover === id ? 'on' : ''} disabled={card.style === 'text'} onClick={() => void c.setCard({ coverAssetId: id })}>
                    <img src={c.api.assetUrl(id)} alt="" />
                  </button>
                ))}
              </div>
            </div>
          )}
          <div>
            <div className="b15">画风</div>
            <div role="radiogroup" aria-label="画风" className="styles5">
              {styles.map((st) => (
                <button key={st} type="button" role="radio" aria-checked={card.style === st} className={card.style === st ? 'on' : ''} onClick={() => void c.setCard(st !== 'text' && !cover && lastCover.current ? { style: st, coverAssetId: lastCover.current } : { style: st })}>
                  {st === 'text' || !thumb ? <span className="sty-ph">字</span> : <img src={c.api.assetUrl(thumb)} alt="" style={{ filter: STYLE_FILTER[st] }} />}
                  <span>{STYLE_NAME[st]}</span>
                </button>
              ))}
            </div>
          </div>
          <label className="field"><span className="b15">歌名</span>
            <input value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} onBlur={() => { if (title.trim() && title !== song.title) { void c.setTitle(title.trim()).then(() => c.schedulePreview()) } }} />
          </label>
          <label className="field"><span className="b15">卡片上的一句</span>
            <input value={line} maxLength={60} onChange={(e) => setLine(e.target.value)} onBlur={() => { if (line !== (card.line ?? '')) void c.setCard({ line }) }} />
          </label>
          <label className="field"><span className="b15">想对听的人说<span className="muted13 f400">（只在歌曲页显示）</span></span>
            <textarea value={msg} maxLength={500} onChange={(e) => setMsg(e.target.value)} onBlur={() => { if (msg !== (card.message ?? '')) void c.setCard({ message: msg }) }} />
          </label>
          <div className="toggles">
            <div className="cityrow">
              <Toggle label={`显示城市和日期（${date}）`} on={!!card.city && card.showCity} disabled={!card.city} onFlip={() => void c.setCard({ showCity: !card.showCity })} />
              <input aria-label="城市" placeholder="写城市" value={city} maxLength={60} onChange={(e) => setCity(e.target.value)} onBlur={() => { const v = city.trim(); if (v !== (card.city ?? '')) void c.setCard(v ? { city: v, showCity: true } : { showCity: false }) }} />
            </div>
            <Toggle label="歌曲页显示真实照片" on={hasPhotos && card.showPhoto} disabled={!hasPhotos} onFlip={() => void c.setCard({ showPhoto: !card.showPhoto })} />
          </div>
          <div className="printbox">
            <button type="button" className="gobtn" disabled={busy || out || offline} onClick={() => void c.printCard()}>印出来</button>
            <div className="muted13 center">{out ? '相纸用完了，换一盒再印' : offline ? '打印机没连上：打开打印机，靠近箱子' : '约 15 秒，从箱子侧面的出卡口出来；也可以按住箱子上的红键约 1 秒'}</div>
          </div>
        </aside>
      </main>
    </>
  )
}
