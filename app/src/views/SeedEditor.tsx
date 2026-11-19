import { useApp, useSel } from '../app/context'
import type { SeedCard } from '../types'
import { TRACKS } from '../lib/song'

const TONICS = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
const METERS = [[4, 4], [3, 4], [2, 4], [6, 8]]
const FIELD: Record<string, string> = { key: '调', tempo: '速度', meter: '拍子', mood: '情绪', motif: '旋律', instruments: '音色' }

/** The seed card: what the device understood, each value with its reason and every value editable. */
export function SeedEditor() {
  const { c } = useApp()
  const seed = useSel((s) => s.seed)!
  const catalog = useSel((s) => s.catalog)
  const set = (patch: Partial<SeedCard>) => c.updateSeed({ ...seed, ...patch })
  const meter = seed.meter ?? { numerator: 4, denominator: 4 }
  const reason = (f: string) => seed.reasons.filter((r) => r.field === f).map((r) => r.text)

  return (
    <div className="seed">
      <div className="seed-card">
        <header>
          <h2>种子卡</h2>
          <span className="chip">{seed.source === 'model' ? '模型理解' : '离线规则'}</span>
        </header>

        <div className="seed-row">
          <label>调</label>
          <div className="ctl">
            <select value={seed.key.tonic} onChange={(e) => set({ key: { ...seed.key, tonic: e.target.value } })}>
              {TONICS.map((t) => <option key={t}>{t}</option>)}
            </select>
            <div className="seg">
              {(['major', 'minor'] as const).map((m) => (
                <button key={m} className={seed.key.mode === m ? 'on' : ''} onClick={() => set({ key: { ...seed.key, mode: m } })}>{m === 'major' ? '大调' : '小调'}</button>
              ))}
            </div>
          </div>
          <p className="why">{reason('key').join('；')}</p>
        </div>

        <div className="seed-row">
          <label>速度</label>
          <div className="ctl">
            <input type="range" min={40} max={220} value={seed.tempo} onChange={(e) => set({ tempo: Number(e.target.value) })} />
            <span className="num">{Math.round(seed.tempo)}</span>
          </div>
          <p className="why">{reason('tempo').join('；')}</p>
        </div>

        <div className="seed-row">
          <label>拍子</label>
          <div className="ctl seg">
            {METERS.map(([n, d]) => (
              <button key={`${n}/${d}`} className={meter.numerator === n && meter.denominator === d ? 'on' : ''} onClick={() => set({ meter: { numerator: n as 2 | 3 | 4 | 6, denominator: d as 4 | 8 } })}>{n}/{d}</button>
            ))}
          </div>
          <p className="why">{reason('meter').join('；')}</p>
        </div>

        <div className="seed-row">
          <label>情绪</label>
          <div className="ctl"><input className="mood" maxLength={24} value={seed.mood} onChange={(e) => set({ mood: e.target.value })} /></div>
          <p className="why">{reason('mood').join('；')}</p>
        </div>

        <div className="seed-row">
          <label>旋律</label>
          <div className="ctl">
            <span>{seed.motif?.length ? `哼唱转成了 ${seed.motif.length} 个音` : '没有哼唱，由设备编旋律'}</span>
            {seed.motif?.length ? <button className="btn small ghost" onClick={() => set({ motif: undefined })}>不用哼唱的旋律</button> : null}
          </div>
          <p className="why">{reason('motif').join('；')}</p>
        </div>

        <div className="seed-row">
          <label>音色</label>
          <div className="ctl inst">
            {TRACKS.filter((t) => t.id !== 'ambience' && t.id !== 'vocal').map((t) => {
              const opts = catalog?.instruments[t.id] ?? (seed.instruments?.[t.id] ? [seed.instruments[t.id]] : [])
              return (
                <label key={t.id} className="inst-pick">
                  <span className="swatch" style={{ background: t.color }} />{t.name}
                  <select value={seed.instruments?.[t.id] ?? opts[0] ?? ''} onChange={(e) => set({ instruments: { ...seed.instruments, [t.id]: e.target.value } })}>
                    {opts.map((o) => <option key={o}>{o}</option>)}
                  </select>
                </label>
              )
            })}
          </div>
          <p className="why">{reason('instruments').join('；')}</p>
        </div>
        <details className="reasons">
          <summary>全部来由</summary>
          <ul>{seed.reasons.map((r, i) => <li key={i}><b>{FIELD[r.field] ?? r.field}</b>　{r.text}</li>)}</ul>
        </details>
      </div>
      <div className="seed-actions">
        <button className="btn ghost" onClick={() => c.store.set({ seed: null })}>回去改输入</button>
        <button className="btn primary big" onClick={() => void c.generate()}>确认，生成这首歌</button>
      </div>
    </div>
  )
}
