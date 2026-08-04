import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cardGlowStyle, glassCard } from './dashboardStyles'

/**
 * A glass card whose body is hidden behind its header until clicked.
 * The meeting page's analysis tail and Trend's demoted sections both use this,
 * so "collapsed by default" looks and behaves identically everywhere.
 */
export default function CollapsibleSection({ title, hint = '', count = null, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className={`${glassCard} overflow-hidden`} style={cardGlowStyle}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-5 py-3.5 text-left transition hover:bg-[var(--db-fill)]"
      >
        <h2 className="text-[15px] font-bold tracking-[-0.01em] text-[color:var(--db-text)]">{title}</h2>
        {count !== null && count !== undefined && (
          <span className="text-[11.5px] font-semibold text-[color:var(--db-text-faint)]">{count}</span>
        )}
        {hint && !open && (
          <span className="min-w-0 flex-1 truncate text-[12px] text-[color:var(--db-text-faint)]">{hint}</span>
        )}
        <ChevronDown
          className={`ml-auto h-4 w-4 shrink-0 text-[color:var(--db-text-faint)] transition-transform ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>
      {open && <div className="px-5 pb-5">{children}</div>}
    </section>
  )
}
