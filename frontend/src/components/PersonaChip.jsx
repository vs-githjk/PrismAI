import { useEffect, useState } from 'react'
import { Sparkles } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog'

const PRESETS = [
  { key: 'default',    label: 'Default'    },
  { key: 'concise',    label: 'Concise'    },
  { key: 'formal',     label: 'Formal'     },
  { key: 'cheeky',     label: 'Cheeky'     },
  { key: 'socratic',   label: 'Socratic'   },
  { key: 'warm',       label: 'Warm'       },
  { key: 'analytical', label: 'Analytical' },
]

const CUSTOM_MAX = 500

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

/**
 * Persona chip + picker popover.
 *
 * Props:
 *   personaPreset:        string — current preset key (or 'custom')
 *   personaCustomPrompt:  string | null — user's custom text
 *   workspaceDefault:     string | null — workspace's default_persona (null in personal mode)
 *   onSave({preset, customPrompt}) - persist callback
 *   variant:              'chip' | 'menuItem' — affects the trigger styling
 */
export default function PersonaChip({
  personaPreset,
  personaCustomPrompt,
  workspaceDefault,
  onSave,
  variant = 'chip',
}) {
  const [open, setOpen] = useState(false)
  const [draftPreset, setDraftPreset] = useState(personaPreset || 'default')
  const [draftCustom, setDraftCustom] = useState(personaCustomPrompt || '')

  // Note: the picker used to be an absolute-positioned popover inside the
  // trigger's container. That broke when this component is mounted inside a
  // Radix DropdownMenu (account dropdown) — the popover got clipped and the
  // outside-click handler closed it immediately. The shared Dialog primitive
  // handles its own portal + dismiss, so nesting Just Works.

  useEffect(() => {
    if (open) {
      setDraftPreset(personaPreset || 'default')
      setDraftCustom(personaCustomPrompt || '')
    }
  }, [open, personaPreset, personaCustomPrompt])

  const sourcePrefix = !workspaceDefault
    ? ''
    : personaPreset && personaPreset !== 'default'
      ? '👤 '
      : '🏢 '

  const chipLabel = personaPreset === 'custom'
    ? 'Custom'
    : capitalize(personaPreset || 'default')

  const handleSave = () => {
    onSave({
      preset: draftPreset,
      customPrompt: draftPreset === 'custom' ? draftCustom.slice(0, CUSTOM_MAX) : null,
    })
    setOpen(false)
  }

  return (
    <>
      {variant === 'chip' ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-full border border-cyan-400/25 bg-cyan-400/[0.10] px-2 py-0.5 text-[9.5px] font-medium uppercase tracking-wider text-cyan-200/90 hover:bg-cyan-400/[0.16]"
          aria-haspopup="dialog"
          aria-expanded={open}
        >
          {sourcePrefix}Persona: {chipLabel} ▾
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex w-full items-center gap-3 px-3 py-2 text-xs font-semibold text-white/84 hover:bg-cyan-300/[0.08]"
        >
          <Sparkles className="h-4 w-4 shrink-0 text-white/62" aria-hidden="true" />
          Persona
          <span className="ml-auto text-[10px] font-medium text-white/40">
            {chipLabel}
          </span>
        </button>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="dashboard-body-font border-[#2f2f2f] bg-[#0b0b0b] text-white sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-sm font-semibold text-white">
              Pick persona
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-1.5">
            {PRESETS.map((p) => (
              <label key={p.key} className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-[12px] hover:bg-white/[0.04]">
                <input
                  type="radio"
                  name="persona-preset"
                  checked={draftPreset === p.key}
                  onChange={() => setDraftPreset(p.key)}
                  className="accent-cyan-400"
                />
                <span>{p.label}</span>
              </label>
            ))}
            <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-[12px] hover:bg-white/[0.04]">
              <input
                type="radio"
                name="persona-preset"
                checked={draftPreset === 'custom'}
                onChange={() => setDraftPreset('custom')}
                className="accent-cyan-400"
              />
              <span>Custom…</span>
            </label>
          </div>

          {draftPreset === 'custom' && (
            <div className="mt-2">
              <textarea
                value={draftCustom}
                onChange={(e) => setDraftCustom(e.target.value.slice(0, CUSTOM_MAX))}
                placeholder="e.g. Talk like a senior engineer. Be direct."
                rows={3}
                className="w-full rounded-md border border-white/[0.10] bg-white/[0.04] px-2 py-1.5 text-[12px] text-white/85 outline-none focus:border-cyan-400/40"
              />
              <p className="mt-1 text-right text-[10px] text-white/40">
                {draftCustom.length} / {CUSTOM_MAX}
              </p>
            </div>
          )}

          {workspaceDefault && workspaceDefault !== 'default' && (
            <button
              type="button"
              onClick={() => setDraftPreset('default')}
              className="mt-2 w-full rounded-md border border-white/[0.08] bg-white/[0.02] px-2 py-1.5 text-left text-[11px] text-white/55 hover:border-white/[0.16]"
            >
              Use workspace default ({capitalize(workspaceDefault)})
            </button>
          )}

          <p className="mt-3 text-[10px] leading-snug text-white/35">
            Some agents (action items, decisions, scores) ignore tonal personas to preserve accuracy.
          </p>

          <div className="mt-3 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-full border border-white/[0.12] bg-white/[0.04] px-3 py-1 text-[11px] font-semibold text-white/70"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              className="rounded-full border border-cyan-400/40 bg-cyan-400/[0.14] px-3 py-1 text-[11px] font-semibold text-cyan-200"
            >
              Save
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
