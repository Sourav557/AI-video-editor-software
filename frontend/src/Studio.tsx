import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, fmtTC, fmtTime, JobStatus, Segment, Silence } from './api'
import Timeline, {
  Block, blockDur, layoutBlocks, newId,
  Kf, KfProp, Keyframes, KF_DEFAULTS, emptyKeyframes, kfVal, kfTransform,
  Transition, TRANSITION_TYPES, clampTransitionDur,
  BlockColor, COLOR_DEFAULTS, COLOR_RANGES, COLOR_PRESETS,
} from './Timeline'
import MediaBin, { MediaTab, TitleT } from './MediaBin'
import ProjectInfo from './ProjectInfo'
import ClipsPanel from './ClipsPanel'
import VoiceStudio from './VoiceStudio'
import PublishPrep from './PublishPrep'
import ChatPanel from './ChatPanel'

interface Props {
  projectId: string
  fileName: string
  segments: Segment[]
  silences: Silence[]
  language: string
  srcDuration: number
  onError: (m: string) => void
  onImport: (f: File) => void
}

interface Edl {
  segments: { start: number; end: number; kind: string }[]
  source_duration: number
  output_duration: number
  cuts: number
}

type View = 'source' | 'edit' | 'rendered'
type Tab = 'clips' | 'transcript' | 'voice' | 'publish' | 'chat'

const KF_ROWS: { key: KfProp; label: string; step: number; min: number; max: number }[] = [
  { key: 'x', label: 'X (px)', step: 1, min: -4000, max: 4000 },
  { key: 'y', label: 'Y (px)', step: 1, min: -4000, max: 4000 },
  { key: 'scale', label: 'Scale', step: 0.05, min: 0.01, max: 8 },
  { key: 'rot', label: 'Rotate (°)', step: 1, min: -360, max: 360 },
  { key: 'op', label: 'Opacity', step: 0.05, min: 0, max: 1 },
]

/** Keyframe editor for the selected clip (Slice 11). Times are block-local
 *  seconds (after speed is applied). */
function KeyframesEditor({ block, localNow, dur, onChange, onCommit }: {
  block: Block
  localNow: number
  dur: number
  onChange: (kfs: Keyframes) => void
  onCommit: () => void
}) {
  const kfs = block.keyframes ?? emptyKeyframes()
  const setProp = (prop: KfProp, next: Kf[]) => {
    const seen = new Map<number, number>()
    for (const k of next) seen.set(Math.round(k.t * 100) / 100, k.v)
    const clean = [...seen.entries()].map(([t, v]) => ({ t, v })).sort((a, b) => a.t - b.t)
    onChange({ ...kfs, [prop]: clean })
  }
  const addAtPlayhead = (prop: KfProp) => {
    const t = Math.round(Math.min(Math.max(localNow, 0), dur) * 100) / 100
    const cur = [...(kfs[prop] ?? [])]
    if (!cur.length) {
      // seed the property default at t=0, plus the playhead keyframe
      const seed: Kf[] = [{ t: 0, v: KF_DEFAULTS[prop] }]
      if (t > 0.05) seed.push({ t, v: KF_DEFAULTS[prop] })
      setProp(prop, seed)
    } else {
      setProp(prop, [...cur.filter((k) => Math.abs(k.t - t) > 0.02), { t, v: kfVal(kfs, prop, t) }])
    }
    onCommit()
  }
  const clampVal = (prop: KfProp, v: number) => {
    const row = KF_ROWS.find((r) => r.key === prop)!
    return Math.min(row.max, Math.max(row.min, v))
  }
  const num = (raw: string, fallback: number) => {
    const v = parseFloat(raw)
    return Number.isNaN(v) ? fallback : v
  }
  return (
    <div className="mt-3 pt-3 border-t" style={{ borderColor: 'var(--border)' }}>
      <div className="font-semibold text-xs mb-1" style={{ color: 'var(--cyan)' }}>KEYFRAMES</div>
      <div className="faint text-[10px] mb-2">Animate position, scale, rotation and opacity over the clip.</div>
      {KF_ROWS.map((row) => {
        const list = [...(kfs[row.key] ?? [])].sort((a, b) => a.t - b.t)
        return (
          <div key={row.key} className="mb-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold">{row.label}</span>
              <div className="flex items-center gap-1.5">
                {list.length > 0 && (
                  <button className="text-[10px] faint hover:text-white" title="Clear all keyframes"
                          onClick={() => { setProp(row.key, []); onCommit() }}>clear</button>
                )}
                <button className="text-[10px] px-1.5 py-0.5 rounded card"
                        title="Add keyframe at playhead (block-local time)"
                        onClick={() => addAtPlayhead(row.key)}>＋ at ▶</button>
              </div>
            </div>
            {list.map((k, i) => (
              <div key={i} className="flex items-center gap-1.5 mt-1 text-xs">
                <span className="faint text-[10px]">t</span>
                <input type="number" min={0} max={dur} step={0.1} value={k.t}
                       className="w-16 px-1 py-0.5 rounded text-xs tabular"
                       style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}
                       onChange={(e) => {
                         const nt = [...list]
                         nt[i] = { ...k, t: Math.min(Math.max(num(e.target.value, k.t), 0), dur) }
                         setProp(row.key, nt)
                       }}
                       onBlur={onCommit} />
                <span className="faint text-[10px]">s</span>
                <input type="number" min={row.min} max={row.max} step={row.step}
                       value={Math.round(k.v * 1000) / 1000}
                       className="w-20 px-1 py-0.5 rounded text-xs tabular"
                       style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}
                       onChange={(e) => {
                         const nt = [...list]
                         nt[i] = { ...k, v: clampVal(row.key, num(e.target.value, k.v)) }
                         setProp(row.key, nt)
                       }}
                       onBlur={onCommit} />
                <button className="faint hover:text-white text-xs" title="Delete keyframe"
                        onClick={() => { setProp(row.key, list.filter((_, j) => j !== i)); onCommit() }}>✕</button>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

/** Color grade panel for the selected clip (Slice 13): 5 sliders with live
 *  values, one-click presets, LUT dropdown, reset. Slider drags update
 *  transiently (no undo-history spam); committed on release. */
function ColorPanel({ block, luts, onChange, onCommit }: {
  block: Block
  luts: string[]
  onChange: (patch: Partial<Block>, transient?: boolean) => void
  onCommit: () => void
}) {
  const color = block.color ?? {}
  const setColor = (key: keyof BlockColor, v: number) => {
    const r = COLOR_RANGES[key]
    const cv = Math.min(r.max, Math.max(r.min, Number.isFinite(v) ? v : COLOR_DEFAULTS[key]))
    onChange({ color: { ...color, [key]: cv } }, true)
  }
  const hasColor = block.color !== undefined || block.lut !== undefined
  return (
    <div className="mt-3 pt-3 border-t" style={{ borderColor: 'var(--border)' }}>
      <div className="flex items-center justify-between mb-2">
        <div className="font-semibold text-xs" style={{ color: 'var(--cyan)' }}>COLOR</div>
        {hasColor && (
          <button className="text-[10px] faint hover:text-white" title="Restore default color grade"
                  onClick={() => onChange({ color: undefined, lut: undefined })}>Reset</button>
        )}
      </div>
      {(Object.keys(COLOR_RANGES) as (keyof BlockColor)[]).map((key) => {
        const r = COLOR_RANGES[key]
        const v = color[key] ?? COLOR_DEFAULTS[key]
        return (
          <div key={key} className="flex items-center gap-2 text-xs mb-1.5">
            <span className="w-24 shrink-0 faint">{r.label}</span>
            <input type="range" min={r.min} max={r.max} step={r.step} value={v} className="flex-1"
                   onChange={(e) => setColor(key, Number(e.target.value))}
                   onPointerUp={onCommit} onBlur={onCommit} />
            <span className="tabular w-12 text-right">{v.toFixed(2)}</span>
          </div>
        )
      })}
      <div className="flex flex-wrap gap-1.5 mt-2">
        {COLOR_PRESETS.map((p) => (
          <button key={p.name} className="text-[11px] px-2 py-1 rounded card hover:text-white"
                  title={`Apply the ${p.name} preset (then tweak the sliders)`}
                  onClick={() => onChange({ color: { ...COLOR_DEFAULTS, ...p.values } })}>
            {p.name}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2 mt-2 text-xs">
        <span className="faint w-24 shrink-0">LUT</span>
        <select value={block.lut ?? ''}
                onChange={(e) => onChange({ lut: e.target.value || undefined })}
                className="card px-1.5 py-1 text-xs flex-1">
          <option value="">None</option>
          {luts.map((l) => (
            <option key={l} value={l}>{l.replace(/\.cube$/, '').replace(/_/g, ' ')}</option>
          ))}
        </select>
      </div>
    </div>
  )
}

export default function Studio({ projectId, fileName, segments, silences, language, srcDuration, onError, onImport }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const playerWrapRef = useRef<HTMLDivElement>(null)
  const [vidAspect, setVidAspect] = useState('16 / 9')
  const saveTimer = useRef<number | null>(null)
  const loadedTl = useRef(false)

  const [peaks, setPeaks] = useState<number[]>([])
  const [filmstrip, setFilmstrip] = useState<{ interval: number; thumbs: string[] } | null>(null)
  const [edl, setEdl] = useState<Edl | null>(null)
  const [hasRender, setHasRender] = useState(false)
  const [view, setView] = useState<View>('source')
  const [tab, setTab] = useState<Tab>('clips')
  const [mediaTab, setMediaTab] = useState<MediaTab>('media')
  const [audioFiles, setAudioFiles] = useState<string[]>([])

  const [blocks, setBlocks] = useState<Block[]>([])
  const [titles, setTitles] = useState<TitleT[]>([])
  const [hist, setHist] = useState<Block[][]>([])
  const [hIdx, setHIdx] = useState(-1)
  const [tool, setTool] = useState<'select' | 'razor'>('select')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedTitleId, setSelectedTitleId] = useState<string | null>(null)
  const [trackLocked, setTrackLocked] = useState(false)
  const [audioMuted, setAudioMuted] = useState(false)

  const [currentTime, setCurrentTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [pxPerSec, setPxPerSec] = useState(40)
  const [showAp, setShowAp] = useState(false)
  const [apRunning, setApRunning] = useState(false)
  const [apProgress, setApProgress] = useState(0)
  const [renderRunning, setRenderRunning] = useState(false)
  const [renderProgress, setRenderProgress] = useState(0)
  const [optSilence, setOptSilence] = useState(true)
  const [optFillers, setOptFillers] = useState(false)
  const [optCaptions, setOptCaptions] = useState(true)
  const [luts, setLuts] = useState<string[]>([])
  const [seoData, setSeoData] = useState<any>(null)
  const [generatingSeo, setGeneratingSeo] = useState(false)

  // ---------- load ----------
  useEffect(() => {
    api.waveform(projectId).then((w) => setPeaks(w.peaks ?? [])).catch(() => {})
    api.filmstrip(projectId).then(setFilmstrip).catch(() => {})
    api.audioList(projectId).then((a) => setAudioFiles(a.files ?? [])).catch(() => {})
    api.luts().then((r) => setLuts(r.luts ?? [])).catch(() => {})
    api.editGet(projectId).then(() => setHasRender(true)).catch(() => {})
    // restore saved timeline, else seed
    api.timelineGet(projectId)
      .then((tl) => {
        if (tl.blocks?.length) {
          setBlocks(tl.blocks); setHist([tl.blocks]); setHIdx(0)
          setTitles(tl.titles ?? [])
        } else {
          seedFromAutopilot()
        }
        loadedTl.current = true
      })
      .catch(() => { seedFromAutopilot(); loadedTl.current = true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const seedFromAutopilot = () => {
    api.autopilotGet(projectId)
      .then((e) => {
        setEdl(e)
        const b = e.segments.map((s: any) => ({ id: newId(), srcStart: s.start, srcEnd: s.end, speed: 1, muted: false }))
        setBlocks(b); setHist([b]); setHIdx(0)
      })
      .catch(() => {
        if (srcDuration > 0) {
          const b: Block[] = [{ id: newId(), srcStart: 0, srcEnd: srcDuration, speed: 1, muted: false }]
          setBlocks(b); setHist([b]); setHIdx(0)
          setPxPerSec(Math.max(8, Math.min(160, 900 / srcDuration)))
        }
      })
  }

  // ---------- persist timeline (debounced) ----------
  useEffect(() => {
    if (!loadedTl.current) return
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      api.timelineSave(projectId, blocks, titles).catch(() => {})
    }, 800)
    return () => { if (saveTimer.current) window.clearTimeout(saveTimer.current) }
  }, [blocks, titles, projectId])

  // ---------- editing ops ----------
  const commit = useCallback((next: Block[], transient = false) => {
    if (transient) { setBlocks(next); return }
    setHist((h) => {
      const nh = [...h.slice(0, hIdx + 1), next]
      return nh.length > 100 ? nh.slice(-100) : nh
    })
    setHIdx((i) => i + 1)
    setBlocks(next)
  }, [hIdx])

  const titlesCommit = useCallback((next: TitleT[], transient = false) => {
    setTitles(next)
    void transient
  }, [])

  const undo = useCallback(() => {
    if (hIdx > 0) { setHIdx(hIdx - 1); setBlocks(hist[hIdx - 1]); setSelectedId(null) }
  }, [hIdx, hist])
  const redo = useCallback(() => {
    if (hIdx < hist.length - 1) { setHIdx(hIdx + 1); setBlocks(hist[hIdx + 1]) }
  }, [hIdx, hist])

  const deleteSelected = useCallback(() => {
    if (trackLocked) return
    if (selectedTitleId) {
      setTitles((ts) => ts.filter((t) => t.id !== selectedTitleId))
      setSelectedTitleId(null)
      return
    }
    if (!selectedId) return
    commit(blocks.filter((b) => b.id !== selectedId))
    setSelectedId(null)
  }, [selectedId, selectedTitleId, blocks, commit, trackLocked])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') return
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelected() }
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo() }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { e.preventDefault(); redo() }
      if (e.key === 'v' || e.key === 'V') setTool('select')
      if (e.key === 'c' || e.key === 'C') setTool('razor')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [deleteSelected, undo, redo])

  const addTitle = (text: string, size: number, position: 'top' | 'bottom') => {
    const t: TitleT = { id: newId(), text, start: currentTime, end: currentTime + 3, size, position }
    setTitles((ts) => [...ts, t])
    setSelectedTitleId(t.id)
  }

  // ---------- preview ----------
  const srcUrl = useMemo(() => api.sourceUrl(projectId), [projectId])
  const editUrl = useMemo(() => api.autopilotUrl(projectId), [projectId])
  const renderUrl = useMemo(() => api.editFileUrl(projectId), [projectId])

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    v.src = view === 'rendered' && hasRender ? renderUrl : view === 'edit' && edl ? editUrl : srcUrl
    v.load()
    setCurrentTime(0); setPlaying(false)
  }, [view, edl, hasRender, srcUrl, editUrl, renderUrl])

  const seek = (t: number) => {
    const v = videoRef.current
    if (v) { v.currentTime = t; setCurrentTime(t) }
  }
  const stepFrame = (d: number) => seek(currentTime + d / 30)
  const togglePlay = () => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) v.play(); else v.pause()
  }

  // ---------- keyframe preview (Slice 11): draw the video onto a canvas,
  // applying the JS-interpolated transform of the block under the playhead.
  // Transport (play/pause/seek) still drives the underlying <video>. ------
  // (kfLive wiring lives below, next to blockStarts)
  useEffect(() => {
    let raf = 0
    const draw = () => {
      raf = requestAnimationFrame(draw)
      if (document.hidden) return
      const v = videoRef.current, cv = canvasRef.current
      if (!v || !cv || v.readyState < 2 || !v.videoWidth) return
      const { blocks: blks, starts, view: vw } = kfLive.current
      const cw = cv.clientWidth || v.videoWidth
      const ch = Math.max(1, Math.round((cw * v.videoHeight) / v.videoWidth))
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      if (cv.width !== Math.round(cw * dpr) || cv.height !== Math.round(ch * dpr)) {
        cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr)
      }
      const ctx = cv.getContext('2d')
      if (!ctx) return
      // 'rendered' view already bakes the transforms in — don't double-apply
      let tr = { x: 0, y: 0, scale: 1, rot: 0, op: 1 }
      if (vw !== 'rendered') {
        const ct = v.currentTime
        for (let i = 0; i < blks.length; i++) {
          const d = blockDur(blks[i])
          if (ct >= starts[i] && ct < starts[i] + d) {
            tr = kfTransform(blks[i].keyframes, ct - starts[i])
            break
          }
        }
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, cw, ch)
      ctx.save()
      ctx.globalAlpha = Math.min(1, Math.max(0, tr.op))
      ctx.translate(cw / 2 + tr.x, ch / 2 + tr.y)
      ctx.rotate((tr.rot * Math.PI) / 180)
      ctx.scale(Math.max(0.001, tr.scale), Math.max(0.001, tr.scale))
      const vw2 = v.videoWidth, vh2 = v.videoHeight
      const fit = Math.min(cw / vw2, ch / vh2)
      ctx.drawImage(v, (-vw2 * fit) / 2, (-vh2 * fit) / 2, vw2 * fit, vh2 * fit)
      ctx.restore()
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [])

  // ---------- autopilot / render / seo ----------
  const runAutopilot = async () => {
    setApRunning(true); setApProgress(0); setShowAp(false)
    try {
      const { autopilot_job } = await api.autopilot(projectId, {
        remove_silence: optSilence, silence_pad: 0.2,
        remove_fillers: optFillers, captions: optCaptions,
      })
      const iv = window.setInterval(async () => {
        try {
          const j: JobStatus = await api.job(autopilot_job)
          setApProgress(j.progress)
          if (j.status === 'done' || j.status === 'failed') {
            window.clearInterval(iv)
            setApRunning(false)
            if (j.status === 'failed') { onError(`Autopilot failed: ${j.error}`); return }
            const e = await api.autopilotGet(projectId)
            setEdl(e)
            const b = e.segments.map((s: any) => ({ id: newId(), srcStart: s.start, srcEnd: s.end, speed: 1, muted: false }))
            commit(b)
            setView('edit')
          }
        } catch (e: any) { window.clearInterval(iv); setApRunning(false); onError(e.message) }
      }, 1500)
    } catch (e: any) { setApRunning(false); onError(e.message) }
  }

  const renderEdit = async () => {
    if (!blocks.length) return
    setRenderRunning(true); setRenderProgress(0)
    try {
      const payload = blocks.map((b) => ({ ...b, muted: b.muted || audioMuted }))
      const { render_job } = await api.editRender(projectId, payload, optCaptions, titles)
      const iv = window.setInterval(async () => {
        try {
          const j: JobStatus = await api.job(render_job)
          setRenderProgress(j.progress)
          if (j.status === 'done' || j.status === 'failed') {
            window.clearInterval(iv)
            setRenderRunning(false)
            if (j.status === 'failed') { onError(`Render failed: ${j.error}`); return }
            setHasRender(true); setView('rendered')
          }
        } catch (e: any) { window.clearInterval(iv); setRenderRunning(false); onError(e.message) }
      }, 1500)
    } catch (e: any) { setRenderRunning(false); onError(e.message) }
  }

  const doSeo = async () => {
    setGeneratingSeo(true); setSeoData(null)
    try {
      const { seo_job } = await api.seoGenerate(projectId)
      const iv = window.setInterval(async () => {
        const j: JobStatus = await api.job(seo_job)
        if (j.status === 'done' || j.status === 'failed') {
          window.clearInterval(iv); setGeneratingSeo(false)
          if (j.status === 'failed') { onError(`Packaging failed: ${j.error}`); return }
          setSeoData(await api.seoGet(projectId))
        }
      }, 1500)
    } catch (e: any) { setGeneratingSeo(false); onError(e.message) }
  }

  const selected = blocks.find((b) => b.id === selectedId) ?? null
  const selectedTitle = titles.find((t) => t.id === selectedTitleId) ?? null
  const { starts: blockStarts, total: editTotal } = layoutBlocks(blocks)
  const updateSelected = (patch: Partial<Block>, transient = false) => {
    if (!selected) return
    commit(blocks.map((b) => (b.id === selected.id ? { ...b, ...patch } : b)), transient)
  }
  // latest blocks/layout/view for the canvas preview loop (avoids effect churn)
  const kfLive = useRef({ blocks, starts: blockStarts, view })
  useEffect(() => { kfLive.current = { blocks, starts: blockStarts, view } }, [blocks, blockStarts, view])
  const posterUrl = filmstrip?.thumbs.length ? api.filmstripUrl(projectId, filmstrip.thumbs[0]) : null

  const tabs: { id: Tab; label: string }[] = [
    { id: 'clips', label: '🎯 Clips' },
    { id: 'transcript', label: '📝 Transcript' },
    { id: 'voice', label: '🎙 Voice' },
    { id: 'publish', label: '📦 Publish' },
    { id: 'chat', label: '💬 Co-editor' },
  ]

  return (
    <div className="space-y-4">
      {/* ======= top toolbar ======= */}
      <div className="card px-4 py-2.5 flex items-center gap-2 flex-wrap">
        <div className="min-w-0 mr-2">
          <div className="font-semibold text-sm truncate">{fileName}</div>
          <div className="faint text-[11px]">
            {language && <span className="mr-2">{language}</span>}
            {segments.length} segments · {silences.length} silences
            {edl && <span className="ml-2" style={{ color: 'var(--success)' }}>· autopilot: {edl.cuts} cuts</span>}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <button className="btn-primary px-4 py-2 text-white text-sm" disabled={apRunning}
                    onClick={() => setShowAp((s) => !s)}>
              {apRunning ? `🤖 ${Math.round(apProgress * 100)}%` : '🤖 Autopilot'}
            </button>
            {showAp && !apRunning && (
              <div className="absolute right-0 mt-2 w-72 card p-4 z-20 space-y-2.5 text-sm" style={{ background: 'var(--surface-2)' }}>
                <div className="font-semibold">Autopilot — long-video self-edit</div>
                <p className="muted text-xs">Cuts dead air, burns captions, normalizes loudness. No overcutting.</p>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={optSilence} onChange={(e) => setOptSilence(e.target.checked)} />
                  Cut silences
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={optFillers} onChange={(e) => setOptFillers(e.target.checked)} />
                  Cut filler words <span className="faint text-xs">(um, uh, like…)</span>
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={optCaptions} onChange={(e) => setOptCaptions(e.target.checked)} />
                  Burn captions
                </label>
                <button className="btn-primary w-full py-2 text-white text-sm" onClick={runAutopilot}>
                  ▶ Run autopilot
                </button>
              </div>
            )}
          </div>
          <button className="px-4 py-2 rounded-lg text-sm font-semibold text-white"
                  style={{ background: 'linear-gradient(135deg,#22c55e,#16a34a)' }}
                  disabled={renderRunning || !blocks.length} onClick={renderEdit}>
            {renderRunning ? `Export… ${Math.round(renderProgress * 100)}%` : '⬆ Export'}
          </button>
        </div>
      </div>
      {(apRunning || renderRunning) && (
        <div className="card px-4 py-3">
          <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--surface-2)' }}>
            <div className="h-full rounded-full transition-all"
                 style={{ width: `${(apRunning ? apProgress : renderProgress) * 100}%`, background: 'var(--ai-gradient)' }} />
          </div>
          <div className="muted text-xs mt-1.5">
            {apRunning ? `Autopilot is editing your video… ${Math.round(apProgress * 100)}%`
                       : `Rendering your timeline… ${Math.round(renderProgress * 100)}%`}
          </div>
        </div>
      )}

      {/* ======= 3-column: bin | preview | info+tools ======= */}
      <div className="grid gap-4" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.7fr) minmax(0,1fr)' }}>
        <MediaBin projectId={projectId} fileName={fileName} srcDuration={srcDuration}
                  posterUrl={posterUrl} usedInTimeline={blocks.length > 0}
                  onImport={onImport} mediaTab={mediaTab} setMediaTab={setMediaTab}
                  audioFiles={audioFiles} titles={titles}
                  onAddTitle={addTitle} onDeleteTitle={(id) => setTitles((ts) => ts.filter((t) => t.id !== id))}
                  currentTime={currentTime} />

        <div className="card p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-sm">Player</span>
            <span className="faint text-xs">Full Quality ▾</span>
          </div>
          <div ref={playerWrapRef} className="relative rounded-lg overflow-hidden flex items-center justify-center"
               style={{ background: '#000', maxHeight: '46vh' }}>
            <video ref={videoRef} className="absolute inset-0 w-full h-full"
                   style={{ opacity: 0, pointerEvents: 'none' }}
                   onTimeUpdate={() => setCurrentTime(videoRef.current?.currentTime ?? 0)}
                   onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
                   onLoadedMetadata={() => {
                     const v = videoRef.current
                     if (v?.videoWidth) setVidAspect(`${v.videoWidth} / ${v.videoHeight}`)
                   }} />
            <canvas ref={canvasRef} className="block"
                    style={{ aspectRatio: vidAspect, maxHeight: '46vh', maxWidth: '100%', background: '#000' }} />
          </div>
          {/* transport */}
          <div className="mt-2">
            <input type="range" min={0} max={Math.max(editTotal, 0.01)} step={0.033}
                   value={Math.min(currentTime, editTotal)}
                   onChange={(e) => seek(Number(e.target.value))}
                   className="w-full" />
            <div className="flex items-center justify-between mt-1">
              <div className="flex items-center gap-1">
                <button title="Previous frame" onClick={() => stepFrame(-1)} className="px-2 py-1 card muted text-sm">⏮</button>
                <button title="Play/Pause (Space)" onClick={togglePlay} className="px-3 py-1 card text-sm">
                  {playing ? '⏸' : '▶'}
                </button>
                <button title="Next frame" onClick={() => stepFrame(1)} className="px-2 py-1 card muted text-sm">⏭</button>
                <button title="Stop" onClick={() => { videoRef.current?.pause(); seek(0) }} className="px-2 py-1 card muted text-sm">⏹</button>
              </div>
              <div className="tabular text-xs faint">{fmtTC(currentTime)} <span className="mx-1">/</span> {fmtTC(editTotal || srcDuration)}</div>
              <button title="Fullscreen" onClick={() => playerWrapRef.current?.requestFullscreen?.()}
                      className="px-2 py-1 card muted text-sm">⛶</button>
            </div>
          </div>
          <div className="flex rounded-lg overflow-hidden border text-xs mt-3 w-max" style={{ borderColor: 'var(--border)' }}>
            {(['source', 'edit', 'rendered'] as View[]).map((v) => {
              const enabled = v === 'source' || (v === 'edit' && edl) || (v === 'rendered' && hasRender)
              if (!enabled) return null
              const label = v === 'source' ? 'Source' : v === 'edit' ? '✂ Autopilot' : '⬇ My edit'
              return (
                <button key={v} onClick={() => setView(v)}
                        className={`px-2.5 py-1 ${view === v ? 'btn-primary text-white' : 'muted'}`}>{label}</button>
              )
            })}
          </div>
        </div>

        <div className="space-y-4">
          <ProjectInfo projectId={projectId} projectName={fileName.replace(/\.[^.]+$/, '')} />
          <div className="card p-4">
            {(selected || selectedTitle) && (
              <div className="card p-3 mb-3 text-sm" style={{ background: 'var(--surface-2)', border: '1px solid var(--cyan)' }}>
                <div className="font-semibold text-xs mb-2" style={{ color: 'var(--cyan)' }}>
                  {selected ? 'CLIP PROPERTIES' : 'TITLE PROPERTIES'}
                </div>
                {selected && (
                  <>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div><span className="faint">In</span><div className="tabular">{fmtTime(selected.srcStart)}</div></div>
                      <div><span className="faint">Out</span><div className="tabular">{fmtTime(selected.srcEnd)}</div></div>
                      <div><span className="faint">Duration</span><div className="tabular">{blockDur(selected).toFixed(1)}s</div></div>
                      <div>
                        <span className="faint">Speed</span>
                        <div className="flex items-center gap-1">
                          <input type="range" min={0.5} max={2} step={0.1} value={selected.speed} className="w-16"
                                 onChange={(e) => updateSelected({ speed: Number(e.target.value) })} />
                          <span className="tabular">{selected.speed.toFixed(1)}x</span>
                        </div>
                      </div>
                    </div>
                    <label className="flex items-center gap-2 mt-2 text-xs">
                      <input type="checkbox" checked={selected.muted}
                             onChange={(e) => updateSelected({ muted: e.target.checked })} />
                      Mute this clip
                    </label>
                    {(() => {
                      const idx = blocks.findIndex((b) => b.id === selected.id)
                      if (idx === -1 || idx >= blocks.length - 1) return null
                      const tr: Transition | undefined = selected.transition
                      return (
                        <div className="mt-2 text-xs">
                          <div className="faint mb-1">⤨ Transition → next clip</div>
                          <div className="flex items-center gap-2">
                            <select
                              value={tr?.type ?? 'none'}
                              onChange={(e) => {
                                const v = e.target.value
                                updateSelected({ transition: v === 'none' ? undefined : { type: v, dur: tr?.dur ?? 0.5 } })
                              }}
                              className="card px-1.5 py-1 text-xs max-w-[9.5rem]">
                              <option value="none">None (hard cut)</option>
                              {TRANSITION_TYPES.map((t) => (
                                <option key={t} value={t}>{t}</option>
                              ))}
                            </select>
                            {tr && (
                              <span className="flex items-center gap-1">
                                <input type="number" min={0.1} max={2} step={0.1}
                                       value={tr.dur}
                                       onChange={(e) => updateSelected({
                                         transition: { type: tr.type, dur: clampTransitionDur(Number(e.target.value)) },
                                       })}
                                       className="card px-1.5 py-1 text-xs w-14 tabular" />
                                <span className="faint">s</span>
                              </span>
                            )}
                          </div>
                        </div>
                      )
                    })()}
                    <ColorPanel
                      block={selected}
                      luts={luts}
                      onChange={(patch, transient) => updateSelected(patch, transient)}
                      onCommit={() => commit(blocks)}
                    />
                    <KeyframesEditor
                      block={selected}
                      localNow={currentTime - (blockStarts[blocks.findIndex((b) => b.id === selected.id)] ?? 0)}
                      dur={blockDur(selected)}
                      onChange={(kfs) => updateSelected({ keyframes: kfs }, true)}
                      onCommit={() => commit(blocks)}
                    />
                  </>
                )}
                {selectedTitle && (
                  <div className="text-xs space-y-2">
                    <div className="truncate">“{selectedTitle.text}”</div>
                    <div className="faint tabular">{fmtTC(selectedTitle.start)} → {fmtTC(selectedTitle.end)}</div>
                    <button className="text-xs faint hover:text-white" onClick={() => {
                      setTitles((ts) => ts.filter((t) => t.id !== selectedTitleId))
                      setSelectedTitleId(null)
                    }}>Delete title</button>
                  </div>
                )}
              </div>
            )}
            <div className="flex gap-1 mb-3 flex-wrap">
              {tabs.map((t) => (
                <button key={t.id} onClick={() => setTab(t.id)}
                        className={`px-3 py-1.5 rounded-lg text-xs ${tab === t.id ? 'btn-primary text-white' : 'muted card'}`}>
                  {t.label}
                </button>
              ))}
            </div>
            <div className="max-h-[40vh] overflow-y-auto pr-1">
              {tab === 'clips' && <ClipsPanel projectId={projectId} onError={onError} />}
              {tab === 'transcript' && (
                <div className="space-y-2">
                  {segments.map((s, i) => (
                    <div key={i} className="flex gap-3 text-sm px-3 py-2 rounded-lg" style={{ background: 'var(--surface-2)' }}>
                      <button className="tabular faint shrink-0 w-24 text-left hover:text-white"
                              onClick={() => { setView('source'); seek(s.start) }}>{fmtTime(s.start)}</button>
                      <span>{s.text}</span>
                    </div>
                  ))}
                  {segments.length === 0 && <div className="muted text-sm">No speech detected.</div>}
                </div>
              )}
              {tab === 'voice' && <VoiceStudio projectId={projectId} />}
              {tab === 'publish' && (
                !seoData ? (
                  <div>
                    <p className="muted text-sm mb-3">Keywords, titles, descriptions, hashtags and thumbnail text — per platform, per clip.</p>
                    <button className="btn-primary px-5 py-2.5 text-white text-sm" disabled={generatingSeo} onClick={doSeo}>
                      {generatingSeo ? 'Packaging…' : '📦 Generate packaging'}
                    </button>
                  </div>
                ) : (
                  <div>
                    <button className="text-xs muted underline mb-3" onClick={doSeo} disabled={generatingSeo}>Regenerate</button>
                    <PublishPrep data={seoData} />
                  </div>
                )
              )}
              {tab === 'chat' && <ChatPanel projectId={projectId} />}
            </div>
          </div>
        </div>
      </div>

      {/* ======= timeline toolbar (Filmora-style, above timeline) ======= */}
      <div className="card px-4 py-2 flex items-center gap-1.5">
        <button title="Undo (Ctrl+Z)" disabled={hIdx <= 0} onClick={undo}
                className="px-2.5 py-1.5 rounded-lg card muted text-sm disabled:opacity-30">↩</button>
        <button title="Redo (Ctrl+Y)" disabled={hIdx >= hist.length - 1} onClick={redo}
                className="px-2.5 py-1.5 rounded-lg card muted text-sm disabled:opacity-30">↪</button>
        <button title="Delete selected (Del)" disabled={!selectedId && !selectedTitleId} onClick={deleteSelected}
                className="px-2.5 py-1.5 rounded-lg card muted text-sm disabled:opacity-30">🗑</button>
        <div className="w-px h-6 mx-1" style={{ background: 'var(--border)' }} />
        <div className="flex rounded-lg overflow-hidden border text-sm" style={{ borderColor: 'var(--border)' }}>
          <button title="Select / move / trim (V)" onClick={() => setTool('select')}
                  className={`px-3 py-1.5 ${tool === 'select' ? 'btn-primary text-white' : 'muted'}`}>➤</button>
          <button title="Razor — split clip at click (C)" onClick={() => setTool('razor')}
                  className={`px-3 py-1.5 ${tool === 'razor' ? 'btn-primary text-white' : 'muted'}`}>✂</button>
        </div>
        <span className="faint text-[11px] ml-1 hidden lg:inline">
          {tool === 'razor' ? 'Click a clip to split it' : 'Drag clips to move · drag edges to trim'}
        </span>
        <div className="ml-auto flex items-center gap-2 text-xs muted">
          <button onClick={() => setPxPerSec(Math.max(8, pxPerSec - 12))} className="px-2 py-1 card">−</button>
          <input type="range" min={8} max={160} value={pxPerSec}
                 onChange={(e) => setPxPerSec(Number(e.target.value))} className="w-32" />
          <button onClick={() => setPxPerSec(Math.min(160, pxPerSec + 12))} className="px-2 py-1 card">+</button>
        </div>
      </div>

      {/* ======= timeline ======= */}
      <Timeline blocks={blocks} commit={commit} peaks={peaks} srcDuration={srcDuration || 1}
                filmstrip={filmstrip} filmstripUrl={(n) => api.filmstripUrl(projectId, n)}
                titles={titles} onTitlesCommit={titlesCommit}
                selectedTitleId={selectedTitleId} onSelectTitle={setSelectedTitleId}
                currentTime={currentTime}
                onSeek={seek} selectedId={selectedId} onSelect={setSelectedId}
                tool={tool} pxPerSec={pxPerSec} setPxPerSec={setPxPerSec}
                trackLocked={trackLocked} onToggleLock={() => setTrackLocked((v) => !v)}
                audioMuted={audioMuted} onToggleMute={() => setAudioMuted((v) => !v)} />
    </div>
  )
}
