import { useEffect, useRef } from 'react'
import { fmtTime } from './api'

export interface TlSegment { start: number; end: number; label?: string }
export interface TlCut { start: number; end: number; kind: 'silence' | 'filler' }

interface Props {
  duration: number
  peaks: number[]
  segments: TlSegment[]   // kept blocks, in the current timebase
  cuts: TlCut[]           // removed regions, in the current timebase
  currentTime: number
  onSeek: (t: number) => void
  pxPerSec: number
  setPxPerSec: (v: number) => void
}

/** Filmora-style timeline: ruler + video track + waveform + playhead. */
export default function Timeline(p: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const { duration, peaks, pxPerSec } = p
  const width = Math.max(50, duration * pxPerSec)

  // draw waveform
  useEffect(() => {
    const cv = canvasRef.current
    if (!cv || !peaks.length) return
    const dpr = window.devicePixelRatio || 1
    cv.width = width * dpr; cv.height = 64 * dpr
    const ctx = cv.getContext('2d')!
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, 64)
    const n = peaks.length
    const barW = Math.max(1, width / n)
    ctx.fillStyle = 'rgba(52,211,153,.55)'
    for (let i = 0; i < n; i++) {
      const h = Math.max(1, peaks[i] * 60)
      const x = (i / n) * width
      ctx.fillRect(x, 32 - h / 2, barW, h)
    }
  }, [peaks, width])

  // ruler ticks
  const step = duration * pxPerSec > 2400 ? 10 : duration * pxPerSec > 1200 ? 5 : 1
  const ticks: number[] = []
  for (let t = 0; t <= duration + 0.01; t += step) ticks.push(t)

  const seekFromEvent = (e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    const x = e.clientX - rect.left
    p.onSeek(Math.min(duration, Math.max(0, x / pxPerSec)))
  }

  const playX = (p.currentTime / Math.max(duration, 0.01)) * width

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-3 text-xs">
          <span className="font-semibold">Timeline</span>
          <span className="faint tabular">{fmtTime(p.currentTime)} / {fmtTime(duration)}</span>
        </div>
        <div className="flex items-center gap-2 text-xs muted">
          <span>Zoom</span>
          <input type="range" min={8} max={120} value={pxPerSec}
                 onChange={(e) => p.setPxPerSec(Number(e.target.value))} className="w-28" />
        </div>
      </div>

      <div ref={wrapRef} className="overflow-x-auto">
        <div style={{ width }} className="relative select-none">
          {/* ruler */}
          <div className="relative h-6 border-b" style={{ borderColor: 'var(--border)', background: 'var(--surface-2)' }}
               onClick={seekFromEvent}>
            {ticks.map((t) => (
              <div key={t} className="absolute top-0 bottom-0" style={{ left: t * pxPerSec }}>
                <div className="w-px h-2" style={{ background: 'var(--border)' }} />
                <div className="faint text-[9px] tabular pl-1">{fmtTime(t)}</div>
              </div>
            ))}
          </div>

          {/* video track */}
          <div className="relative h-14 border-b cursor-pointer" style={{ borderColor: 'var(--border)', background: '#0b0e14' }}
               onClick={seekFromEvent}>
            <div className="absolute inset-y-2 left-0 right-0">
              {p.segments.map((s, i) => (
                <div key={i} className="absolute inset-y-0 rounded"
                     title={s.label ?? `${fmtTime(s.start)} → ${fmtTime(s.end)}`}
                     style={{
                       left: s.start * pxPerSec, width: Math.max(2, (s.end - s.start) * pxPerSec),
                       background: 'linear-gradient(180deg, rgba(124,58,237,.55), rgba(34,211,238,.35))',
                       border: '1px solid rgba(139,92,246,.6)',
                     }} />
              ))}
              {p.cuts.map((c, i) => (
                <div key={'c' + i} className="absolute inset-y-0 rounded"
                     title={`${c.kind} cut ${fmtTime(c.start)} → ${fmtTime(c.end)}`}
                     style={{
                       left: c.start * pxPerSec, width: Math.max(2, (c.end - c.start) * pxPerSec),
                       background: c.kind === 'silence'
                         ? 'repeating-linear-gradient(45deg, rgba(248,113,113,.35), rgba(248,113,113,.35) 4px, transparent 4px, transparent 8px)'
                         : 'repeating-linear-gradient(45deg, rgba(251,191,36,.35), rgba(251,191,36,.35) 4px, transparent 4px, transparent 8px)',
                     }} />
              ))}
            </div>
            <span className="absolute left-1 top-1 faint text-[9px] font-semibold">V1</span>
          </div>

          {/* audio track */}
          <div className="relative h-16 cursor-pointer" style={{ background: '#0b0e14' }} onClick={seekFromEvent}>
            <canvas ref={canvasRef} style={{ width, height: 64 }} className="absolute inset-0" />
            <span className="absolute left-1 top-1 faint text-[9px] font-semibold">A1</span>
          </div>

          {/* playhead */}
          <div className="absolute top-0 bottom-0 pointer-events-none" style={{ left: playX }}>
            <div className="w-px h-full" style={{ background: 'var(--danger)' }} />
            <div className="w-3 h-3 rotate-45 -ml-1.5 -mt-0.5" style={{ background: 'var(--danger)' }} />
          </div>
        </div>
      </div>

      <div className="px-4 py-1.5 border-t flex gap-4 text-[10px] faint" style={{ borderColor: 'var(--border)' }}>
        <span><span style={{ color: 'var(--danger)' }}>▨</span> silence cut</span>
        <span><span style={{ color: 'var(--warning)' }}>▨</span> filler cut</span>
        <span className="ml-auto">click anywhere to seek</span>
      </div>
    </div>
  )
}
