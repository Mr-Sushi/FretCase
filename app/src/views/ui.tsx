import { useEffect, useRef, useState } from 'react'

/**
 * Range input that shows the finger's value while dragging and reports the final value on release.
 * The song is never patched locally: after the commit the server's song arrives and the prop catches up.
 * The draft is kept until the prop reaches it, so older responses arriving mid-adjustment do not
 * pull the thumb back; if the server settles elsewhere (clamping, a rejected edit) it gives way after 3 s.
 */
export function DraftSlider({ value, min = 0, max = 1, step = 0.01, label, onInput, onCommit }: {
  value: number; min?: number; max?: number; step?: number; label?: string
  onInput?: (v: number) => void; onCommit: (v: number) => void
}) {
  const [draft, setDraft] = useState<number | null>(null)
  const giveUp = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (draft !== null && Math.abs(value - draft) < step / 2) setDraft(null)
  }, [value, draft, step])
  useEffect(() => () => { if (giveUp.current) clearTimeout(giveUp.current) }, [])
  const commit = (v: number) => {
    onCommit(v)
    if (giveUp.current) clearTimeout(giveUp.current)
    giveUp.current = setTimeout(() => setDraft(null), 3000)
  }
  return (
    <input
      type="range" min={min} max={max} step={step} aria-label={label}
      value={draft ?? value}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => { const v = Number(e.target.value); setDraft(v); onInput?.(v) }}
      onPointerUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
      onKeyUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
    />
  )
}

export function PlayIcon({ size = 18, color = '#1C1410' }: { size?: number; color?: string }) {
  return <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true"><path d="M4 2l12 7-12 7z" fill={color} /></svg>
}
export function PauseIcon({ size = 18, color = '#1C1410' }: { size?: number; color?: string }) {
  return <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true"><rect x="3" y="2" width="4" height="14" fill={color} /><rect x="11" y="2" width="4" height="14" fill={color} /></svg>
}

/** A slider drawn as a thin bar with the track's colour; a real range input underneath keeps it touch and keyboard friendly. */
export function BarSlider({ value, color, label, onInput, onCommit }: {
  value: number; color: string; label: string; onInput?: (v: number) => void; onCommit: (v: number) => void
}) {
  const [draft, setDraft] = useState<number | null>(null)
  const giveUp = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => { if (draft !== null && Math.abs(value - draft) < 0.005) setDraft(null) }, [value, draft])
  useEffect(() => () => { if (giveUp.current) clearTimeout(giveUp.current) }, [])
  const shown = draft ?? value
  const commit = (v: number) => {
    onCommit(v)
    if (giveUp.current) clearTimeout(giveUp.current)
    giveUp.current = setTimeout(() => setDraft(null), 3000)
  }
  return (
    <span className="barslider" style={{ ['--c' as string]: color }}>
      <span className="barslider-rail"><span className="barslider-fill" style={{ width: `${Math.round(shown * 100)}%` }} /></span>
      <input
        type="range" min={0} max={1} step={0.01} aria-label={label} value={shown}
        onChange={(e) => { const v = Number(e.target.value); setDraft(v); onInput?.(v) }}
        onPointerUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
        onKeyUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
      />
    </span>
  )
}

/** A pill-shaped choice group (radio semantics). */
export function Segmented<T extends string>({ value, options, onPick, label, className = '' }: {
  value: T; options: { id: T; label: string }[]; onPick: (v: T) => void; label: string; className?: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className={`seg ${className}`}>
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={o.id === value} className={o.id === value ? 'on' : ''} onClick={() => onPick(o.id)}>{o.label}</button>
      ))}
    </div>
  )
}

/** A dial drawn like the knob on the box. Drag it up or down, or use the − and + buttons; the change is sent 400 ms after the last touch. */
export function KnobDial({ name, value, min = 0, max = 1, step, text, onCommit }: {
  name: string; value: number; min?: number; max?: number; step: number; text: (v: number) => string; onCommit: (v: number) => void
}) {
  const [draft, setDraft] = useState<number | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const drag = useRef<{ y: number; v: number } | null>(null)
  const shown = draft ?? value
  useEffect(() => { if (draft !== null && Math.abs(value - draft) < step / 2) setDraft(null) }, [value, draft, step])
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  const round = (v: number) => Math.round(v / (step / 4)) * (step / 4)
  const set = (v: number) => {
    const nv = Math.min(max, Math.max(min, round(v)))
    setDraft(nv)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => { onCommit(nv); timer.current = setTimeout(() => setDraft(null), 3000) }, 400)
  }
  const deg = -135 + ((shown - min) / (max - min)) * 270
  return (
    <div className="knob">
      <div
        className="dial" role="slider" tabIndex={0} aria-label={name} aria-valuemin={min} aria-valuemax={max} aria-valuenow={shown} style={{ transform: `rotate(${deg}deg)` }}
        onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); drag.current = { y: e.clientY, v: shown } }}
        onPointerMove={(e) => { if (drag.current) set(drag.current.v + ((drag.current.y - e.clientY) / 160) * (max - min)) }}
        onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }}
        onKeyDown={(e) => { if (e.key === 'ArrowUp' || e.key === 'ArrowRight') set(shown + step); if (e.key === 'ArrowDown' || e.key === 'ArrowLeft') set(shown - step) }}
      ><span /></div>
      <div className="knob-name">{name}</div>
      <div className="knob-row">
        <button type="button" aria-label={`${name}减一点`} onClick={() => set(shown - step)}>−</button>
        <span className="knob-value">{text(shown)}</span>
        <button type="button" aria-label={`${name}加一点`} onClick={() => set(shown + step)}>+</button>
      </div>
    </div>
  )
}
