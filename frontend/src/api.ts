/* Thin client for the LocalCut REST API.
   Browser dev: same origin (relative URLs).
   Tauri desktop build: frontend is built with VITE_API_BASE=http://127.0.0.1:8000
   so calls reach the bundled Python backend. */

const API_BASE: string =
  ((import.meta as any).env?.VITE_API_BASE as string | undefined) ?? '';

/** Timecode HH:MM:SS:FF (Filmora-style, 30fps). */
export function fmtTC(sec: number, fps = 30): string {
  const s = Math.max(0, sec)
  const f = Math.floor((s % 1) * fps)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = Math.floor(s % 60)
  const p = (n: number, l = 2) => String(n).padStart(l, '0')
  return `${p(h)}:${p(m)}:${p(ss)}:${p(f)}`
}

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
  const r = await fetch(API_BASE + path, init)
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
    req<{ transcribe_job: string; silence_job: string; waveform_job: string; filmstrip_job: string }>(
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
  ttsVoices: () =>
    req<{ engine: string; speakers: { name: string; description: string; native: string }[]; languages: string[] }>(`/api/tts/voices`),
  ttsGenerate: (pid: string, body: { text: string; speaker: string; language: string; instruct: string }) =>
    req<{ tts_job: string }>(`/api/projects/${pid}/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  ttsClone: (pid: string, text: string, refText: string, language: string, refFile: File, consent: boolean) => {
    const fd = new FormData()
    fd.append('text', text)
    fd.append('ref_text', refText)
    fd.append('language', language)
    fd.append('consent', String(consent))
    fd.append('ref_audio', refFile)
    return req<{ tts_job: string }>(`/api/projects/${pid}/tts/clone`, { method: 'POST', body: fd })
  },
  seoGenerate: (pid: string) =>
    req<{ seo_job: string }>(`/api/projects/${pid}/seo`, { method: 'POST' }),
  seoGet: (pid: string) => req<any>(`/api/projects/${pid}/seo`),
  chat: (pid: string, message: string) =>
    req<{ chat_job: string }>(`/api/projects/${pid}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    }),
  chatHistory: (pid: string) => req<{ messages: any[] }>(`/api/projects/${pid}/chat`),
  waveform: (pid: string) => req<{ peaks: number[]; duration: number }>(`/api/projects/${pid}/waveform`),
  autopilot: (pid: string, opts: { remove_silence: boolean; silence_pad: number; remove_fillers: boolean; captions: boolean }) =>
    req<{ autopilot_job: string }>(`/api/projects/${pid}/autopilot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    }),
  autopilotGet: (pid: string) => req<any>(`/api/projects/${pid}/autopilot`),
  sourceUrl: (pid: string) => `${API_BASE}/api/projects/${pid}/source/file`,
  autopilotUrl: (pid: string) => `${API_BASE}/api/projects/${pid}/autopilot/file`,
  editFileUrl: (pid: string) => `${API_BASE}/api/projects/${pid}/edit/file`,
  editRender: (pid: string, blocks: any[], captions: boolean, titles: any[]) =>
    req<{ render_job: string }>(`/api/projects/${pid}/edit/render`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocks, captions, titles }),
    }),
  editGet: (pid: string) => req<any>(`/api/projects/${pid}/edit`),
  filmstrip: (pid: string) => req<{ interval: number; thumbs: string[]; width: number; height: number }>(`/api/projects/${pid}/filmstrip`),
  filmstripUrl: (pid: string, name: string) => `${API_BASE}/api/projects/${pid}/filmstrip/${name}`,
  projectInfo: (pid: string) => req<any>(`/api/projects/${pid}/info`),
  audioList: (pid: string) => req<{ files: string[] }>(`/api/projects/${pid}/audio`),
  audioUrl: (pid: string, name: string) => `${API_BASE}/api/projects/${pid}/audio/${name}`,
  /** Slice 17: upload a mic-recorded voiceover (MediaRecorder output). */
  audioUpload: (pid: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<{ file: string; duration?: number }>(`/api/projects/${pid}/audio/upload`, {
      method: 'POST',
      body: fd,
    })
  },
  /** Slice 17: screen capture. */
  recordStart: (pid: string, opts?: { region?: string; fps?: number }) =>
    req<{ recording: string }>(`/api/projects/${pid}/record/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts ?? {}),
    }),
  recordStop: (pid: string) =>
    req<{ file: string; duration: number; ok: boolean }>(`/api/projects/${pid}/record/stop`, { method: 'POST' }),
  recordStatus: (pid: string) =>
    req<{ recording: boolean; file?: string; elapsed?: number }>(`/api/projects/${pid}/record/status`),
  recordings: (pid: string) => req<{ files: string[] }>(`/api/projects/${pid}/recordings`),
  recordingUrl: (pid: string, name: string) => `${API_BASE}/api/projects/${pid}/recordings/${name}`,
  /** Slice 17: preview-canvas snapshot. */
  snapshot: (pid: string, image: string) =>
    req<{ file: string }>(`/api/projects/${pid}/snapshot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image }),
    }),
  snapshots: (pid: string) => req<{ files: string[] }>(`/api/projects/${pid}/snapshots`),
  snapshotUrl: (pid: string, name: string) => `${API_BASE}/api/projects/${pid}/snapshots/${name}`,
  timelineGet: (pid: string) => req<{ blocks: any[]; titles: any[]; markers?: any[] }>(`/api/projects/${pid}/timeline`),
  timelineSave: (pid: string, blocks: any[], titles: any[], markers?: any[]) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/timeline`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocks, titles, markers: markers ?? [] }),
    }),
  transcript: (pid: string) =>
    req<{ transcript: any; silence: any }>(`/api/projects/${pid}/transcript`),
  luts: () => req<{ luts: string[] }>(`/api/luts`),
}

export function fmtTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}
