import { useEffect, useMemo, useRef, useState } from 'react'
import { Popover } from 'radix-ui'
import { Clock } from 'lucide-react'

const pad = (n) => String(n).padStart(2, '0')

function to12h(value) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(value || '')
  if (!m) return 'Pick a time'
  const h = +m[1]
  const suffix = h < 12 ? 'AM' : 'PM'
  const h12 = h % 12 || 12
  return `${h12}:${m[2]} ${suffix}`
}

/**
 * Time picker that matches DatePopover — a themed Radix Popover with a
 * scrollable 15-minute grid, instead of the native <input type="time"> whose
 * look and popup are inconsistent with the rest of the editor.
 */
export default function TimePopover({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const listRef = useRef(null)
  const selectedRef = useRef(null)

  // 15-min grid, plus the current value injected if it's off-grid (e.g. 02:40).
  const options = useMemo(() => {
    const set = new Set()
    for (let h = 0; h < 24; h++) for (const mm of [0, 15, 30, 45]) set.add(`${pad(h)}:${pad(mm)}`)
    if (/^\d{1,2}:\d{2}$/.test(value || '')) {
      const [h, m] = value.split(':')
      set.add(`${pad(+h)}:${pad(+m)}`)
    }
    return Array.from(set).sort()
  }, [value])

  // Center the selected row when the popover opens.
  useEffect(() => {
    if (open && selectedRef.current) {
      selectedRef.current.scrollIntoView({ block: 'center' })
    }
  }, [open])

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="flex w-32 items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-left text-sm text-white/90 outline-none transition focus:border-cyan-400/40 hover:border-white/[0.16]"
        >
          <Clock className="h-4 w-4 shrink-0 text-white/45" />
          <span className="flex-1 truncate">{to12h(value)}</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="bottom"
          align="start"
          sideOffset={6}
          className="z-50 w-36 rounded-xl border border-[#2f2f2f] bg-[#0b0b0b] p-1.5 shadow-2xl shadow-black/60"
        >
          <div ref={listRef} className="max-h-60 overflow-y-auto">
            {options.map((opt) => {
              const isSelected = opt === value
              return (
                <button
                  key={opt}
                  ref={isSelected ? selectedRef : null}
                  type="button"
                  onClick={() => { onChange?.(opt); setOpen(false) }}
                  className={`block w-full rounded-md px-3 py-1.5 text-left text-[12.5px] transition ${
                    isSelected
                      ? 'bg-cyan-400/90 font-semibold text-black'
                      : 'text-white/80 hover:bg-white/[0.08]'
                  }`}
                >
                  {to12h(opt)}
                </button>
              )
            })}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
