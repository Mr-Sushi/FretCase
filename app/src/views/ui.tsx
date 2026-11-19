import { useEffect, useState } from 'react'

/**
 * Range input that shows the finger's value while dragging and reports the final value on release.
 * The song is never patched locally: after the commit the server's song arrives and the prop catches up.
 */
export function DraftSlider({ value, min = 0, max = 1, step = 0.01, label, onInput, onCommit }: {
  value: number; min?: number; max?: number; step?: number; label?: string
  onInput?: (v: number) => void; onCommit: (v: number) => void
}) {
  const [draft, setDraft] = useState<number | null>(null)
  useEffect(() => setDraft(null), [value])
  return (
    <input
      type="range" min={min} max={max} step={step} aria-label={label}
      value={draft ?? value}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => { const v = Number(e.target.value); setDraft(v); onInput?.(v) }}
      onPointerUp={(e) => { const v = Number((e.target as HTMLInputElement).value); onCommit(v) }}
      onKeyUp={(e) => { const v = Number((e.target as HTMLInputElement).value); onCommit(v) }}
    />
  )
}
