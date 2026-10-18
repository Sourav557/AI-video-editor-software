import { useMemo, useState } from 'react'
import { api, fmtTime } from './api'

export type MediaTab = 'media' | 'audio' | 'titles'
export interface TitleT { id: string; text: string; start: number; end: number; size: number; position: 'top' | 'bottom' }

interface Props {
  projectId: string
  fileName: string
  srcDuration: number
  posterUrl: string | null
  usedInTimeline: boolean
  onImport: (f: File) => void
  mediaTab: MediaTab
  setMediaTab: (t: MediaTab) => void
  audioFiles: string[]
  titles: TitleT[]
  /** Slice 17: preview snapshots + screen recordings listed in the Media tab. */
  snapshots: string[]
  recordings: string[]
  onAddTitle: (text: string, size: number, position: 'top' | 'bottom') => void
  onDeleteTitle: (id: string) => void
  currentTime: number
}

const SOON = ['Transitions', 'Effects', 'Stickers', 'Templates']

export default function MediaBin(p: Props) {
  const [query, setQuery] = useState('')
  const [titleText, setTitleText] = useState('')
  const [titleSize, setTitleSize] = useState(48)
  const [titlePos, setTitlePos] = useState<'top' | 'bottom'>('bottom')

  const folders = useMemo(() => [
    { name: 'Project Media', open: true },
    { name: 'Global Media', open: false },
    { name: 'Cloud Media', open: false },
    { name: 'Adjustment Layer', open: false },
    { name: 'Compound Clip', open: false },
  ], [])

  const matchQ = (s: string) => s.toLowerCase().includes(query.toLowerCase())

  return (
    <div className="card flex flex-col min-h-[420px] overflow-hidden">
      {/* media tab bar */}
      <div className="flex items-center gap-1 px-2 pt-2 border-b overflow-x-auto" style={{ borderColor: 'var(--border)' }}>
        {(['media', 'audio', 'titles'] as MediaTab[]).map((t) => (
          <button key={t}
                  onClick={() => p.setMediaTab(t)}
                  className={`px-3 py-2 text-xs font-medium whitespace-nowrap border-b-2 -mb-px ${
                    p.mediaTab === t ? 'ai-glow border-current' : 'muted border-transparent hover:text-white'
                  }`}
                  style={p.mediaTab === t ? { borderColor: 'var(--accent)' } : undefined}>
            {t === 'media' ? 'Media' : t === 'audio' ? 'Audio' : 'Titles'}
          </button>
        ))}
        {SOON.map((s) => (
          <span key={s} title="Coming soon"
                className="px-3 py-2 text-xs faint whitespace-nowrap cursor-not-allowed">{s}</span>
        ))}
      </div>

      {p.mediaTab === 'media' && (
        <>
          <div className="flex gap-2 p-3">
            <label className="text-xs px-3 py-1.5 rounded-lg btn-primary text-white cursor-pointer">
              Import ▾
              <input type="file" accept="video/*" className="hidden"
                     onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onImport(f) }} />
            </label>
            <input value={query} onChange={(e) => setQuery(e.target.value)}
                   placeholder="Search media"
                   className="flex-1 min-w-0 text-xs px-3 py-1.5 rounded-lg card"
                   style={{ background: 'var(--surface-2)' }} />
          </div>
          <div className="flex flex-1 min-h-0">
            {/* folder tree */}
            <div className="w-32 shrink-0 border-r px-2 py-1 space-y-0.5 overflow-y-auto"
                 style={{ borderColor: 'var(--border)' }}>
              {folders.map((f) => (
                <div key={f.name}
                     className={`text-[11px] px-2 py-1.5 rounded truncate ${f.open ? 'card' : 'faint'}`}
                     title={f.name}>
                  ▸ {f.name}
                </div>
              ))}
            </div>
            {/* thumbnails */}
            <div className="flex-1 p-3 overflow-y-auto">
              <div className="grid grid-cols-2 gap-3">
                <label className="cursor-pointer rounded-xl border-2 border-dashed aspect-video flex flex-col items-center justify-center gap-1 muted hover:text-white"
                       style={{ borderColor: 'var(--border)' }}>
                  <span className="text-2xl ai-glow">+</span>
                  <span className="text-[10px]">Import Media</span>
                  <input type="file" accept="video/*" className="hidden"
                         onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onImport(f) }} />
                </label>
                {matchQ(p.fileName) && (
                  <div className="relative rounded-xl overflow-hidden card group">
                    {p.posterUrl ? (
                      <img src={p.posterUrl} className="w-full aspect-video object-cover" alt="" />
                    ) : (
                      <video src={api.sourceUrl(p.projectId)} preload="metadata" muted playsInline
                             className="w-full aspect-video object-cover" style={{ background: '#000' }} />
                    )}
                    <span className="absolute top-1 right-1 text-[9px] px-1.5 py-0.5 rounded tabular"
                          style={{ background: 'rgba(0,0,0,.7)' }}>{fmtTime(p.srcDuration)}</span>
                    {p.usedInTimeline && (
                      <span className="absolute bottom-1 right-1 w-5 h-5 rounded-full flex items-center justify-center text-[10px] text-white"
                            style={{ background: 'var(--success)' }}>✓</span>
                    )}
                    <div className="text-[10px] px-1.5 py-1 truncate" title={p.fileName}>{p.fileName}</div>
                  </div>
                )}
                {/* Slice 17: screen recordings (imported to the bin on stop) */}
                {p.recordings.filter(matchQ).map((f) => (
                  <div key={f} className="relative rounded-xl overflow-hidden card group">
                    <video src={api.recordingUrl(p.projectId, f)} preload="metadata" muted playsInline
                           className="w-full aspect-video object-cover" style={{ background: '#000' }} />
                    <span className="absolute top-1 left-1 text-[9px] px-1.5 py-0.5 rounded"
                          style={{ background: 'rgba(248,113,113,.85)', color: '#fff' }}>⏺ screen</span>
                    <div className="text-[10px] px-1.5 py-1 truncate" title={f}>{f}</div>
                  </div>
                ))}
                {/* Slice 17: preview snapshots */}
                {p.snapshots.filter(matchQ).map((f) => (
                  <div key={f} className="relative rounded-xl overflow-hidden card group">
                    <img src={api.snapshotUrl(p.projectId, f)} className="w-full aspect-video object-cover" alt="" />
                    <span className="absolute top-1 left-1 text-[9px] px-1.5 py-0.5 rounded"
                          style={{ background: 'rgba(0,0,0,.7)' }}>📷</span>
                    <div className="text-[10px] px-1.5 py-1 truncate" title={f}>{f}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      {p.mediaTab === 'audio' && (
        <div className="p-3 space-y-2 overflow-y-auto">
          <p className="faint text-[11px]">Voiceovers you generate land here. Preview below.</p>
          {p.audioFiles.length === 0 && (
            <p className="muted text-xs">No audio yet — make one in the 🎙 Voice tab.</p>
          )}
          {p.audioFiles.map((f) => (
            <div key={f} className="card p-2" style={{ background: 'var(--surface-2)' }}>
              <div className="text-[11px] truncate mb-1" title={f}>🎵 {f}</div>
              <audio controls src={api.audioUrl(p.projectId, f)} className="w-full h-8" />
            </div>
          ))}
        </div>
      )}

      {p.mediaTab === 'titles' && (
        <div className="p-3 space-y-3 overflow-y-auto">
          <div className="space-y-2">
            <input value={titleText} onChange={(e) => setTitleText(e.target.value)}
                   placeholder="Title text…"
                   className="w-full text-xs px-3 py-2 rounded-lg card" style={{ background: 'var(--surface-2)' }} />
            <div className="flex gap-2">
              <select value={titleSize} onChange={(e) => setTitleSize(Number(e.target.value))}
                      className="text-xs px-2 py-1.5 rounded-lg card" style={{ background: 'var(--surface-2)' }}>
                {[32, 48, 64, 96].map((s) => <option key={s} value={s}>{s}px</option>)}
              </select>
              <select value={titlePos} onChange={(e) => setTitlePos(e.target.value as any)}
                      className="text-xs px-2 py-1.5 rounded-lg card" style={{ background: 'var(--surface-2)' }}>
                <option value="bottom">Bottom</option>
                <option value="top">Top</option>
              </select>
              <button disabled={!titleText.trim()}
                      onClick={() => { p.onAddTitle(titleText.trim(), titleSize, titlePos); setTitleText('') }}
                      className="btn-primary text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-40">
                + Add at playhead
              </button>
            </div>
            <p className="faint text-[10px]">Adds a 3s title at {fmtTime(p.currentTime)} on the T2 track.</p>
          </div>
          <div className="space-y-1.5">
            {p.titles.map((t) => (
              <div key={t.id} className="card p-2 flex items-center gap-2" style={{ background: 'var(--surface-2)' }}>
                <span className="font-bold ai-glow">T</span>
                <div className="flex-1 min-w-0">
                  <div className="text-xs truncate">“{t.text}”</div>
                  <div className="faint text-[10px] tabular">{fmtTime(t.start)} → {fmtTime(t.end)}</div>
                </div>
                <button className="faint hover:text-white text-xs" onClick={() => p.onDeleteTitle(t.id)}>✕</button>
              </div>
            ))}
            {p.titles.length === 0 && <p className="muted text-xs">No titles yet.</p>}
          </div>
        </div>
      )}
    </div>
  )
}
