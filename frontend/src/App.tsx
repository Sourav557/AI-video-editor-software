import { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtTime, JobStatus, Segment, Silence } from './api'
import VoiceStudio from './VoiceStudio'
import PublishPrep from './PublishPrep'

type Phase = 'idle' | 'uploading' | 'ready' | 'analyzing' | 'analyzed' | 'error'

interface Clip {
  index: number
  start: number
  end: number
  duration: number
  hook_text: string
  score: number
  breakdown: Record<string, number>
  reason: string
}

export default function App() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [dragOver, setDragOver] = useState(false)
  const [projectId, setProjectId] = useState<string | null>(null)
  const [fileName, setFileName] = useState('')
  const [jobs, setJobs] = useState<Record<string, JobStatus>>({})
  const [segments, setSegments] = useState<Segment[]>([])
  const [silences, setSilences] = useState<Silence[]>([])
  const [language, setLanguage] = useState('')
  const [clips, setClips] = useState<Clip[]>([])
  const [clipMsg, setClipMsg] = useState('')
  const [finding, setFinding] = useState(false)
  const [rendering, setRendering] = useState<Record<number, string>>({})
  const [rendered, setRendered] = useState<Record<number, boolean>>({})
  const [platforms, setPlatforms] = useState<[string, string][]>([])
  const [exporting, setExporting] = useState<Record<string, boolean>>({})
  const [exported, setExported] = useState<Record<string, string>>({})
  const [seoData, setSeoData] = useState<any>(null)
  const [generatingSeo, setGeneratingSeo] = useState(false)
  const [error, setError] = useState('')
  const pollRef = useRef<number | null>(null)

  const stopPolling = () => {
    if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null }
  }

  const pollUntilDone = useCallback(
    (ids: string[], onDone: () => Promise<void> | void) => {
      stopPolling()
      pollRef.current = window.setInterval(async () => {
        try {
          const statuses = await Promise.all(ids.map((id) => api.job(id)))
          const map: Record<string, JobStatus> = {}
          statuses.forEach((s) => (map[s.id] = s))
          setJobs(map)
          if (statuses.every((s) => s.status === 'done' || s.status === 'failed')) {
            stopPolling()
            const failed = statuses.find((s) => s.status === 'failed')
            if (failed) { setError(`Job "${failed.kind}" failed: ${failed.error}`); setPhase('error'); return }
            await onDone()
          }
        } catch (e: any) {
          stopPolling(); setError(e.message); setPhase('error')
        }
      }, 1000)
    },
    [],
  )

  useEffect(() => () => stopPolling(), [])

  useEffect(() => {
    api.platforms()
      .then((p) => setPlatforms(Object.entries(p.platforms).map(([k, v]) => [k, v.label])))
      .catch(() => {})
  }, [])

  const doUpload = async (file: File) => {
    setError(''); setPhase('uploading')
    setClips([]); setClipMsg(''); setRendered({}); setRendering({})
    try {
      const { project_id, filename } = await api.upload(file)
      setProjectId(project_id); setFileName(filename)
      setSegments([]); setSilences([]); setJobs({})
      setPhase('ready')
    } catch (e: any) { setError(e.message); setPhase('error') }
  }

  const doAnalyze = async () => {
    if (!projectId) return
    setError(''); setPhase('analyzing')
    try {
      const { transcribe_job, silence_job } = await api.analyze(projectId)
      pollUntilDone([transcribe_job, silence_job], async () => {
        const t = await api.transcript(projectId)
        setSegments(t.transcript?.segments ?? [])
        setSilences(t.silence?.silences ?? [])
        setLanguage(t.transcript?.language ?? '')
        setPhase('analyzed')
      })
    } catch (e: any) { setError(e.message); setPhase('error') }
  }

  const doFindClips = async () => {
    if (!projectId) return
    setError(''); setFinding(true)
    try {
      const { score_job } = await api.findClips(projectId)
      pollUntilDone([score_job], async () => {
        const c = await api.clips(projectId)
        setClips(c.clips ?? [])
        setClipMsg(c.message ?? '')
        setFinding(false)
      })
    } catch (e: any) { setError(e.message); setFinding(false) }
  }

  const doRender = async (idx: number) => {
    if (!projectId) return
    setError('')
    setRendering((r) => ({ ...r, [idx]: 'queued' }))
    try {
      const { render_job } = await api.renderClip(projectId, idx)
      pollUntilDone([render_job], async () => {
        setRendered((r) => ({ ...r, [idx]: true }))
        setRendering((r) => { const n = { ...r }; delete n[idx]; return n })
      })
    } catch (e: any) {
      setError(e.message)
      setRendering((r) => { const n = { ...r }; delete n[idx]; return n })
    }
  }

  const doSeo = async () => {
    if (!projectId) return
    setError(''); setGeneratingSeo(true); setSeoData(null)
    try {
      const { seo_job } = await api.seoGenerate(projectId)
      pollUntilDone([seo_job], async () => {
        setSeoData(await api.seoGet(projectId))
        setGeneratingSeo(false)
      })
    } catch (e: any) { setError(e.message); setGeneratingSeo(false) }
  }

  const doExport = async (idx: number, platform: string) => {
    if (!projectId) return
    const key = `${idx}-${platform}`
    setError('')
    setExporting((e) => ({ ...e, [key]: true }))
    try {
      const { export_job } = await api.exportClip(projectId, idx, platform)
      pollUntilDone([export_job], async () => {
        setExported((e) => ({ ...e, [key]: `export_${platform}_clip${idx}.mp4` }))
        setExporting((e) => { const n = { ...e }; delete n[key]; return n })
      })
    } catch (e: any) {
      setError(e.message)
      setExporting((e) => { const n = { ...e }; delete n[key]; return n })
    }
  }

  const analyzing = phase === 'analyzing'
  const analyzed = phase === 'analyzed'
  const jobList = Object.values(jobs)
  const overall = jobList.length ? jobList.reduce((a, j) => a + j.progress, 0) / jobList.length : 0

  return (
    <div className="min-h-screen">
      <header className="border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center font-bold text-lg"
                 style={{ background: 'var(--ai-gradient)' }}>L</div>
            <div>
              <div className="font-bold text-lg leading-tight">LocalCut</div>
              <div className="faint text-xs">Free · Local · AI Video Editor</div>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="px-3 py-1 rounded-full card muted">Slice 5: Publish prep</span>
            <span className="px-3 py-1 rounded-full faint border" style={{ borderColor: 'var(--border)' }}>
              <span className="ai-glow font-semibold">100% offline after models</span>
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        {/* Upload / Analyze */}
        <section className="card p-6">
          <h2 className="font-semibold text-lg mb-1">1 · Upload a video</h2>
          <p className="muted text-sm mb-4">Drop a file below. It never leaves your machine.</p>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) doUpload(f) }}
            className="rounded-xl border-2 border-dashed p-10 text-center transition-colors"
            style={{ borderColor: dragOver ? 'var(--accent)' : 'var(--border)', background: 'var(--surface-2)' }}
          >
            <input type="file" accept="video/*" className="hidden" id="file-input"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) doUpload(f) }} />
            <label htmlFor="file-input" className="cursor-pointer">
              <div className="text-4xl mb-2">🎬</div>
              {phase === 'uploading' ? <div className="muted">Uploading…</div>
                : fileName ? <div><span className="font-medium">{fileName}</span><div className="faint text-sm mt-1">Drop another to replace</div></div>
                : <div><span className="font-medium">Drop a video here</span> <span className="muted">or click to browse</span></div>}
            </label>
          </div>

          <h2 className="font-semibold text-lg mt-6 mb-1">2 · Analyze</h2>
          <p className="muted text-sm mb-4">
            The orchestrator queues two independent workers — <span className="ai-glow font-medium">transcription</span> and{' '}
            <span className="ai-glow font-medium">silence detection</span> — running without blocking each other.
          </p>
          <button className="btn-primary px-6 py-3 text-white" disabled={!projectId || analyzing || phase === 'uploading'} onClick={doAnalyze}>
            {analyzing ? 'Analyzing…' : '✨ Analyze video'}
          </button>

          {analyzing && <ProgressBar overall={overall} jobList={jobList} />}
          {error && <ErrorBox message={error} />}
        </section>

        {/* Analysis results */}
        {analyzed && (
          <>
            <section className="grid grid-cols-3 gap-4">
              <Stat label="Language" value={language || '—'} />
              <Stat label="Segments" value={String(segments.length)} />
              <Stat label="Silences" value={String(silences.length)} />
            </section>

            {/* Clip engine */}
            <section className="card p-6">
              <h2 className="font-semibold text-lg mb-1">3 · Find viral clips</h2>
              <p className="muted text-sm mb-4">
                The quality engine scores every 15–60s moment on hook, completeness, pacing and length —
                and <span className="ai-glow font-medium">rejects weak clips instead of padding the count</span>.
              </p>
              <button className="btn-primary px-6 py-3 text-white" disabled={finding} onClick={doFindClips}>
                {finding ? 'Scoring moments…' : '🎯 Find clips'}
              </button>
              {finding && <ProgressBar overall={overall} jobList={jobList} />}
              {clipMsg && !finding && <p className="muted text-sm mt-3">{clipMsg}</p>}

              <div className="grid md:grid-cols-2 gap-4 mt-4">
                {clips.map((c) => (
                  <div key={c.index} className="card p-4" style={{ background: 'var(--surface-2)' }}>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="tabular faint text-xs">{fmtTime(c.start)} → {fmtTime(c.end)} · {c.duration}s</div>
                        <div className="font-medium mt-1">“{c.hook_text}”</div>
                        <div className="muted text-sm mt-1">{c.reason}</div>
                      </div>
                      <ScoreRing score={c.score} />
                    </div>
                    <div className="mt-3 space-y-1">
                      {Object.entries(c.breakdown).map(([k, v]) => (
                        <div key={k} className="flex items-center gap-2 text-xs">
                          <span className="muted w-24 shrink-0">{k.replace('_', ' ')}</span>
                          <div className="flex-1 h-1.5 rounded-full" style={{ background: 'var(--bg)' }}>
                            <div className="h-full rounded-full" style={{ width: `${Math.min(100, v * 100)}%`, background: 'var(--ai-gradient)' }} />
                          </div>
                          <span className="tabular faint w-8 text-right">{v.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                    <div className="mt-4">
                      {rendered[c.index] && projectId ? (
                        <div className="space-y-2">
                          <video controls className="w-full rounded-lg max-h-80" style={{ background: '#000' }}
                            src={`/api/projects/${projectId}/clips/${c.index}/file`} />
                          <a className="text-sm underline" style={{ color: 'var(--cyan)' }}
                             href={`/api/projects/${projectId}/clips/${c.index}/file`} download>
                            ⬇ Download 9:16 captioned clip
                          </a>
                        </div>
                      ) : (
                        <button className="btn-primary px-4 py-2 text-white text-sm"
                                disabled={c.index in rendering} onClick={() => doRender(c.index)}>
                          {c.index in rendering ? 'Rendering…' : '🎞 Render 9:16 captioned clip'}
                        </button>
                      )}
                    </div>
                    {/* Multi-platform export */}
                    <div className="mt-3 pt-3 border-t" style={{ borderColor: 'var(--border)' }}>
                      <div className="faint text-xs mb-2">Export for platform <span className="ai-glow">· aspect + captions + loudness</span></div>
                      <div className="flex flex-wrap gap-2">
                        {platforms.map(([key, label]) => {
                          const ek = `${c.index}-${key}`
                          return exported[ek] && projectId ? (
                            <a key={key} className="text-xs px-3 py-1.5 rounded-full card"
                               style={{ color: 'var(--cyan)' }}
                               href={`/api/projects/${projectId}/exports/${exported[ek]}`} download>
                              ⬇ {label}
                            </a>
                          ) : (
                            <button key={key}
                              className="text-xs px-3 py-1.5 rounded-full card muted hover:text-white"
                              disabled={ek in exporting}
                              onClick={() => doExport(c.index, key)}>
                              {ek in exporting ? '…' : label}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* Transcript */}
            <section className="card p-6">
              <h2 className="font-semibold text-lg mb-3">Transcript <span className="faint text-sm font-normal">· word-level timestamps</span></h2>
              <div className="space-y-2 max-h-96 overflow-y-auto pr-2">
                {segments.map((s, i) => (
                  <div key={i} className="flex gap-3 text-sm px-3 py-2 rounded-lg" style={{ background: 'var(--surface-2)' }}>
                    <span className="tabular faint shrink-0 w-24">{fmtTime(s.start)} → {fmtTime(s.end)}</span>
                    <span>{s.text}</span>
                  </div>
                ))}
                {segments.length === 0 && <div className="muted text-sm">No speech detected.</div>}
              </div>
            </section>

            {/* Voice studio */}
            <section className="card p-6">
              <h2 className="font-semibold text-lg mb-1">4 · Voice studio</h2>
              <p className="muted text-sm mb-4">
                <span className="ai-glow font-medium">Qwen3-TTS</span> voiceovers — preset voices with emotion direction,
                or clone your own voice from a 3s+ clip (consent-gated).
              </p>
              {projectId && <VoiceStudio projectId={projectId} />}
            </section>

            {/* Publish prep */}
            <section className="card p-6">
              <h2 className="font-semibold text-lg mb-1">5 · Publish prep</h2>
              <p className="muted text-sm mb-4">
                The <span className="ai-glow font-medium">packaging engine</span> turns your transcript into ranked keywords,
                titles, descriptions, hashtags and thumbnail text — per platform, per clip.
              </p>
              {!seoData ? (
                <>
                  <button className="btn-primary px-6 py-3 text-white" disabled={generatingSeo} onClick={doSeo}>
                    {generatingSeo ? 'Packaging…' : '📦 Generate packaging'}
                  </button>
                  {generatingSeo && <ProgressBar overall={overall} jobList={jobList} />}
                </>
              ) : (
                <>
                  <button className="text-sm muted underline mb-4" onClick={doSeo} disabled={generatingSeo}>
                    Regenerate
                  </button>
                  <PublishPrep data={seoData} />
                </>
              )}
            </section>
          </>
        )}

        <footer className="faint text-xs text-center pt-4">
          Slice 5 of the roadmap — next: the editing agent, then the .exe desktop build. Nothing leaves your machine.
        </footer>
      </main>
    </div>
  )
}

function ProgressBar({ overall, jobList }: { overall: number; jobList: JobStatus[] }) {
  return (
    <div className="mt-4">
      <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--surface-2)' }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${overall * 100}%`, background: 'var(--ai-gradient)' }} />
      </div>
      <div className="mt-2 space-y-1">
        {jobList.map((j) => (
          <div key={j.id} className="text-sm muted flex justify-between">
            <span className="tabular">{j.kind}</span>
            <span>{j.status} · {Math.round(j.progress * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="mt-4 text-sm px-4 py-3 rounded-lg"
         style={{ background: 'rgba(248,113,113,.12)', color: 'var(--danger)' }}>{message}</div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card p-4">
      <div className="faint text-xs uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-bold mt-1 tabular">{value}</div>
    </div>
  )
}

function ScoreRing({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = score >= 0.7 ? 'var(--success)' : score >= 0.55 ? 'var(--warning)' : 'var(--danger)'
  return (
    <div className="w-14 h-14 rounded-full flex items-center justify-center shrink-0 font-bold tabular"
         style={{ border: `3px solid ${color}` }}>
      {pct}
    </div>
  )
}
