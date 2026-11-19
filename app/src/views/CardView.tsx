import { useEffect, useState } from 'react'
import { useApp, useSel } from '../app/context'
import type { CardStyle } from '../types'

const STYLE_NAMES: Record<CardStyle, string> = { ink: '水墨', comic: '漫画', xieyi: '写意', original: '原图', text: '文字' }

/** Card preview: style, line, message, city, whether the real photo and city go on the song page, then print. */
export function CardView() {
  const { c } = useApp()
  const song = useSel((s) => s.song)!
  const catalog = useSel((s) => s.catalog)
  const city0 = useSel((s) => s.city)
  const previewSig = useSel((s) => s.previewSig)
  const busy = useSel((s) => s.busy)
  const card = song.card ?? { style: 'ink' as const, showPhoto: false, showCity: false }
  const styles = (catalog?.cardStyles ?? ['ink', 'comic', 'xieyi', 'original', 'text']) as CardStyle[]
  const hasPhoto = !!card.photoAssetId

  const [line, setLine] = useState(card.line ?? '')
  const [message, setMessage] = useState(card.message ?? '')
  const [city, setCity] = useState(card.city ?? city0)
  const [title, setTitle] = useState(song.title)
  useEffect(() => { setLine(card.line ?? ''); setMessage(card.message ?? ''); setCity(card.city ?? city0); setTitle(song.title) }, [song.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!card.city && city0) setCity(city0) }, [city0, card.city])

  /** Writes the text fields that differ, in one edit, before a preview. */
  const flush = async () => {
    const ops: Parameters<typeof c.edit>[0] = []
    if (title !== song.title && title.trim()) ops.push({ op: 'setTitle', title: title.trim() })
    const patch: Record<string, string> = {}
    if (line !== (card.line ?? '')) patch.line = line
    if (message !== (card.message ?? '')) patch.message = message
    if (city !== (card.city ?? '') && city.trim()) patch.city = city.trim()
    if (Object.keys(patch).length) ops.push({ op: 'setCard', ...patch })
    if (ops.length) await c.edit(ops)
  }

  const fresh = !!card.frontAssetId && previewSig === c.cardSignature(song)
  const dirty = line !== (card.line ?? '') || message !== (card.message ?? '') || (city !== (card.city ?? '') && !!city.trim()) || title !== song.title

  const front = card.frontAssetId ? c.api.assetUrl(card.frontAssetId) : null
  const back = card.backAssetId ? c.api.assetUrl(card.backAssetId) : null
  const photo = card.photoAssetId ? c.api.assetUrl(card.photoAssetId) : null

  return (
    <div className="cardview">
      <section className="cv-form">
        <h2>卡片</h2>
        <div className="field">
          <label>歌名</label>
          <input value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="field">
          <label>风格</label>
          <div className="seg wide">
            {styles.map((s) => (
              <button key={s} className={card.style === s ? 'on' : ''} disabled={!hasPhoto && s !== 'text'} onClick={() => void c.setCard({ style: s })}>{STYLE_NAMES[s]}</button>
            ))}
          </div>
          {!hasPhoto && <div className="hint">没有照片时，卡片正面印歌名或下面这句话。</div>}
        </div>
        <div className="field">
          <label>一句话（没有照片时印在正面）</label>
          <input value={line} maxLength={60} onChange={(e) => setLine(e.target.value)} placeholder="一句和这首歌有关的话" />
        </div>
        <div className="field">
          <label>想对听的人说</label>
          <textarea rows={3} value={message} maxLength={500} onChange={(e) => setMessage(e.target.value)} placeholder="只显示在扫码后的歌曲页" />
        </div>
        <div className="field">
          <label>城市</label>
          <input value={city} maxLength={60} onChange={(e) => setCity(e.target.value)} />
        </div>
        <div className="toggles">
          <label className="check"><input type="checkbox" checked={card.showPhoto} disabled={!hasPhoto} onChange={(e) => void c.setCard({ showPhoto: e.target.checked })} />歌曲页显示真实照片</label>
          <label className="check"><input type="checkbox" checked={card.showCity} onChange={(e) => void c.setCard({ showCity: e.target.checked })} />卡片和歌曲页显示城市</label>
        </div>
      </section>

      <section className="cv-preview">
        <div className="faces">
          <figure>{front ? <img src={front} alt="卡片正面" /> : <div className="blank">正面</div>}<figcaption>正面</figcaption></figure>
          <figure>{back ? <img src={back} alt="卡片背面" /> : <div className="blank">背面</div>}<figcaption>背面（二维码）</figcaption></figure>
          {photo && card.showPhoto && <figure className="real"><img src={photo} alt="真实照片" /><figcaption>歌曲页上的照片</figcaption></figure>}
        </div>
        {card.share && <div className="share">扫码地址 <code>{card.share.url}</code>　<span className="chip">{{ reserved: '已预留', queued: '等待上传', uploaded: '已上传', failed: '上传失败' }[card.share.state]}</span></div>}
        <div className="cv-actions">
          <button className="btn" disabled={!!busy} onClick={async () => { await flush(); await c.previewCard() }}>{front ? '重新预览' : '预览'}</button>
          <button className="btn primary big" disabled={!!busy || !fresh || dirty} onClick={() => void c.printCard()}>
            {card.printedAt ? '再印一张' : '打印'}
          </button>
        </div>
        <div className="hint">
          {!front ? '先预览，满意后才能打印。' : !fresh || dirty ? '内容改过了，请重新预览后再打印。' : card.printedAt ? '已经印出来了。' : '预览和打印的内容一样。'}
        </div>
      </section>
    </div>
  )
}
