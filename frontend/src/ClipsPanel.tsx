import { useEffect, useState } from 'react'
import { api, fmtTime, JobStatus } from './api'

interface Clip {
  index: number; start: number; end: number; duration: number
  hook_text: string; score: number; breakdown: Record<string, number>; reason: string
}

function usePoll() {
  const [jobs, setJobs] = useState<Record<string, JobStatus>>({})
  const poll = (ids: string[], onDone: () => Promise<void> | void, onFail: (msg: string) => void) => {
    const iv = window.setInterval(async () => {
      try {
        const statuses = await Promise.all(ids.map((id) => api.job(id)))
        const map: Record<string, JobStatus> = {}
        statuses.forEach((s) => (map[s.id] = s))
        setJobs(map)
        if (statuses.every((s) => s.status === 'done' || s.status === 'failed')) {
          window.clearInterval(iv)
          const failed = statuses.find((s) => s.status === 'failed')
          if (failed) { onFail(`Job "${failed.kind}" failed: ${failed.error}`); return }
          await onDone()
        }
      } catch (e: any) { window.clearInterval(iv); onFail(e.message) }
    }, 1000)
    return () => window.clearInterval(iv)
  }
  return { jobs, poll }
}

export default function ClipsPanel({ projectId, onError }: { projectId: string; onError: (m: string) => void }) {
  const [clips, setClips] = useState<Clip[]>([])
  const [clipMsg, setClipMsg] = useState('')
  const [finding, setFinding] = useState(false)
  const [rendering, setRendering] = useState<Record<number, boolean>>({})
  const [rendered, setRendered] = useState<Record<number, boolean>>({})
  const [platforms, setPlatforms] = useState<[string, string][]>([])
  const [exporting, setExporting] = useState<Record<string, boolean>>({})
  const [exported, setExported] = useState<Record<string, string>>({})
  const { jobs, poll } = usePoll()
  const jobList = Object.values(jobs)

  useEffect(() => {
    api.platforms()
      .then((p) => setPlatforms(Object.entries(p.platforms).map(([k, v]) => [k, (v as any).label])))
      .catch(() => {})
  }, [])

  const doFindClips = async () => {
    setFinding(true)
    try {
      const { score_job } = await api.findClips(projectId)
      poll([score_job], async () => {
        const c = await api.clips(projectId)
        setClips(c.clips ?? []); setClipMsg(c.message ?? ''); setFinding(false)
      }, (m) => { onError(m); setFinding(false) })
    } catch (e: any) { onError(e.message); setFinding(false) }
  }

  const doRender = async (idx: number) => {
    setRendering((r) => ({ ...r, [idx]: true }))
    try {
      const { render_job } = await api.renderClip(projectId, idx)
      poll([render_job], async () => {
        setRendered((r) => ({ ...r, [idx]: true }))
        setRendering((r) => { const n = { ...r }; delete n[idx]; return n })
      }, (m) => { onError(m); setRendering((r) => { const n = { ...r }; delete n[idx]; return n }) })
    } catch (e: any) { onError(e.message); setRendering((r) => { const n = { ...r }; delete n[idx]; return n }) }
  }

  const doExport = async (idx: number, platform: string) => {
    const key = `${idx}-${platform}`
    setExporting((e) => ({ ...e, [key]: true }))
    try {
      const { export_job } = await api.exportClip(projectId, idx, platform)
      poll([export_job], async () => {
        setExported((e) => ({ ...e, [key]: `export_${platform}_clip${idx}.mp4` }))
        setExporting((e) => { const n = { ...e }; delete n[key]; return n })
      }, (m) => { onError(m); setExporting((e) => { const n = { ...e }; delete n[key]; return n }) })
    } catch (e: any) { onError(e.message); setExporting((e) => { const n = { ...e }; delete n[key]; return n }) }
  }

  return (
    <div>
      <p className="muted text-sm mb-4">
        The quality engine scores every 15–60s moment — and{' '}
        <span className="ai-glow font-medium">rejects weak clips instead of padding the count</span>.
      </p>
      <button className="btn-primary px-5 py-2.5 text-white text-sm" disabled={finding} onClick={doFindClips}>
        {finding ? 'Scoring moments…' : '🎯 Find clips'}
      </button>
      {finding && jobList.length > 0 && (
        <div className="text-xs muted mt-2 tabular">
          {jobList.map((j) => `${j.kind}: ${j.status} ${Math.round(j.progress * 100)}%`).join(' · ')}
        </div>
      )}
      {clipMsg && !finding && <p className="muted text-sm mt-3">{clipMsg}</p>}

      <div className="space-y-3 mt-4">
        {clips.map((c) => (
          <div key={c.index} className="card p-3" style={{ background: 'var(--surface-2)' }}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="tabular faint text-xs">{fmtTime(c.start)} → {fmtTime(c.end)} · {c.duration}s</div>
                <div className="font-medium mt-1 text-sm">“{c.hook_text}”</div>
                <div className="muted text-xs mt-1">{c.reason}</div>
              </div>
              <ScoreRing score={c.score} />
            </div>
            <div className="mt-3">
              {rendered[c.index] ? (
                <div className="space-y-2">
                  <video controls className="w-full rounded-lg max-h-64" style={{ background: '#000' }}
                    src={`/api/projects/${projectId}/clips/${c.index}/file`} />
                  <a className="text-xs underline" style={{ color: 'var(--cyan)' }}
                     href={`/api/projects/${projectId}/clips/${c.index}/file`} download>
                    ⬇ Download 9:16 captioned clip
                  </a>
                </div>
              ) : (
                <button className="btn-primary px-3 py-1.5 text-white text-xs"
                        disabled={rendering[c.index]} onClick={() => doRender(c.index)}>
                  {rendering[c.index] ? 'Rendering…' : '🎞 Render 9:16 clip'}
                </button>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {platforms.map(([key, label]) => {
                const ek = `${c.index}-${key}`
                return exported[ek] ? (
                  <a key={key} className="text-xs px-2.5 py-1 rounded-full card" style={{ color: 'var(--cyan)' }}
                     href={`/api/projects/${projectId}/exports/${exported[ek]}`} download>⬇ {label}</a>
                ) : (
                  <button key={key} className="text-xs px-2.5 py-1 rounded-full card muted hover:text-white"
                          disabled={exporting[ek]} onClick={() => doExport(c.index, key)}>
                    {exporting[ek] ? '…' : label}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ScoreRing({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = score >= 0.7 ? 'var(--success)' : score >= 0.55 ? 'var(--warning)' : 'var(--danger)'
  return (
    <div className="w-11 h-11 rounded-full flex items-center justify-center shrink-0 font-bold tabular text-sm"
         style={{ border: `3px solid ${color}` }}>
      {pct}
    </div>
  )
}
