import { useEffect, useMemo, useRef, useState } from 'react'
import { fmtTime } from './api'
import type { TitleT } from './MediaBin'

export interface Block {
  id: string
  srcStart: number
  srcEnd: number
  speed: number
  muted: boolean
  keyframes?: Keyframes
}

/** One keyframe: t = seconds relative to the block's output-time start
 *  (after speed is applied), v = property value at that time. */
export interface Kf { t: number; v: number }

export type KfProp = 'x' | 'y' | 'scale' | 'rot' | 'op'

/** Keyframed transforms. Defaults: x=0, y=0 (px offset of clip's top-left
 *  on the centered canvas), scale=1, rot=0 (degrees), op=1. */
export type Keyframes = Record<KfProp, Kf[]>

export const KF_DEFAULTS: Record<KfProp, number> = { x: 0, y: 0, scale: 1, rot: 0, op: 1 }

export const emptyKeyframes = (): Keyframes => ({ x: [], y: [], scale: [], rot: [], op: [] })

/** Linear interpolation between keyframes; before first = first value,
 *  after last = last value. No keyframes -> the property default. */
export function kfVal(kfs: Keyframes | undefined, prop: KfProp, t: number): number {
  const ks = [...(kfs?.[prop] ?? [])].sort((a, b) => a.t - b.t)
  if (!ks.length) return KF_DEFAULTS[prop]
  if (t <= ks[0].t) return ks[0].v
  for (let i = 0; i < ks.length - 1; i++) {
    const a = ks[i], b = ks[i + 1]
    if (t <= b.t) {
      const span = b.t - a.t
      return span < 1e-9 ? b.v : a.v + ((b.v - a.v) * (t - a.t)) / span
    }
  }
  return ks[ks.length - 1].v
}

/** Interpolated transform for a block at block-local time t. */
export function kfTransform(kfs: Keyframes | undefined, t: number) {
  return {
    x: kfVal(kfs, 'x', t),
    y: kfVal(kfs, 'y', t),
    scale: kfVal(kfs, 'scale', t),
    rot: kfVal(kfs, 'rot', t),
    op: kfVal(kfs, 'op', t),
  }
}

export function blockHasKeyframes(b: Block): boolean {
  const k = b.keyframes
  return !!k && (k.x.length + k.y.length + k.scale.length + k.rot.length + k.op.length) > 0
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
  filmstrip: { interval: number; thumbs: string[] } | null
  filmstripUrl: (name: string) => string
  titles: TitleT[]
  onTitlesCommit: (next: TitleT[], transient?: boolean) => void
  selectedTitleId: string | null
  onSelectTitle: (id: string | null) => void
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
  const [tdrag, setTdrag] = useState<null | {
    id: string; mode: 'move' | 'trim-l' | 'trim-r'; startX: number; orig: TitleT
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

  /** Filmstrip thumbnails across a video block (Filmora look). */
  const thumbStrip = (b: Block, i: number) => {
    if (!p.filmstrip || !p.filmstrip.thumbs.length) return null
    const wPx = blockDur(b) * p.pxPerSec
    if (wPx < 50) return null
    const n = Math.ceil(wPx / 90)
    const imgs = []
    for (let k = 0; k < n; k++) {
      const editT = starts[i] + ((k + 0.5) * 90) / p.pxPerSec
      const srcT = b.srcStart + (editT - starts[i]) * b.speed
      const idx = Math.min(
        p.filmstrip.thumbs.length - 1,
        Math.max(0, Math.floor(srcT / p.filmstrip.interval)),
      )
      imgs.push(
        <img key={k} src={p.filmstripUrl(p.filmstrip.thumbs[idx])}
             draggable={false} alt=""
             style={{ width: 90, height: '100%', objectFit: 'cover', flexShrink: 0 }} />,
      )
    }
    return <div className="absolute inset-0 flex overflow-hidden opacity-70 pointer-events-none">{imgs}</div>
  }

  const onBlockDown = (e: React.PointerEvent, b: Block, idx: number) => {
    if (p.trackLocked) return
    e.stopPropagation()
    p.onSelect(b.id); p.onSelectTitle(null)
    if (p.tool === 'razor') {
      const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
      const clickEdit = starts[idx] + (e.clientX - rect.left) / p.pxPerSec
      const cutSrc = b.srcStart + (clickEdit - starts[idx]) * b.speed
      if (cutSrc - b.srcStart < 0.15 || b.srcEnd - cutSrc < 0.15) return
      const left: Block = { ...b, srcEnd: cutSrc }
      const right: Block = { ...b, id: newId(), srcStart: cutSrc }
      const next = [...p.blocks]
      next.splice(idx, 1, left, right)
      p.commit(next)
      p.onSelect(right.id)
      return
    }
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    const edge = e.clientX - rect.left < 8 ? 'trim-l'
      : rect.right - e.clientX < 8 ? 'trim-r' : 'move'
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
    setDrag({ id: b.id, mode: edge, startX: e.clientX, orig: { ...b }, over: idx })
  }

  const onBlockMove = (e: React.PointerEvent) => {
    if (!drag) return
    const dxEdit = (e.clientX - drag.startX) / p.pxPerSec
    if (drag.mode === 'move') {
      const fromIdx = p.blocks.findIndex((bb) => bb.id === drag.id)
      const targetCenter = starts[fromIdx] + dxEdit + blockDur(drag.orig) / 2
      let over = p.blocks.length - 1
      for (let i = 0; i < p.blocks.length; i++) {
        if (targetCenter < starts[i] + blockDur(p.blocks[i])) { over = i; break }
      }
      setDrag({ ...drag, over })
    } else {
      const dSrc = dxEdit * drag.orig.speed
      const next = p.blocks.map((bb) => {
        if (bb.id !== drag.id) return bb
        const nb = { ...bb }
        if (drag.mode === 'trim-l') nb.srcStart = Math.min(drag.orig.srcStart + dSrc, drag.orig.srcEnd - 0.1)
        else nb.srcEnd = Math.max(drag.orig.srcEnd + dSrc, drag.orig.srcStart + 0.1)
        nb.srcStart = Math.max(0, nb.srcStart)
        return nb
      })
      p.commit(next, true)
    }
  }

  const onBlockUp = () => {
    if (drag?.mode === 'move') {
      const from = p.blocks.findIndex((bb) => bb.id === drag.id)
      if (from !== -1 && drag.over !== from) {
        const next = [...p.blocks]
        const [bb] = next.splice(from, 1)
        next.splice(drag.over, 0, bb)
        p.commit(next)
      }
    } else if (drag) {
      p.commit(p.blocks)
    }
    setDrag(null)
  }

  // ---- title chips ----
  const onTitleDown = (e: React.PointerEvent, t: TitleT) => {
    if (p.trackLocked) return
    e.stopPropagation()
    p.onSelectTitle(t.id); p.onSelect(null)
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    const edge = e.clientX - rect.left < 8 ? 'trim-l'
      : rect.right - e.clientX < 8 ? 'trim-r' : 'move'
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
    setTdrag({ id: t.id, mode: edge, startX: e.clientX, orig: { ...t } })
  }
  const onTitleMove = (e: React.PointerEvent) => {
    if (!tdrag) return
    const dx = (e.clientX - tdrag.startX) / p.pxPerSec
    const next = p.titles.map((t) => {
      if (t.id !== tdrag.id) return t
      const nt = { ...t }
      if (tdrag.mode === 'move') {
        const len = tdrag.orig.end - tdrag.orig.start
        nt.start = Math.max(0, tdrag.orig.start + dx)
        nt.end = nt.start + len
      } else if (tdrag.mode === 'trim-l') {
        nt.start = Math.min(tdrag.orig.start + dx, tdrag.orig.end - 0.3)
      } else {
        nt.end = Math.max(tdrag.orig.end + dx, tdrag.orig.start + 0.3)
      }
      return nt
    })
    p.onTitlesCommit(next, true)
  }
  const onTitleUp = () => {
    if (tdrag) p.onTitlesCommit(p.titles)
    setTdrag(null)
  }

  const seekFromEvent = (e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    p.onSeek(Math.min(total, Math.max(0, (e.clientX - rect.left) / p.pxPerSec)))
  }

  const playX = editX(p.currentTime)

  return (
    <div className="card overflow-hidden select-none">
      <div className="flex">
        {/* track headers */}
        <div className="shrink-0 w-20 border-r" style={{ borderColor: 'var(--border)', background: 'var(--surface-2)' }}>
          <div className="h-6 border-b" style={{ borderColor: 'var(--border)' }} />
          <div className="h-9 border-b flex items-center justify-center gap-2" style={{ borderColor: 'var(--border)' }}>
            <span className="text-[10px] font-bold faint">T2</span>
          </div>
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

            {/* T2 titles track */}
            <div className="relative h-9 border-b" style={{ borderColor: 'var(--border)', background: '#0d1017' }}
                 onClick={seekFromEvent} onPointerMove={onTitleMove} onPointerUp={onTitleUp} onPointerLeave={onTitleUp}>
              {p.titles.map((t) => (
                <div key={t.id}
                     onPointerDown={(e) => onTitleDown(e, t)}
                     className="absolute inset-y-1 rounded flex items-center px-2 gap-1 overflow-hidden"
                     style={{
                       left: t.start * p.pxPerSec,
                       width: Math.max(10, (t.end - t.start) * p.pxPerSec),
                       background: 'linear-gradient(180deg, rgba(34,211,238,.5), rgba(34,211,238,.25))',
                       border: t.id === p.selectedTitleId ? '2px solid var(--cyan)' : '1px solid rgba(34,211,238,.6)',
                       cursor: 'grab',
                     }}>
                  <div className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize" style={{ background: 'rgba(255,255,255,.3)' }} />
                  <div className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize" style={{ background: 'rgba(255,255,255,.3)' }} />
                  <span className="font-bold text-[10px] ai-glow shrink-0">T</span>
                  {(t.end - t.start) * p.pxPerSec > 50 && (
                    <span className="text-[10px] truncate">{t.text}</span>
                  )}
                </div>
              ))}
            </div>

            {/* V1 */}
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
                         background: 'rgba(30,27,75,.85)',
                         border: sel ? '2px solid var(--cyan)' : '1px solid rgba(139,92,246,.6)',
                         cursor: p.tool === 'razor' ? 'crosshair' : 'grab',
                         opacity: b.muted ? 0.55 : 1,
                       }}>
                    {thumbStrip(b, i)}
                    <div className="absolute inset-y-0 left-0 w-2 cursor-ew-resize z-10"
                         style={{ background: 'rgba(255,255,255,.25)' }} />
                    <div className="absolute inset-y-0 right-0 w-2 cursor-ew-resize z-10"
                         style={{ background: 'rgba(255,255,255,.25)' }} />
                    {blockDur(b) * p.pxPerSec > 60 && (
                      <div className="absolute bottom-0 left-0 right-0 text-[9px] px-2 py-0.5 truncate z-10"
                           style={{ background: 'rgba(0,0,0,.55)' }}>
                        {blockHasKeyframes(b) ? '◆ ' : ''}{b.speed !== 1 ? `${b.speed}x · ` : ''}{fmtTime(b.srcStart)}→{fmtTime(b.srcEnd)}
                      </div>
                    )}
                  </div>
                )
              })}
              {drag?.mode === 'move' && (
                <div className="absolute top-0 bottom-0 w-0.5 pointer-events-none z-20"
                     style={{ left: starts[Math.min(drag.over, starts.length - 1)] * p.pxPerSec, background: 'var(--warning)' }} />
              )}
            </div>

            {/* A1 */}
            <div className="relative h-16" style={{ background: '#0b0e14', cursor: 'pointer' }} onClick={seekFromEvent}>
              <canvas ref={canvasRef} style={{ width, height: 64 }} className="absolute inset-0" />
            </div>

            {/* playhead */}
            <div className="absolute top-0 bottom-0 pointer-events-none z-30" style={{ left: playX }}>
              <div className="w-px h-full" style={{ background: 'var(--danger)' }} />
              <div className="w-3 h-3 rotate-45 -ml-1.5 -mt-0.5" style={{ background: 'var(--danger)' }} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
