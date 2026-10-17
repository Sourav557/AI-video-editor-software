import { useState } from 'react'

function Copy({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [ok, setOk] = useState(false)
  return (
    <button
      className="text-xs px-2 py-1 rounded card muted hover:text-white shrink-0"
      onClick={async () => {
        try { await navigator.clipboard.writeText(text) } catch {
          const ta = document.createElement('textarea')
          ta.value = text; document.body.appendChild(ta); ta.select()
          document.execCommand('copy'); ta.remove()
        }
        setOk(true); setTimeout(() => setOk(false), 1200)
      }}
    >
      {ok ? '✓' : label}
    </button>
  )
}

export default function PublishPrep({ data }: { data: any }) {
  const [tab, setTab] = useState<'youtube' | 'shorts'>('youtube')
  const titles = data.titles?.[tab] ?? []

  return (
    <div className="space-y-6">
      {/* Keywords */}
      <div>
        <h3 className="font-medium mb-1">Keywords <span className="faint text-xs font-normal">· from your transcript{data.suggestions && Object.keys(data.suggestions).length ? ' + YouTube autocomplete' : ''}</span></h3>
        <p className="faint text-xs mb-3">{data.enrichment_note}</p>
        <div className="grid md:grid-cols-2 gap-x-6 gap-y-1">
          {(data.keywords ?? []).map((k: any) => (
            <div key={k.keyword} className="flex items-center gap-2 text-sm py-1">
              <span className="w-40 truncate">{k.keyword}</span>
              <div className="flex-1 h-1.5 rounded-full" style={{ background: 'var(--bg)' }}>
                <div className="h-full rounded-full" style={{ width: `${k.score * 100}%`, background: 'var(--ai-gradient)' }} />
              </div>
              <span className="tabular faint text-xs w-10 text-right">{k.score.toFixed(2)}</span>
            </div>
          ))}
        </div>
        {data.suggestions && Object.keys(data.suggestions).length > 0 && (
          <div className="mt-3 text-sm">
            <span className="faint text-xs">What people search: </span>
            {Object.entries(data.suggestions).map(([kw, sugs]: [string, any]) => (
              <div key={kw} className="mt-1">
                <span className="ai-glow text-xs font-medium">{kw}: </span>
                <span className="muted text-xs">{(sugs as string[]).join(' · ')}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Titles */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <h3 className="font-medium">Titles</h3>
          {(['youtube', 'shorts'] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`text-xs px-3 py-1 rounded-full ${tab === t ? 'btn-primary text-white' : 'card muted'}`}>
              {t === 'youtube' ? 'YouTube' : 'Shorts / TikTok'}
            </button>
          ))}
        </div>
        <div className="space-y-1">
          {titles.map((t: any, i: number) => (
            <div key={i} className="flex items-center gap-3 text-sm px-3 py-2 rounded-lg" style={{ background: 'var(--surface-2)' }}>
              <span className="tabular faint text-xs w-8 shrink-0">{t.score.toFixed(2)}</span>
              <span className="flex-1">{t.title}</span>
              <span className="faint text-xs shrink-0">{t.length ?? t.title.length} ch</span>
              <Copy text={t.title} />
            </div>
          ))}
        </div>
      </div>

      {/* Descriptions */}
      <div>
        <h3 className="font-medium mb-3">Descriptions</h3>
        <div className="grid md:grid-cols-2 gap-4">
          {(['youtube', 'shorts'] as const).map((p) => (
            <div key={p} className="card p-4" style={{ background: 'var(--surface-2)' }}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium faint uppercase tracking-wide">{p === 'youtube' ? 'YouTube' : 'Shorts / TikTok'}</span>
                <Copy text={data.descriptions?.[p] ?? ''} label="Copy description" />
              </div>
              <pre className="text-xs muted whitespace-pre-wrap font-sans">{data.descriptions?.[p]}</pre>
            </div>
          ))}
        </div>
      </div>

      {/* Thumbnail texts */}
      <div>
        <h3 className="font-medium mb-3">Thumbnail overlay text</h3>
        <div className="flex flex-wrap gap-2">
          {(data.thumbnail_texts_long ?? []).map((t: string, i: number) => (
            <span key={i} className="flex items-center gap-2 px-4 py-2 rounded-lg font-bold tracking-wide card" style={{ background: 'var(--surface-2)' }}>
              {t} <Copy text={t} />
            </span>
          ))}
        </div>
      </div>

      {/* Per-clip packaging */}
      {(data.per_clip ?? []).length > 0 && (
        <div>
          <h3 className="font-medium mb-3">Per-clip packaging</h3>
          <div className="grid md:grid-cols-2 gap-4">
            {(data.per_clip ?? []).map((c: any) => (
              <div key={c.clip_index} className="card p-4" style={{ background: 'var(--surface-2)' }}>
                <div className="faint text-xs mb-2">Clip {c.clip_index + 1}</div>
                {(c.titles ?? []).map((t: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-sm py-1">
                    <span className="flex-1">{t.title}</span>
                    <Copy text={t.title} />
                  </div>
                ))}
                <div className="flex flex-wrap gap-2 mt-2">
                  {(c.thumbnail_texts ?? []).map((t: string, i: number) => (
                    <span key={i} className="text-xs px-2 py-1 rounded card font-bold">{t}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
