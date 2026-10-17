import { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtTime, JobStatus, Segment, Silence } from './api'

type Phase = 'idle' | 'uploading' | 'ready' | 'analyzing' | 'done' | 'error'

export default function App() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [dragOver, setDragOver] = useState(false)
  const [projectId, setProjectId] = useState<string | null>(null)
  const [fileName, setFileName] = useState('')
  const [jobs, setJobs] = useState<Record<string, JobStatus>>({})
  const [segments, setSegments] = useState<Segment[]>([])
  const [silences, setSilences] = useState<Silence[]>([])
  const [language, setLanguage] = useState('')
  const [error, setError] = useState('')
  const pollRef = useRef<number | null>(null)

  const stopPolling = () => {
    if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null }
  }

  const pollJobs = useCallback((ids: string[], pid: string) => {
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
          if (failed) {
            setError(`Job "${failed.kind}" failed: ${failed.error}`)
            setPhase('error')
            return
          }
          const t = await api.transcript(pid)
          setSegments(t.transcript?.segments ?? [])
          setSilences(t.silence?.silences ?? [])
          setLanguage(t.transcript?.language ?? '')
          setPhase('done')
        }
      } catch (e: any) {
        stopPolling()
        setError(e.message)
        setPhase('error')
      }
    }, 1000)
  }, [])

  useEffect(() => () => stopPolling(), [])

  const doUpload = async (file: File) => {
    setError(''); setPhase('uploading')
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
      pollJobs([transcribe_job, silence_job], projectId)
    } catch (e: any) { setError(e.message); setPhase('error') }
  }

  const analyzing = phase === 'analyzing'
  const jobList = Object.values(jobs)
  const overall =
    jobList.length ? jobList.reduce((a, j) => a + j.progress, 0) / jobList.length : 0

  return (
    <div className="min-h-screen">
      {/* Header */}
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
            <span className="px-3 py-1 rounded-full card muted">Slice 1: Transcribe + Silence</span>
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
            <input
              type="file" accept="video/*" className="hidden" id="file-input"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) doUpload(f) }}
            />
            <label htmlFor="file-input" className="cursor-pointer">
              <div className="text-4xl mb-2">🎬</div>
              {phase === 'uploading'
                ? <div className="muted">Uploading…</div>
                : fileName
                  ? <div><span className="font-medium">{fileName}</span><div className="faint text-sm mt-1">Drop another to replace</div></div>
                  : <div><span className="font-medium">Drop a video here</span> <span className="muted">or click to browse</span></div>}
            </label>
          </div>

          <h2 className="font-semibold text-lg mt-6 mb-1">2 · Analyze</h2>
          <p className="muted text-sm mb-4">
            The orchestrator queues two independent workers — <span className="ai-glow font-medium">transcription</span> (word timestamps)
            and <span className="ai-glow font-medium">silence detection</span> — and runs them without blocking each other.
          </p>
          <button className="btn-primary px-6 py-3 text-white" disabled={!projectId || analyzing || phase === 'uploading'} onClick={doAnalyze}>
            {analyzing ? 'Analyzing…' : '✨ Analyze video'}
          </button>

          {analyzing && (
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
          )}
          {error && <div className="mt-4 text-sm px-4 py-3 rounded-lg" style={{ background: 'rgba(248,113,113,.12)', color: 'var(--danger)' }}>{error}</div>}
        </section>

        {/* Results */}
        {(phase === 'done') && (
          <>
            <section className="grid grid-cols-3 gap-4">
              <Stat label="Language" value={language || '—'} />
              <Stat label="Segments" value={String(segments.length)} />
              <Stat label="Silences" value={String(silences.length)} />
            </section>

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

            <section className="card p-6">
              <h2 className="font-semibold text-lg mb-3">Silence gaps <span className="faint text-sm font-normal">· candidates for auto-cut</span></h2>
              <div className="flex flex-wrap gap-2">
                {silences.map((s, i) => (
                  <span key={i} className="tabular text-xs px-3 py-1.5 rounded-full card muted">
                    {fmtTime(s.start)} → {fmtTime(s.end)} <span className="faint">({s.duration}s)</span>
                  </span>
                ))}
                {silences.length === 0 && <div className="muted text-sm">No silences found.</div>}
              </div>
            </section>
          </>
        )}

        <footer className="faint text-xs text-center pt-4">
          Slice 1 of the roadmap — next: clip quality engine, captions, multi-platform export. Nothing leaves your machine.
        </footer>
      </main>
    </div>
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
