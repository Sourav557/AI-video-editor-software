import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, fmtTime, JobStatus, Segment, Silence } from './api'
import Timeline, { Block, blockDur, layoutBlocks, newId } from './Timeline'
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
}

interface Edl {
  segments: { start: number; end: number; kind: string }[]
  source_duration: number
  output_duration: number
  cuts: number
}

type View = 'source' | 'edit' | 'rendered'
type Tab = 'media' | 'clips' | 'transcript' | 'voice' | 'publish' | 'chat'

export default function Studio({ projectId, fileName, segments, silences, language, srcDuration, onError }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [peaks, setPeaks] = useState<number[]>([])
  const [edl, setEdl] = useState<Edl | null>(null)
  const [hasRender, setHasRender] = useState(false)
  const [view, setView] = useState<View>('source')
  const [tab, setTab] = useState<Tab>('media')

  // --- timeline editing state (Filmora-style) ---
  const [blocks, setBlocks] = useState<Block[]>([])
  const [hist, setHist] = useState<Block[][]>([])
  const [hIdx, setHIdx] = useState(-1)
  const [tool, setTool] = useState<'select' | 'razor'>('select')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [trackLocked, setTrackLocked] = useState(false)
  const [audioMuted, setAudioMuted] = useState(false)

  const [currentTime, setCurrentTime] = useState(0)
  const [pxPerSec, setPxPerSec] = useState(40)
  const [showAp, setShowAp] = useState(false)
  const [apRunning, setApRunning] = useState(false)
  const [apProgress, setApProgress] = useState(0)
  const [renderRunning, setRenderRunning] = useState(false)
  const [renderProgress, setRenderProgress] = useState(0)
  const [optSilence, setOptSilence] = useState(true)
  const [optFillers, setOptFillers] = useState(false)
  const [optCaptions, setOptCaptions] = useState(true)
  const [seoData, setSeoData] = useState<any>(null)
  const [generatingSeo, setGeneratingSeo] = useState(false)

  useEffect(() => {
    api.waveform(projectId).then((w) => setPeaks(w.peaks ?? [])).catch(() => {})
    api.autopilotGet(projectId)
      .then((e) => { setEdl(e); setBlocks(fromEdl(e)) })
      .catch(() => {})
    api.editGet(projectId).then(() => setHasRender(true)).catch(() => {})
  }, [projectId])

  function fromEdl(e: Edl): Block[] {
    return e.segments.map((s) => ({
      id: newId(), srcStart: s.start, srcEnd: s.end, speed: 1, muted: false,
    }))
  }

  // seed a single full-length block once the source duration is known
  useEffect(() => {
    if (srcDuration > 0 && blocks.length === 0 && !edl) {
      const b: Block[] = [{ id: newId(), srcStart: 0, srcEnd: srcDuration, speed: 1, muted: false }]
      setBlocks(b); setHist([b]); setHIdx(0)
      setPxPerSec(Math.max(8, Math.min(160, 900 / srcDuration)))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srcDuration])

  const commit = useCallback((next: Block[], transient = false) => {
    if (transient) { setBlocks(next); return } // live drag preview: no history spam
    setHist((h) => {
      const nh = [...h.slice(0, hIdx + 1), next]
      return nh.length > 100 ? nh.slice(-100) : nh
    })
    setHIdx((i) => i + 1)
    setBlocks(next)
  }, [hIdx])

  const undo = useCallback(() => {
    if (hIdx > 0) { setHIdx(hIdx - 1); setBlocks(hist[hIdx - 1]); setSelectedId(null) }
  }, [hIdx, hist])
  const redo = useCallback(() => {
    if (hIdx < hist.length - 1) { setHIdx(hIdx + 1); setBlocks(hist[hIdx + 1]) }
  }, [hIdx, hist])

  const deleteSelected = useCallback(() => {
    if (!selectedId || trackLocked) return
    commit(blocks.filter((b) => b.id !== selectedId))
    setSelectedId(null)
  }, [selectedId, blocks, commit, trackLocked])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') return
      if ((e.key === 'Delete' || e.key === 'Backspace')) { e.preventDefault(); deleteSelected() }
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo() }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { e.preventDefault(); redo() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [deleteSelected, undo, redo])

  const srcUrl = useMemo(() => api.sourceUrl(projectId), [projectId])
  const editUrl = useMemo(() => api.autopilotUrl(projectId), [projectId])
  const renderUrl = useMemo(() => api.editFileUrl(projectId), [projectId])

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    v.src = view === 'rendered' && hasRender ? renderUrl : view === 'edit' && edl ? editUrl : srcUrl
    v.load()
    setCurrentTime(0)
  }, [view, edl, hasRender, srcUrl, editUrl, renderUrl])

  const onTimeUpdate = () => setCurrentTime(videoRef.current?.currentTime ?? 0)
  const seek = (t: number) => {
    const v = videoRef.current
    if (v) { v.currentTime = t; setCurrentTime(t) }
  }

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
            const b = fromEdl(e)
            setBlocks(b); setHist([b]); setHIdx(0)
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
      const { render_job } = await api.editRender(projectId, payload, optCaptions)
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
  const { total: editTotal } = layoutBlocks(blocks)

  const updateSelected = (patch: Partial<Block>) => {
    if (!selected) return
    commit(blocks.map((b) => (b.id === selected.id ? { ...b, ...patch } : b)))
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'media', label: '🗂 Media' },
    { id: 'clips', label: '🎯 Clips' },
    { id: 'transcript', label: '📝 Transcript' },
    { id: 'voice', label: '🎙 Voice' },
    { id: 'publish', label: '📦 Publish' },
    { id: 'chat', label: '💬 Co-editor' },
  ]

  const mediaItems = [
    { name: 'Source', url: srcUrl, tag: 'source' },
    ...(edl ? [{ name: 'Autopilot edit', url: editUrl, tag: 'edit' }] : []),
    ...(hasRender ? [{ name: 'My edit', url: renderUrl, tag: 'rendered' }] : []),
  ]

  return (
    <div className="space-y-4">
      {/* ======= toolbar (Filmora-style) ======= */}
      <div className="card px-4 py-2.5 flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1 mr-1">
          <button title="Undo (Ctrl+Z)" disabled={hIdx <= 0} onClick={undo}
                  className="px-2.5 py-1.5 rounded-lg card muted text-sm disabled:opacity-30">↩</button>
          <button title="Redo (Ctrl+Y)" disabled={hIdx >= hist.length - 1} onClick={redo}
                  className="px-2.5 py-1.5 rounded-lg card muted text-sm disabled:opacity-30">↪</button>
        </div>
        <div className="flex rounded-lg overflow-hidden border text-sm" style={{ borderColor: 'var(--border)' }}>
          <button title="Select / move / trim (V)" onClick={() => setTool('select')}
                  className={`px-3 py-1.5 ${tool === 'select' ? 'btn-primary text-white' : 'muted'}`}>➤ Select</button>
          <button title="Razor — split clip at click (C)" onClick={() => setTool('razor')}
                  className={`px-3 py-1.5 ${tool === 'razor' ? 'btn-primary text-white' : 'muted'}`}>✂ Razor</button>
        </div>
        <button title="Delete selected (Del)" disabled={!selectedId} onClick={deleteSelected}
                className="px-3 py-1.5 rounded-lg card muted text-sm disabled:opacity-30">🗑 Delete</button>

        <div className="ml-auto flex items-center gap-2">
          {edl && (
            <div className="faint text-xs mr-1">autopilot: {edl.cuts} cuts</div>
          )}
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
            {renderRunning ? `Rendering… ${Math.round(renderProgress * 100)}%` : '⬇ Export edit'}
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

      {/* ======= preview + side panel ======= */}
      <div className="grid gap-4" style={{ gridTemplateColumns: 'minmax(0,1.6fr) minmax(0,1fr)' }}>
        <div className="card p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-sm">Preview <span className="faint font-normal">· {fileName}</span></span>
            <div className="flex rounded-lg overflow-hidden border text-xs" style={{ borderColor: 'var(--border)' }}>
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
          <video ref={videoRef} controls className="w-full rounded-lg max-h-[52vh]" style={{ background: '#000' }}
                 onTimeUpdate={onTimeUpdate} />
          <div className="faint text-xs mt-2 tabular">
            {language && <span className="mr-2">{language}</span>}
            {segments.length} segments · {silences.length} silences · timeline {fmtTime(editTotal)}
          </div>
        </div>

        <div className="card p-4 min-h-[300px]">
          {selected && (
            <div className="card p-3 mb-3 text-sm" style={{ background: 'var(--surface-2)', border: '1px solid var(--cyan)' }}>
              <div className="font-semibold text-xs mb-2" style={{ color: 'var(--cyan)' }}>CLIP PROPERTIES</div>
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
          <div className="max-h-[52vh] overflow-y-auto pr-1">
            {tab === 'media' && (
              <div className="grid grid-cols-2 gap-3">
                {mediaItems.map((m) => (
                  <button key={m.tag} className="card p-2 text-left" style={{ background: 'var(--surface-2)' }}
                          onClick={() => setView(m.tag as View)}>
                    <video src={m.url} preload="metadata" muted playsInline className="w-full rounded aspect-video" style={{ background: '#000' }} />
                    <div className="text-xs font-medium mt-1.5">{m.name}</div>
                    <div className="faint text-[10px]">click to preview</div>
                  </button>
                ))}
              </div>
            )}
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

      {/* ======= timeline ======= */}
      <Timeline blocks={blocks} commit={commit} peaks={peaks} srcDuration={srcDuration || 1}
                currentTime={view === 'source' ? currentTime : currentTime}
                onSeek={seek} selectedId={selectedId} onSelect={setSelectedId}
                tool={tool} pxPerSec={pxPerSec} setPxPerSec={setPxPerSec}
                trackLocked={trackLocked} onToggleLock={() => setTrackLocked((v) => !v)}
                audioMuted={audioMuted} onToggleMute={() => setAudioMuted((v) => !v)} />
    </div>
  )
}
