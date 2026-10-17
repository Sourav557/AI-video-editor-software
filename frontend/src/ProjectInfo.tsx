import { useEffect, useState } from 'react'
import { api, fmtTime } from './api'

interface Info {
  filename: string; width: number; height: number; fps: number
  duration: number; pix_fmt: string; size_mb: number
}

export default function ProjectInfo({ projectId, projectName }: { projectId: string; projectName: string }) {
  const [info, setInfo] = useState<Info | null>(null)

  useEffect(() => {
    api.projectInfo(projectId).then(setInfo).catch(() => {})
  }, [projectId])

  const rows: [string, string][] = info ? [
    ['Project Name', projectName],
    ['Resolution', `${info.width} x ${info.height}`],
    ['Frame Rate', `${info.fps}fps`],
    ['Color Space', info.pix_fmt?.includes('709') ? 'SDR - Rec.709' : `SDR (${info.pix_fmt ?? '?'})`],
    ['Duration', fmtTime(info.duration)],
    ['File Size', `${info.size_mb} MB`],
  ] : []

  return (
    <div className="card p-4">
      <div className="ai-glow font-semibold text-sm mb-3">Project Info</div>
      {!info && <div className="muted text-xs">Loading…</div>}
      <div className="space-y-2.5">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3 text-xs">
            <span className="muted shrink-0">{k}:</span>
            <span className="tabular text-right truncate" title={v}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
