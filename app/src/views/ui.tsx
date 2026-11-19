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
