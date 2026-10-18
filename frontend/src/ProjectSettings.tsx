import { useEffect, useState } from 'react'
import { api } from './api'

export interface ProjSettings { aspect: string; width: number; height: number; fps: number }

/* Slice 18: project settings dialog (canvas + fps). Opened from File →
   Project settings… or the ⚙ toolbar button. The render uses these as the
   project canvas; the preview canvas follows the aspect too. */
const PRESETS: { aspect: string; label: string; w: number; h: number }[] = [
  { aspect: '16:9', label: '16:9 Landscape', w: 1920, h: 1080 },
  { aspect: '9:16', label: '9:16 Portrait', w: 1080, h: 1920 },
  { aspect: '1:1', label: '1:1 Square', w: 1080, h: 1080 },
  { aspect: '4:3', label: '4:3 Classic', w: 1440, h: 1080 },
]

export default function ProjectSettings({ projectId, open, onClose, onSaved }: {
  projectId: string
  open: boolean
  onClose: () => void
  onSaved: (s: ProjSettings) => void
}) {
  const [aspect, setAspect] = useState('16:9')
  const [width, setWidth] = useState(1920)
  const [height, setHeight] = useState(1080)
  const [fps, setFps] = useState(30)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!open) return
    setErr('')
    api.settingsGet(projectId).then((s) => {
      setAspect(s.aspect); setWidth(s.width); setHeight(s.height); setFps(s.fps)
    }).catch((e) => setErr(e.message))
  }, [open, projectId])

  if (!open) return null

  const pick = (p: { aspect: string; w: number; h: number }) => {
    setAspect(p.aspect); setWidth(p.w); setHeight(p.h)
  }

  const save = async () => {
    setBusy(true); setErr('')
    try {
      const s = await api.settingsSave(projectId, { aspect, width, height, fps })
      onSaved(s); onClose()
    } catch (e: any) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,.55)' }}
         onClick={onClose}>
      <div className="card p-5 w-[380px] space-y-4" style={{ background: 'var(--surface-2)' }}
           onClick={(e) => e.stopPropagation()}>
        <div className="font-semibold">⚙ Project settings</div>
        <div>
          <div className="faint text-xs mb-1.5">Aspect preset</div>
          <div className="grid grid-cols-2 gap-2">
            {PRESETS.map((p) => (
              <button key={p.aspect}
                      onClick={() => pick(p)}
                      className="px-3 py-2 rounded-lg text-sm border text-left"
                      style={{ borderColor: aspect === p.aspect ? 'var(--accent)' : 'var(--border)',
                               background: aspect === p.aspect ? 'rgba(99,102,241,.15)' : 'transparent' }}>
                <div className="font-semibold">{p.label}</div>
                <div className="faint text-[11px]">{p.w}×{p.h}</div>
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <label className="text-xs faint">Width
            <input type="number" min={16} max={8192} step={2} value={width}
                   onChange={(e) => { setWidth(Number(e.target.value)); setAspect('custom') }}
                   className="mt-1 w-full px-2 py-1.5 rounded-lg card text-sm text-white" />
          </label>
          <label className="text-xs faint">Height
            <input type="number" min={16} max={8192} step={2} value={height}
                   onChange={(e) => { setHeight(Number(e.target.value)); setAspect('custom') }}
                   className="mt-1 w-full px-2 py-1.5 rounded-lg card text-sm text-white" />
          </label>
          <label className="text-xs faint">FPS
            <input type="number" min={1} max={120} value={fps}
                   onChange={(e) => setFps(Number(e.target.value))}
                   className="mt-1 w-full px-2 py-1.5 rounded-lg card text-sm text-white" />
          </label>
        </div>
        <p className="muted text-[11px]">The render uses this canvas (content is aspect-fit with padding) and
          frame rate. Width/height snap to even numbers.</p>
        {err && <div className="text-xs" style={{ color: 'var(--danger)' }}>{err}</div>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm card">Cancel</button>
          <button onClick={save} disabled={busy}
                  className="btn-primary px-4 py-2 rounded-lg text-sm text-white disabled:opacity-40">
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
