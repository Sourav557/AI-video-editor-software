import { useEffect, useMemo, useRef, useState } from 'react'
import { api, fmtTime, JobStatus, Segment, Silence } from './api'
import Timeline, { TlCut, TlSegment } from './Timeline'
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
  onError: (m: string) => void
}

interface Edl {
  segments: { start: number; end: number; kind: string }[]
  removed: { start: number; end: number; kind: 'silence' | 'filler' }[]
  source_duration: number
  output_duration: number
  cuts: number
  options: Record<string, any>
}

type View = 'source' | 'edit'
type Tab = 'clips' | 'transcript' | 'voice' | 'publish' | 'chat'

/** Remap source-timebase waveform peaks onto the edited (concatenated) timeline. */
function remapPeaks(peaks: number[], srcDur: number, kept: { start: number; end: number }[]): number[] {
  const n = peaks.length
  const out: number[] = []
  for (const k of kept) {
    const i0 = Math.max(0, Math.floor((k.start / srcDur) * n))
    const i1 = Math.min(n, Math.ceil((k.end / srcDur) * n))
    for (let i = i0; i < i1; i++) out.push(peaks[i])
  }
  if (!out.length) return peaks
  // resample back to n buckets
  const res: number[] = []
  for (let i = 0; i < n; i++) res.push(out[Math.floor((i / n) * out.length)])
  return res
}

export default function Studio({ projectId, fileName, segments, silences, language, onError }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [peaks, setPeaks] = useState<number[]>([])
  const [edl, setEdl] = useState<Edl | null>(null)
  const [view, setView] = useState<View>('source')
  const [tab, setTab] = useState<Tab>('clips')
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [pxPerSec, setPxPerSec] = useState(40)
  const [showAp, setShowAp] = useState(false)
  const [apRunning, setApRunning] = useState(false)
  const [apProgress, setApProgress] = useState(0)
  const [optSilence, setOptSilence] = useState(true)
  const [optFillers, setOptFillers] = useState(false)
  const [optCaptions, setOptCaptions] = useState(true)
  const [seoData, setSeoData] = useState<any>(null)
  const [generatingSeo, setGeneratingSeo] = useState(false)

  useEffect(() => {
    api.waveform(projectId).then((w) => setPeaks(w.peaks ?? [])).catch(() => {})
    api.autopilotGet(projectId).then((e) => { setEdl(e); }).catch(() => {})
  }, [projectId])

  const srcUrl = useMemo(() => api.sourceUrl(projectId), [projectId])
  const editUrl = useMemo(() => api.autopilotUrl(projectId), [projectId])

  // switch preview source when view changes
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    v.src = view === 'edit' && edl ? editUrl : srcUrl
    v.load()
    setCurrentTime(0)
  }, [view, edl, srcUrl, editUrl])

  const onTimeUpdate = () => setCurrentTime(videoRef.current?.currentTime ?? 0)
  const onLoadedMeta = () => {
    const v = videoRef.current
    if (v && v.duration) {
      setDuration(v.duration)
      setPxPerSec(Math.max(8, Math.min(120, 900 / v.duration)))
    }
  }
  const seek = (t: number) => {
    const v = videoRef.current
    if (v) { v.currentTime = t; setCurrentTime(t) }
  }

  // timeline model for the current view
  const tl = useMemo(() => {
    if (view === 'edit' && edl) {
      let cursor = 0
      const segs: TlSegment[] = edl.segments.map((s) => {
        const len = s.end - s.start
        const seg = { start: cursor, end: cursor + len, label: `keep ${fmtTime(s.start)} → ${fmtTime(s.end)}` }
        cursor += len
        return seg
      })
      return { segments: segs, cuts: [] as TlCut[], peaks: remapPeaks(peaks, edl.source_duration, edl.segments) }
    }
    const segs: TlSegment[] = duration > 0 ? [{ start: 0, end: duration, label: 'source' }] : []
    const cuts: TlCut[] = silences.map((s) => ({ start: s.start, end: s.end, kind: 'silence' as const }))
    return { segments: segs, cuts, peaks }
  }, [view, edl, silences, duration, peaks])

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
            setEdl(e); setView('edit')
          }
        } catch (e: any) { window.clearInterval(iv); setApRunning(false); onError(e.message) }
      }, 1500)
    } catch (e: any) { setApRunning(false); onError(e.message) }
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

  const tabs: { id: Tab; label: string }[] = [
    { id: 'clips', label: '🎯 Clips' },
    { id: 'transcript', label: '📝 Transcript' },
    { id: 'voice', label: '🎙 Voice' },
    { id: 'publish', label: '📦 Publish' },
    { id: 'chat', label: '💬 Co-editor' },
  ]

  return (
    <div className="space-y-4">
      {/* toolbar */}
      <div className="card px-4 py-3 flex items-center gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="font-semibold truncate">{fileName}</div>
          <div className="faint text-xs">
            {language && <span className="mr-2">{language}</span>}
            {segments.length} segments · {silences.length} silences
            {edl && <span className="ml-2" style={{ color: 'var(--success)' }}>· autopilot: {edl.cuts} cuts, −{Math.round(edl.source_duration - edl.output_duration)}s</span>}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {edl && (
            <div className="flex rounded-lg overflow-hidden border text-sm" style={{ borderColor: 'var(--border)' }}>
              <button className={`px-3 py-1.5 ${view === 'source' ? 'btn-primary text-white' : 'muted'}`}
                      onClick={() => setView('source')}>Source</button>
              <button className={`px-3 py-1.5 ${view === 'edit' ? 'btn-primary text-white' : 'muted'}`}
                      onClick={() => setView('edit')}>✂ Edited</button>
            </div>
          )}
          <div className="relative">
            <button className="btn-primary px-5 py-2 text-white text-sm" disabled={apRunning}
                    onClick={() => setShowAp((s) => !s)}>
              {apRunning ? `🤖 Autopilot… ${Math.round(apProgress * 100)}%` : '🤖 Autopilot'}
            </button>
            {showAp && !apRunning && (
              <div className="absolute right-0 mt-2 w-72 card p-4 z-20 space-y-2.5 text-sm" style={{ background: 'var(--surface-2)' }}>
                <div className="font-semibold">Autopilot — long-video self-edit</div>
                <p className="muted text-xs">Cleans the whole video: cuts dead air, burns captions, normalizes loudness. No overcutting.</p>
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
        </div>
      </div>
      {apRunning && (
        <div className="card px-4 py-3">
          <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--surface-2)' }}>
            <div className="h-full rounded-full transition-all" style={{ width: `${apProgress * 100}%`, background: 'var(--ai-gradient)' }} />
          </div>
          <div className="muted text-xs mt-1.5">Autopilot is editing your video… {Math.round(apProgress * 100)}%</div>
        </div>
      )}

      {/* preview + side panel */}
      <div className="grid gap-4" style={{ gridTemplateColumns: 'minmax(0,1.6fr) minmax(0,1fr)' }}>
        <div className="card p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-sm">Preview</span>
            <span className="faint text-xs">{view === 'edit' ? '✂ autopilot edit' : 'source'}</span>
          </div>
          <video ref={videoRef} controls className="w-full rounded-lg max-h-[52vh]" style={{ background: '#000' }}
                 onTimeUpdate={onTimeUpdate} onLoadedMetadata={onLoadedMeta} />
          {view === 'edit' && edl && (
            <a className="text-sm underline mt-2 inline-block" style={{ color: 'var(--cyan)' }}
               href={editUrl} download>⬇ Download edited video</a>
          )}
        </div>

        <div className="card p-4 min-h-[300px]">
          <div className="flex gap-1 mb-3 flex-wrap">
            {tabs.map((t) => (
              <button key={t.id} onClick={() => setTab(t.id)}
                      className={`px-3 py-1.5 rounded-lg text-xs ${tab === t.id ? 'btn-primary text-white' : 'muted card'}`}>
                {t.label}
              </button>
            ))}
          </div>
          <div className="max-h-[52vh] overflow-y-auto pr-1">
            {tab === 'clips' && <ClipsPanel projectId={projectId} onError={onError} />}
            {tab === 'transcript' && (
              <div className="space-y-2">
                {segments.map((s, i) => (
                  <div key={i} className="flex gap-3 text-sm px-3 py-2 rounded-lg" style={{ background: 'var(--surface-2)' }}>
                    <button className="tabular faint shrink-0 w-24 text-left hover:text-white"
                            onClick={() => seek(s.start)}>{fmtTime(s.start)}</button>
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

      {/* timeline */}
      <Timeline duration={duration} peaks={tl.peaks} segments={tl.segments} cuts={tl.cuts}
                currentTime={currentTime} onSeek={seek}
                pxPerSec={pxPerSec} setPxPerSec={setPxPerSec} />
    </div>
  )
}
