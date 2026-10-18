import { useCallback, useEffect, useRef, useState } from 'react'
import { api, JobStatus, Segment, Silence } from './api'
import MenuBar from './MenuBar'
import Studio from './Studio'

type Phase = 'idle' | 'uploading' | 'ready' | 'analyzing' | 'analyzed' | 'error'

export default function App() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [dragOver, setDragOver] = useState(false)
  const [projectId, setProjectId] = useState<string | null>(null)
  const [fileName, setFileName] = useState('')
  const [jobs, setJobs] = useState<Record<string, JobStatus>>({})
  const [segments, setSegments] = useState<Segment[]>([])
  const [silences, setSilences] = useState<Silence[]>([])
  const [language, setLanguage] = useState('')
  const [srcDuration, setSrcDuration] = useState(0)
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

  const doUpload = async (file: File) => {
    setError(''); setPhase('uploading')
    try {
      const { project_id, filename } = await api.upload(file)
      setProjectId(project_id); setFileName(filename)
      setSegments([]); setSilences([]); setJobs({}); setLanguage('')
      setPhase('ready')
    } catch (e: any) { setError(e.message); setPhase('error') }
  }

  const doAnalyze = async () => {
    if (!projectId) return
    setError(''); setPhase('analyzing')
    try {
      const { transcribe_job, silence_job, waveform_job, filmstrip_job } = await api.analyze(projectId)
      pollUntilDone([transcribe_job, silence_job, waveform_job, filmstrip_job], async () => {
        const t = await api.transcript(projectId)
        setSegments(t.transcript?.segments ?? [])
        setSilences(t.silence?.silences ?? [])
        setLanguage(t.transcript?.language ?? '')
        try {
          const w = await api.waveform(projectId)
          setSrcDuration(w.duration ?? 0)
        } catch {}
        setPhase('analyzed')
      })
    } catch (e: any) { setError(e.message); setPhase('error') }
  }

  const analyzing = phase === 'analyzing'
  const analyzed = phase === 'analyzed'
  const jobList = Object.values(jobs)
  const overall = jobList.length ? jobList.reduce((a, j) => a + j.progress, 0) / jobList.length : 0

  return (
    <div className="min-h-screen">
      <MenuBar menus={[
        { label: 'File', items: [
          { label: 'Import media…', action: () => document.getElementById('file-input')?.click() },
          { label: 'Project settings…', action: () => window.dispatchEvent(new CustomEvent('open-project-settings')) },
          { label: 'New project', hint: 'Ctrl+N', action: () => window.location.reload() },
        ]},
        { label: 'Edit', items: [
          { label: 'Undo', hint: 'Ctrl+Z', action: () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true })) },
          { label: 'Redo', hint: 'Ctrl+Y', action: () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'y', ctrlKey: true })) },
          { label: 'Delete selected', hint: 'Del', action: () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete' })) },
        ]},
        { label: 'View', items: [
          { label: 'Reload', hint: 'Ctrl+R', action: () => window.location.reload() },
        ]},
        { label: 'Help', items: [
          { label: 'About LocalCut', action: () => alert('LocalCut — free, fully local AI video editor.\nNothing leaves your machine.') },
        ]},
      ]} />
      <header className="border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="max-w-[1400px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div>
              <div className="font-bold text-lg leading-tight">LocalCut <span className="faint font-normal text-sm">Studio</span></div>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="px-3 py-1 rounded-full card muted">Slice 10: Filmora parity</span>
            <span className="px-3 py-1 rounded-full faint border" style={{ borderColor: 'var(--border)' }}>
              <span className="ai-glow font-semibold">100% offline after models</span>
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-[1400px] mx-auto px-6 py-8 space-y-6">
        {!analyzed && (
          <section className="card p-6">
            <h2 className="font-semibold text-lg mb-1">Upload a video</h2>
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

            {projectId && phase === 'ready' && (
              <div className="mt-6">
                <p className="muted text-sm mb-4">
                  The orchestrator queues <span className="ai-glow font-medium">transcription</span>,{' '}
                  <span className="ai-glow font-medium">silence detection</span> and{' '}
                  <span className="ai-glow font-medium">waveform peaks</span> for your timeline.
                </p>
                <button className="btn-primary px-6 py-3 text-white" onClick={doAnalyze}>
                  ✨ Analyze video
                </button>
              </div>
            )}

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
            {error && (
              <div className="mt-4 text-sm px-4 py-3 rounded-lg"
                   style={{ background: 'rgba(248,113,113,.12)', color: 'var(--danger)' }}>{error}</div>
            )}
          </section>
        )}

        {analyzed && projectId && (
          <Studio projectId={projectId} fileName={fileName}
                  segments={segments} silences={silences} language={language}
                  srcDuration={srcDuration}
                  onError={(m) => setError(m)}
                  onImport={doUpload} />
        )}
        {error && analyzed && (
          <div className="text-sm px-4 py-3 rounded-lg"
               style={{ background: 'rgba(248,113,113,.12)', color: 'var(--danger)' }}>{error}</div>
        )}

        <footer className="faint text-xs text-center pt-4">
          Slice 10 of the roadmap — Filmora parity. Nothing leaves your machine.
        </footer>
      </main>
    </div>
  )
}
