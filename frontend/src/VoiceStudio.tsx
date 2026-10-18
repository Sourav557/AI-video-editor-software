import { useEffect, useRef, useState } from 'react'
import { api, fmtTime } from './api'

interface Speaker { name: string; description: string; native: string }

export default function VoiceStudio({ projectId, onRecorded }: { projectId: string; onRecorded?: () => void }) {
  const [tab, setTab] = useState<'preset' | 'clone' | 'record'>('preset')
  const [speakers, setSpeakers] = useState<Speaker[]>([])
  const [languages, setLanguages] = useState<string[]>([])
  const [text, setText] = useState('')
  const [speaker, setSpeaker] = useState('Ryan')
  const [language, setLanguage] = useState('English')
  const [instruct, setInstruct] = useState('')
  const [refFile, setRefFile] = useState<File | null>(null)
  const [refText, setRefText] = useState('')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [audioUrl, setAudioUrl] = useState('')
  const [error, setError] = useState('')
  /** Slice 17: mic recording state */
  const [recording, setRecording] = useState(false)
  const [recElapsed, setRecElapsed] = useState(0)
  const [uploading, setUploading] = useState(false)
  const recRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    api.ttsVoices()
      .then((v) => { setSpeakers(v.speakers); setLanguages(v.languages) })
      .catch(() => {})
  }, [])

  const waitFor = async (jobId: string): Promise<string> => {
    for (;;) {
      const j = await api.job(jobId)
      setProgress(j.progress)
      if (j.status === 'done') return (j.result as any).file as string
      if (j.status === 'failed') throw new Error(j.error || 'TTS failed')
      await new Promise((r) => setTimeout(r, 2000))
    }
  }

  const generate = async () => {
    setError(''); setBusy(true); setProgress(0); setAudioUrl('')
    try {
      let jobId: string
      if (tab === 'preset') {
        ;({ tts_job: jobId } = await api.ttsGenerate(projectId, { text, speaker, language, instruct }))
      } else {
        if (!refFile) throw new Error('Attach a 3s+ reference clip of the voice.')
        if (!refText.trim()) throw new Error('Paste the transcript of the reference clip.')
        if (!consent) throw new Error('Tick the consent box — cloning needs explicit consent.')
        ;({ tts_job: jobId } = await api.ttsClone(projectId, text, refText, language, refFile, consent))
      }
      const file = await waitFor(jobId)
      setAudioUrl(`/api/projects/${projectId}/tts/${file}`)
    } catch (e: any) { setError(e.message) }
    finally { setBusy(false) }
  }

  const canGo = text.trim().length > 0 && !busy

  /** Slice 17: record from the microphone, upload as a voiceover. */
  const pickMime = (): { mime: string | undefined; ext: string } => {
    for (const m of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']) {
      if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported?.(m))
        return { mime: m, ext: m.includes('mp4') ? 'm4a' : 'webm' }
    }
    return { mime: undefined, ext: 'webm' }
  }

  const startRecord = async () => {
    setError('')
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser cannot access the microphone.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const { mime, ext } = pickMime()
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
      chunksRef.current = []
      rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data) }
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || 'audio/webm' })
        setUploading(true)
        try {
          const file = new File([blob], `voiceover.${ext}`, { type: blob.type })
          const r = await api.audioUpload(projectId, file)
          setAudioUrl(`/api/projects/${projectId}/audio/${r.file}`)
          onRecorded?.()
        } catch (e: any) { setError(e.message) }
        finally { setUploading(false) }
      }
      rec.start()
      recRef.current = rec
      setRecording(true)
      setRecElapsed(0)
      timerRef.current = window.setInterval(() => setRecElapsed((s) => s + 1), 1000)
    } catch (e: any) {
      setError(e?.name === 'NotAllowedError'
        ? 'Microphone permission denied — allow mic access and try again.'
        : `Could not start recording: ${e?.message ?? e}`)
    }
  }

  const stopRecord = () => {
    if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = null }
    setRecording(false)
    recRef.current?.stop()
    recRef.current = null
  }

  useEffect(() => () => {
    if (timerRef.current) window.clearInterval(timerRef.current)
    if (recRef.current?.state !== 'inactive') recRef.current?.stop()
  }, [])

  return (
    <div>
      <div className="flex gap-2 mb-4">
        {(['preset', 'clone', 'record'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`text-sm px-4 py-2 rounded-full ${tab === t ? 'btn-primary text-white' : 'card muted'}`}>
            {t === 'preset' ? '🎙 Preset voice' : t === 'clone' ? '🧬 Clone a voice' : '● Record mic'}
          </button>
        ))}
      </div>

      {tab === 'record' && (
        <div className="space-y-3">
          <p className="faint text-xs">Record a voiceover with your microphone. It saves into the project's Audio tab
            (media bin), where you can preview and reuse it. Dropping it onto the timeline at the playhead is not
            built yet — timeline audio-clip placement is coming in a later slice.</p>
          <div className="flex items-center gap-4">
            {!recording ? (
              <button className="btn-primary px-6 py-3 text-white" disabled={uploading} onClick={startRecord}>
                ● Record voiceover
              </button>
            ) : (
              <button className="px-6 py-3 rounded-lg text-white font-semibold"
                      style={{ background: 'var(--danger)' }} onClick={stopRecord}>
                ⏹ Stop &amp; save
              </button>
            )}
            {recording && (
              <span className="flex items-center gap-2 text-sm">
                <span className="w-2.5 h-2.5 rounded-full animate-pulse" style={{ background: 'var(--danger)' }} />
                <span className="tabular">{fmtTime(recElapsed)}</span>
              </span>
            )}
            {uploading && <span className="faint text-xs">Uploading…</span>}
          </div>
          {error && <div className="mt-3 text-sm px-4 py-3 rounded-lg" style={{ background: 'rgba(248,113,113,.12)', color: 'var(--danger)' }}>{error}</div>}
          {audioUrl && (
            <div className="mt-2 space-y-2">
              <audio controls src={audioUrl} className="w-full" />
              <a className="text-sm underline" style={{ color: 'var(--cyan)' }} href={audioUrl} download>⬇ Download recording</a>
            </div>
          )}
        </div>
      )}

      {tab !== 'record' && (
      <>

      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3}
        placeholder="Type what the voice should say…"
        className="w-full rounded-lg p-3 text-sm card" style={{ background: 'var(--surface-2)' }} />

      <div className="grid md:grid-cols-3 gap-3 mt-3">
        <label className="text-sm">
          <span className="faint text-xs">Speaker</span>
          <select value={speaker} onChange={(e) => setSpeaker(e.target.value)}
            className="w-full mt-1 rounded-lg p-2 text-sm card" style={{ background: 'var(--surface-2)' }}>
            {speakers.map((s) => <option key={s.name} value={s.name}>{s.name} — {s.description}</option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="faint text-xs">Language</span>
          <select value={language} onChange={(e) => setLanguage(e.target.value)}
            className="w-full mt-1 rounded-lg p-2 text-sm card" style={{ background: 'var(--surface-2)' }}>
            {languages.map((l) => <option key={l}>{l}</option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="faint text-xs">Emotion / direction <span className="faint">(optional)</span></span>
          <input value={instruct} onChange={(e) => setInstruct(e.target.value)}
            placeholder='e.g. "speak excitedly"'
            className="w-full mt-1 rounded-lg p-2 text-sm card" style={{ background: 'var(--surface-2)' }} />
        </label>
      </div>

      {tab === 'clone' && (
        <div className="card p-4 mt-3 space-y-3" style={{ background: 'var(--surface-2)' }}>
          <div className="text-sm font-medium">Reference clip <span className="faint font-normal">· 3s+ of clear speech, your own voice only</span></div>
          <input type="file" accept="audio/*" className="text-sm"
            onChange={(e) => setRefFile(e.target.files?.[0] ?? null)} />
          <textarea value={refText} onChange={(e) => setRefText(e.target.value)} rows={2}
            placeholder="Exact transcript of the reference clip…"
            className="w-full rounded-lg p-3 text-sm card" style={{ background: 'var(--bg)' }} />
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1" />
            <span>I confirm this is <b>my own voice</b> (or one I have rights to), and I consent to cloning it. No public figures.</span>
          </label>
        </div>
      )}

      <div className="mt-4 flex items-center gap-4">
        <button className="btn-primary px-6 py-3 text-white" disabled={!canGo} onClick={generate}>
          {busy ? 'Generating…' : '🔊 Generate voiceover'}
        </button>
        {busy && (
          <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--surface-2)' }}>
            <div className="h-full rounded-full transition-all" style={{ width: `${progress * 100}%`, background: 'var(--ai-gradient)' }} />
          </div>
        )}
      </div>
      {busy && <p className="faint text-xs mt-2">First run downloads the Qwen3-TTS 0.6B model (~2.5 GB), then runs fully offline.</p>}
      {error && <div className="mt-3 text-sm px-4 py-3 rounded-lg" style={{ background: 'rgba(248,113,113,.12)', color: 'var(--danger)' }}>{error}</div>}
      {audioUrl && (
        <div className="mt-4 space-y-2">
          <audio controls src={audioUrl} className="w-full" />
          <a className="text-sm underline" style={{ color: 'var(--cyan)' }} href={audioUrl} download>⬇ Download voiceover (.wav)</a>
        </div>
      )}
      </>
      )}
    </div>
  )
}
