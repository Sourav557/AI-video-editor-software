import { useEffect, useRef, useState } from 'react'
import { api } from './api'

interface Step { tool: string; args: any; result?: any }
interface Msg { role: 'user' | 'agent'; text: string; ts: string; backend?: string; steps?: Step[] }

function StepBadge({ step, projectId }: { step: Step; projectId: string }) {
  const r = step.result ?? {}
  return (
    <div className="text-xs px-2 py-1 rounded-full card muted inline-flex items-center gap-1 mr-1 mb-1">
      <span className="ai-glow font-medium">⚙ {step.tool}</span>
      {r.file && r.file.startsWith('montage_') && (
        <a className="underline" style={{ color: 'var(--cyan)' }}
           href={`/api/projects/${projectId}/montage/${r.file}`} download>⬇ {r.file}</a>
      )}
      {r.file && r.file.startsWith('tts_') && (
        <a className="underline" style={{ color: 'var(--cyan)' }}
           href={`/api/projects/${projectId}/tts/${r.file}`} download>⬇ audio</a>
      )}
      {r.file && r.file.startsWith('export_') && (
        <a className="underline" style={{ color: 'var(--cyan)' }}
           href={`/api/projects/${projectId}/exports/${r.file}`} download>⬇ video</a>
      )}
      {r.file && r.file.startsWith('clip_') && (
        <a className="underline" style={{ color: 'var(--cyan)' }}
           href={`/api/projects/${projectId}/clips/${r.clip_index ?? 0}/file`} download>⬇ video</a>
      )}
    </div>
  )
}

export default function ChatPanel({ projectId }: { projectId: string }) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const bottomRef = useRef<HTMLDivElement>(null)

  const refresh = async () => {
    try { setMessages((await api.chatHistory(projectId)).messages ?? []) } catch {}
  }
  useEffect(() => { refresh() }, [projectId])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, busy])

  const send = async () => {
    const text = input.trim()
    if (!text || busy) return
    setInput(''); setBusy(true); setProgress(0)
    try {
      const { chat_job } = await api.chat(projectId, text)
      for (;;) {
        const j = await api.job(chat_job)
        setProgress(j.progress)
        if (j.status === 'done' || j.status === 'failed') break
        await new Promise((r) => setTimeout(r, 1500))
      }
      await refresh()
    } catch (e: any) {
      setMessages((m) => [...m, { role: 'agent', text: `Error: ${e.message}`, ts: '' }])
    } finally { setBusy(false) }
  }

  const suggestions = [
    'Analyze this video',
    'Find clips and make a highlight montage',
    'Prepare the publishing package',
    'What is the status?',
  ]

  return (
    <div>
      <div className="space-y-3 max-h-[420px] overflow-y-auto pr-1 mb-4">
        {messages.length === 0 && (
          <p className="muted text-sm">No messages yet — tell your co-editor what to do.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] px-4 py-2.5 rounded-2xl text-sm ${
                m.role === 'user' ? 'btn-primary text-white' : 'card'
              }`} style={m.role === 'agent' ? { background: 'var(--surface-2)' } : undefined}>
              <div className="whitespace-pre-wrap">{m.text}</div>
              {m.steps && m.steps.length > 0 && (
                <div className="mt-2">
                  {m.steps.map((s, j) => <StepBadge key={j} step={s} projectId={projectId} />)}
                </div>
              )}
              {m.backend && m.role === 'agent' && (
                <div className="faint text-[10px] mt-1">via {m.backend === 'rule' ? 'built-in assistant' : m.backend}</div>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex justify-start">
            <div className="card px-4 py-2.5 rounded-2xl text-sm muted" style={{ background: 'var(--surface-2)' }}>
              Working… {Math.round(progress * 100)}%
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        {suggestions.map((s) => (
          <button key={s} className="text-xs px-3 py-1.5 rounded-full card muted hover:text-white"
                  disabled={busy} onClick={() => { setInput(s); }}>
            {s}
          </button>
        ))}
      </div>

      <div className="flex gap-2">
        <input value={input} onChange={(e) => setInput(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && send()}
               placeholder="Tell your co-editor what to do…"
               className="flex-1 rounded-lg p-3 text-sm card" style={{ background: 'var(--surface-2)' }}
               disabled={busy} />
        <button className="btn-primary px-6 text-white rounded-lg" disabled={busy || !input.trim()} onClick={send}>
          Send
        </button>
      </div>
      <p className="faint text-xs mt-2">
        Built-in assistant for now — set <span className="tabular">AGENT_BACKEND=ollama</span> with{' '}
        <span className="tabular">ollama serve</span> running to talk to a real local LLM instead.
      </p>
    </div>
  )
}
