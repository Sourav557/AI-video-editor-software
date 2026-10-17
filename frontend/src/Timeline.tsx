import { useEffect, useMemo, useRef, useState } from 'react'
import { fmtTime } from './api'

export interface Block {
  id: string
  srcStart: number
  srcEnd: number
  speed: number
  muted: boolean
}

export const blockDur = (b: Block) => Math.max(0.01, (b.srcEnd - b.srcStart) / b.speed)

/** Lay blocks end-to-end; returns edit-start per block and total. */
export function layoutBlocks(blocks: Block[]): { starts: number[]; total: number } {
  const starts: number[] = []
  let cur = 0
  for (const b of blocks) { starts.push(cur); cur += blockDur(b) }
  return { starts, total: cur }
}

/** Remap source-timebase peaks onto the current block layout (speed-aware). */
export function remapPeaksBlocks(peaks: number[], srcDur: number, blocks: Block[]): number[] {
  const n = peaks.length
  if (!n || !blocks.length) return peaks
  const total = blocks.reduce((a, b) => a + blockDur(b), 0)
  const out: number[] = []
  for (const b of blocks) {
    const i0 = Math.max(0, Math.floor((b.srcStart / srcDur) * n))
    const i1 = Math.min(n, Math.ceil((b.srcEnd / srcDur) * n))
    const slice = peaks.slice(i0, Math.max(i0 + 1, i1))
    const target = Math.max(1, Math.round((blockDur(b) / total) * n))
    for (let i = 0; i < target; i++) out.push(slice[Math.floor((i / target) * slice.length)])
  }
  return out
}

let uid = 0
export const newId = () => `b${Date.now().toString(36)}${uid++}`

interface Props {
  blocks: Block[]
  commit: (next: Block[], transient?: boolean) => void
  peaks: number[]
  srcDuration: number
  currentTime: number
  onSeek: (t: number) => void
  selectedId: string | null
  onSelect: (id: string | null) => void
  tool: 'select' | 'razor'
  pxPerSec: number
  setPxPerSec: (v: number) => void
  trackLocked: boolean
  onToggleLock: () => void
  audioMuted: boolean
  onToggleMute: () => void
}

export default function Timeline(p: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [drag, setDrag] = useState<null | {
    id: string; mode: 'move' | 'trim-l' | 'trim-r'; startX: number; orig: Block; over: number
  }>(null)

  const { starts, total } = useMemo(() => layoutBlocks(p.blocks), [p.blocks])
  const width = Math.max(50, total * p.pxPerSec)
  const mappedPeaks = useMemo(
    () => remapPeaksBlocks(p.peaks, p.srcDuration, p.blocks),
    [p.peaks, p.srcDuration, p.blocks],
  )

  // waveform
  useEffect(() => {
    const cv = canvasRef.current
    if (!cv || !mappedPeaks.length) return
    const dpr = window.devicePixelRatio || 1
    cv.width = width * dpr; cv.height = 64 * dpr
    const ctx = cv.getContext('2d')!
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, 64)
    const n = mappedPeaks.length
    const barW = Math.max(1, width / n)
    ctx.fillStyle = 'rgba(52,211,153,.55)'
    for (let i = 0; i < n; i++) {
      const h = Math.max(1, mappedPeaks[i] * 60)
      ctx.fillRect((i / n) * width, 32 - h / 2, barW, h)
    }
  }, [mappedPeaks, width])

  const step = width > 2400 ? 10 : width > 1200 ? 5 : 1
  const ticks: number[] = []
  for (let t = 0; t <= total + 0.01; t += step) ticks.push(t)

  const editX = (t: number) => (t / Math.max(total, 0.01)) * width

  const onBlockDown = (e: React.PointerEvent, b: Block, idx: number) => {
    if (p.trackLocked) return
    e.stopPropagation()
    const x = e.clientX
    if (p.tool === 'razor') {
      // split at click position (edit timebase)
      const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
      const clickEdit = starts[idx] + (e.clientX - rect.left) / p.pxPerSec
      const offsetSrc = (clickEdit - starts[idx]) * b.speed
      const cutSrc = b.srcStart + offsetSrc
      if (cutSrc - b.srcStart < 0.15 || b.srcEnd - cutSrc < 0.15) return
      const left: Block = { ...b }
      const right: Block = { ...b, id: newId(), srcStart: cutSrc }
      left.srcEnd = cutSrc
      const next = [...p.blocks]
      next.splice(idx, 1, left, right)
      p.commit(next)
      p.onSelect(right.id)
      return
    }
    p.onSelect(b.id)
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    const edge = e.clientX - rect.left < 8 ? 'trim-l'
      : rect.right - e.clientX < 8 ? 'trim-r' : 'move'
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
    setDrag({ id: b.id, mode: edge, startX: x, orig: { ...b }, over: idx })
  }

  const onBlockMove = (e: React.PointerEvent) => {
    if (!drag) return
    const dxEdit = (e.clientX - drag.startX) / p.pxPerSec
    if (drag.mode === 'move') {
      const targetCenter = starts[p.blocks.findIndex((b) => b.id === drag.id)] + dxEdit + blockDur(drag.orig) / 2
      let over = p.blocks.length - 1
      for (let i = 0; i < p.blocks.length; i++) {
        if (targetCenter < starts[i] + blockDur(p.blocks[i])) { over = i; break }
      }
      setDrag({ ...drag, over })
    } else {
      const dSrc = dxEdit * drag.orig.speed
      const next = p.blocks.map((b) => {
        if (b.id !== drag.id) return b
        const nb = { ...b }
        if (drag.mode === 'trim-l') nb.srcStart = Math.min(drag.orig.srcStart + dSrc, drag.orig.srcEnd - 0.1)
        else nb.srcEnd = Math.max(drag.orig.srcEnd + dSrc, drag.orig.srcStart + 0.1)
        nb.srcStart = Math.max(0, nb.srcStart)
        return nb
      })
      p.commit(next, true) // transient: single history entry on release
    }
  }

  const onBlockUp = () => {
    if (drag?.mode === 'move') {
      const from = p.blocks.findIndex((b) => b.id === drag.id)
      if (from !== -1 && drag.over !== from) {
        const next = [...p.blocks]
        const [b] = next.splice(from, 1)
        next.splice(drag.over, 0, b)
        p.commit(next)
      }
    } else if (drag && (drag.mode === 'trim-l' || drag.mode === 'trim-r')) {
      p.commit(p.blocks) // finalize the trim as one undo step
    }
    setDrag(null)
  }

  const seekFromEvent = (e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    p.onSeek(Math.min(total, Math.max(0, (e.clientX - rect.left) / p.pxPerSec)))
  }

  const playX = editX(p.currentTime)

  return (
    <div className="card overflow-hidden select-none">
      <div className="flex items-center justify-between px-4 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-3 text-xs">
          <span className="font-semibold">Timeline</span>
          <span className="faint tabular">{fmtTime(p.currentTime)} / {fmtTime(total)}</span>
          <span className="faint">{p.blocks.length} clips</span>
        </div>
        <div className="flex items-center gap-2 text-xs muted">
          <span>Zoom</span>
          <input type="range" min={8} max={160} value={p.pxPerSec}
                 onChange={(e) => p.setPxPerSec(Number(e.target.value))} className="w-28" />
        </div>
      </div>

      <div className="flex">
        {/* track headers */}
        <div className="shrink-0 w-20 border-r" style={{ borderColor: 'var(--border)', background: 'var(--surface-2)' }}>
          <div className="h-6 border-b" style={{ borderColor: 'var(--border)' }} />
          <div className="h-16 border-b flex flex-col items-center justify-center gap-1" style={{ borderColor: 'var(--border)' }}>
            <span className="text-[10px] font-bold faint">V1</span>
            <button title={p.trackLocked ? 'Unlock track' : 'Lock track'}
                    className="text-xs" onClick={p.onToggleLock}>{p.trackLocked ? '🔒' : '🔓'}</button>
          </div>
          <div className="h-16 flex flex-col items-center justify-center gap-1">
            <span className="text-[10px] font-bold faint">A1</span>
            <button title={p.audioMuted ? 'Unmute' : 'Mute'}
                    className="text-xs" onClick={p.onToggleMute}>{p.audioMuted ? '🔇' : '🔊'}</button>
          </div>
        </div>

        {/* tracks */}
        <div className="overflow-x-auto flex-1">
          <div style={{ width }} className="relative">
            <div className="relative h-6 border-b" style={{ borderColor: 'var(--border)', background: 'var(--surface-2)' }}
                 onClick={seekFromEvent}>
              {ticks.map((t) => (
                <div key={t} className="absolute top-0 bottom-0" style={{ left: t * p.pxPerSec }}>
                  <div className="w-px h-2" style={{ background: 'var(--border)' }} />
                  <div className="faint text-[9px] tabular pl-1">{fmtTime(t)}</div>
                </div>
              ))}
            </div>

            <div className="relative h-16 border-b" style={{ borderColor: 'var(--border)', background: '#0b0e14', cursor: p.tool === 'razor' ? 'crosshair' : 'default' }}
                 onClick={seekFromEvent}
                 onPointerMove={onBlockMove} onPointerUp={onBlockUp} onPointerLeave={onBlockUp}>
              {p.blocks.map((b, i) => {
                const sel = b.id === p.selectedId
                return (
                  <div key={b.id}
                       onPointerDown={(e) => onBlockDown(e, b, i)}
                       className="absolute inset-y-2 rounded overflow-hidden"
                       title={`${fmtTime(b.srcStart)} → ${fmtTime(b.srcEnd)}${b.speed !== 1 ? ` · ${b.speed}x` : ''}${b.muted ? ' · muted' : ''}`}
                       style={{
                         left: starts[i] * p.pxPerSec,
                         width: Math.max(4, blockDur(b) * p.pxPerSec),
                         background: sel
                           ? 'linear-gradient(180deg, rgba(34,211,238,.75), rgba(124,58,237,.6))'
                           : 'linear-gradient(180deg, rgba(124,58,237,.55), rgba(34,211,238,.35))',
                         border: sel ? '2px solid var(--cyan)' : '1px solid rgba(139,92,246,.6)',
                         cursor: p.tool === 'razor' ? 'crosshair' : 'grab',
                         opacity: b.muted ? 0.55 : 1,
                       }}>
                    <div className="absolute inset-y-0 left-0 w-2 cursor-ew-resize"
                         style={{ background: 'rgba(255,255,255,.25)' }} />
                    <div className="absolute inset-y-0 right-0 w-2 cursor-ew-resize"
                         style={{ background: 'rgba(255,255,255,.25)' }} />
                    {blockDur(b) * p.pxPerSec > 60 && (
                      <div className="text-[9px] px-2 py-0.5 truncate faint">
                        {b.speed !== 1 ? `${b.speed}x · ` : ''}{fmtTime(b.srcStart)}→{fmtTime(b.srcEnd)}
                      </div>
                    )}
                  </div>
                )
              })}
              {drag?.mode === 'move' && (
                <div className="absolute top-0 bottom-0 w-0.5 pointer-events-none"
                     style={{ left: starts[Math.min(drag.over, starts.length - 1)] * p.pxPerSec, background: 'var(--warning)' }} />
              )}
            </div>

            <div className="relative h-16" style={{ background: '#0b0e14', cursor: 'pointer' }} onClick={seekFromEvent}>
              <canvas ref={canvasRef} style={{ width, height: 64 }} className="absolute inset-0" />
            </div>

            <div className="absolute top-0 bottom-0 pointer-events-none" style={{ left: playX }}>
              <div className="w-px h-full" style={{ background: 'var(--danger)' }} />
              <div className="w-3 h-3 rotate-45 -ml-1.5 -mt-0.5" style={{ background: 'var(--danger)' }} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
