/* Thin client for the LocalCut REST API (served by FastAPI on :8000). */

export interface JobStatus {
  id: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  error: string | null
  result: any
}

export interface Word { start: number; end: number; word: string }
export interface Segment { start: number; end: number; text: string }
export interface Silence { start: number; end: number; duration: number }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
  health: () => req<{ status: string }>('/api/health'),
  upload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<{ project_id: string; filename: string }>('/api/projects', {
      method: 'POST',
      body: fd,
    })
  },
  analyze: (pid: string) =>
    req<{ transcribe_job: string; silence_job: string }>(
      `/api/projects/${pid}/analyze`,
      { method: 'POST' },
    ),
  job: (id: string) => req<JobStatus>(`/api/jobs/${id}`),
  findClips: (pid: string) =>
    req<{ score_job: string }>(`/api/projects/${pid}/clips`, { method: 'POST' }),
  clips: (pid: string) =>
    req<{ clips: any[]; message: string }>(`/api/projects/${pid}/clips`),
  renderClip: (pid: string, idx: number) =>
    req<{ render_job: string }>(`/api/projects/${pid}/clips/${idx}/render`, { method: 'POST' }),
  platforms: () =>
    req<{ version: number; platforms: Record<string, { label: string }> }>(`/api/platforms`),
  exportClip: (pid: string, idx: number, platform: string) =>
    req<{ export_job: string }>(`/api/projects/${pid}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clip_index: idx, platform }),
    }),
  transcript: (pid: string) =>
    req<{ transcript: any; silence: any }>(`/api/projects/${pid}/transcript`),
}

export function fmtTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}
