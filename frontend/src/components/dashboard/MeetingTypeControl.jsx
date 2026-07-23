import { Loader2 } from 'lucide-react'

// A styled native <select> for choosing the meeting type. Native on purpose: it
// avoids the position:fixed-inside-transformed-ancestor bug that bites portalled
// menus on the dashboard, and works inside the New-Meeting Radix popover too.
// Reused as the input-surface picker (options include Auto) and the result
// override chip (concrete types only).
export default function MeetingTypeControl({
  value,
  onChange,
  options,
  disabled = false,
  loading = false,
  label,
  title,
}) {
  return (
    <label className="inline-flex items-center gap-2" title={title}>
      {label && (
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-white/40">
          {label}
        </span>
      )}
      <div className="relative inline-flex items-center">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled || loading}
          className="appearance-none rounded-lg border border-white/[0.12] bg-white/[0.05] py-1 pl-2.5 pr-7 text-[12px] font-medium text-white/85 outline-none transition hover:border-cyan-400/40 focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value} className="bg-[#0b1120] text-white">
              {o.label}
            </option>
          ))}
        </select>
        <span className="pointer-events-none absolute right-2 flex items-center text-white/40">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : (
            <svg width="9" height="9" viewBox="0 0 10 6" fill="none" aria-hidden="true">
              <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </span>
      </div>
    </label>
  )
}
