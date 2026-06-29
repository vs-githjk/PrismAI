import { useMemo, useState } from 'react'
import { Popover } from 'radix-ui'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'

const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December']

const pad = (n) => String(n).padStart(2, '0')
const toISO = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}` // local, no TZ shift

function parseISO(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '')
  if (!m) return null
  return { y: +m[1], m: +m[2] - 1, d: +m[3] }
}

function formatLabel(value) {
  const p = parseISO(value)
  if (!p) return 'Pick a date'
  return new Date(p.y, p.m, p.d).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}

/**
 * Compact date picker that anchors directly under its trigger via Radix Popover
 * (collision-aware) — replaces the native <input type="date"> whose popup the
 * browser positions on its own (often detached, opening upward over content).
 */
export default function DatePopover({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const selected = parseISO(value)
  const today = new Date()
  const [view, setView] = useState(() => selected
    ? { y: selected.y, m: selected.m }
    : { y: today.getFullYear(), m: today.getMonth() })

  const cells = useMemo(() => {
    const firstDay = new Date(view.y, view.m, 1).getDay()
    const daysInMonth = new Date(view.y, view.m + 1, 0).getDate()
    const out = []
    for (let i = 0; i < firstDay; i++) out.push(null)
    for (let d = 1; d <= daysInMonth; d++) out.push(d)
    return out
  }, [view])

  const shiftMonth = (delta) => setView((v) => {
    const m0 = v.m + delta
    return { y: v.y + Math.floor(m0 / 12), m: ((m0 % 12) + 12) % 12 }
  })

  const pick = (d) => {
    onChange?.(toISO(view.y, view.m, d))
    setOpen(false)
  }

  const isSelected = (d) => selected && selected.y === view.y && selected.m === view.m && selected.d === d
  const isToday = (d) => view.y === today.getFullYear() && view.m === today.getMonth() && d === today.getDate()

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-left text-sm text-white/90 outline-none transition focus:border-cyan-400/40 hover:border-white/[0.16]"
        >
          <CalendarDays className="h-4 w-4 shrink-0 text-white/45" />
          <span className="flex-1 truncate">{formatLabel(value)}</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="bottom"
          align="start"
          sideOffset={6}
          className="z-50 w-[268px] rounded-xl border border-[#2f2f2f] bg-[#0b0b0b] p-3 shadow-2xl shadow-black/60"
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[13px] font-semibold text-white">{MONTHS[view.m]} {view.y}</span>
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => shiftMonth(-1)} aria-label="Previous month"
                className="grid h-6 w-6 place-items-center rounded-md text-white/60 hover:bg-white/[0.08] hover:text-white">
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button type="button" onClick={() => shiftMonth(1)} aria-label="Next month"
                className="grid h-6 w-6 place-items-center rounded-md text-white/60 hover:bg-white/[0.08] hover:text-white">
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-7 gap-0.5">
            {WEEKDAYS.map((w, i) => (
              <div key={i} className="grid h-7 place-items-center text-[10px] font-semibold text-white/35">{w}</div>
            ))}
            {cells.map((d, i) => d === null ? (
              <div key={i} className="h-8" />
            ) : (
              <button
                key={i}
                type="button"
                onClick={() => pick(d)}
                className={`grid h-8 place-items-center rounded-md text-[12.5px] transition ${
                  isSelected(d)
                    ? 'bg-cyan-400/90 font-semibold text-black'
                    : isToday(d)
                      ? 'text-cyan-300 ring-1 ring-inset ring-cyan-400/40 hover:bg-white/[0.08]'
                      : 'text-white/80 hover:bg-white/[0.08]'
                }`}
              >
                {d}
              </button>
            ))}
          </div>

          <div className="mt-2 flex items-center justify-end border-t border-white/[0.06] pt-2">
            <button
              type="button"
              onClick={() => { const t = new Date(); onChange?.(toISO(t.getFullYear(), t.getMonth(), t.getDate())); setOpen(false) }}
              className="text-[11px] font-medium text-cyan-300 hover:text-cyan-200"
            >
              Today
            </button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
