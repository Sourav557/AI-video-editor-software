import { useEffect, useRef, useState } from 'react'

interface Item { label: string; hint?: string; action: () => void; disabled?: boolean }

export default function MenuBar({ menus }: { menus: { label: string; items: Item[] }[] }) {
  const [open, setOpen] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(null)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [])

  return (
    <div ref={ref} className="flex items-center gap-1 px-3 border-b text-sm"
         style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}>
      <div className="w-6 h-6 rounded-md flex items-center justify-center font-bold text-xs mr-1"
           style={{ background: 'var(--ai-gradient)' }}>L</div>
      <span className="font-semibold text-xs mr-3 hidden sm:inline">LocalCut</span>
      {menus.map((m) => (
        <div key={m.label} className="relative">
          <button
            className={`px-3 py-2 text-[13px] rounded ${open === m.label ? 'card' : 'muted hover:text-white'}`}
            onClick={() => setOpen(open === m.label ? null : m.label)}
            onMouseEnter={() => { if (open) setOpen(m.label) }}>
            {m.label}
          </button>
          {open === m.label && (
            <div className="absolute left-0 top-full mt-1 w-60 card p-1.5 z-50"
                 style={{ background: 'var(--surface-2)', boxShadow: '0 12px 32px rgba(0,0,0,.5)' }}>
              {m.items.map((it, i) => (
                <button key={i} disabled={it.disabled}
                        onClick={() => { setOpen(null); it.action() }}
                        className="w-full flex items-center justify-between px-3 py-2 rounded text-[13px] text-left
                                   hover:bg-white/10 disabled:opacity-30 disabled:cursor-default">
                  <span>{it.label}</span>
                  {it.hint && <span className="faint text-[11px]">{it.hint}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
