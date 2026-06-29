import { useEffect, useState } from 'react'
import { Sparkles, Triangle, Zap, Gem, Radio, Sun, BarChart3 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog'

// Names + icons mirror backend/personas.py PERSONA_NAMES. Keep in sync — the
// bot self-identifies by these names in meetings, so the picker MUST show them.
const PRESETS = [
  { key: 'default',    label: 'Default',    name: 'Prism',    Icon: Triangle,  iconClass: 'text-cyan-300/90'    },
  { key: 'concise',    label: 'Concise',    name: 'Flash',    Icon: Zap,       iconClass: 'text-amber-300/90'   },
  { key: 'formal',     label: 'Formal',     name: 'Crystal',  Icon: Gem,       iconClass: 'text-slate-200/90'   },
  { key: 'cheeky',     label: 'Cheeky',     name: 'Glint',    Icon: Sparkles,  iconClass: 'text-fuchsia-300/90' },
  { key: 'socratic',   label: 'Socratic',   name: 'Echo',     Icon: Radio,     iconClass: 'text-indigo-300/90'  },
  { key: 'warm',       label: 'Warm',       name: 'Glow',     Icon: Sun,       iconClass: 'text-orange-300/90'  },
  { key: 'analytical', label: 'Analytical', name: 'Spectrum', Icon: BarChart3, iconClass: 'text-violet-300/90'  },
]

const PRESET_BY_KEY = Object.fromEntries(PRESETS.map((p) => [p.key, p]))

const CUSTOM_MAX = 500

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

function presetInfo(key) {
  return PRESET_BY_KEY[key] || PRESET_BY_KEY.default
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

  const isCustom = personaPreset === 'custom'
  const chipLabel = isCustom ? 'Custom' : capitalize(personaPreset || 'default')
  // Custom presets are tone-only — the bot still calls itself Prism, so the
  // name shown here matches what the user will actually say in the meeting.
  const chipName = isCustom ? 'Prism' : presetInfo(personaPreset || 'default').name
  const ChipIcon = isCustom ? Sparkles : presetInfo(personaPreset || 'default').Icon
  const chipIconClass = isCustom ? 'text-cyan-300/90' : presetInfo(personaPreset || 'default').iconClass

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
          className="inline-flex items-center gap-1 rounded-full border border-cyan-400/25 bg-cyan-400/[0.10] px-2 py-0.5 text-[9.5px] font-medium uppercase tracking-wider text-cyan-200/90 hover:bg-cyan-400/[0.16]"
          aria-haspopup="dialog"
          aria-expanded={open}
        >
          <ChipIcon className={`h-3 w-3 shrink-0 ${chipIconClass}`} aria-hidden="true" />
          {sourcePrefix}
          {chipLabel} · {chipName} ▾
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex w-full items-center gap-3 px-3 py-2 text-xs font-semibold text-white/84 hover:bg-cyan-300/[0.08]"
        >
          <ChipIcon className={`h-4 w-4 shrink-0 ${chipIconClass}`} aria-hidden="true" />
          Persona
          <span className="ml-auto text-[10px] font-medium text-white/40">
            {chipLabel} · <span className="text-white/70">{chipName}</span>
          </span>
        </button>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="dashboard-popup dashboard-body-font text-white sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-sm font-semibold text-white">
              Pick persona
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-1.5">
            {PRESETS.map((p) => {
              const Icon = p.Icon
              return (
                <label
                  key={p.key}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-[12px] hover:bg-white/[0.04]"
                >
                  <input
                    type="radio"
                    name="persona-preset"
                    checked={draftPreset === p.key}
                    onChange={() => setDraftPreset(p.key)}
                    className="accent-cyan-400"
                  />
                  <Icon className={`h-3.5 w-3.5 shrink-0 ${p.iconClass}`} aria-hidden="true" />
                  <span>{p.label}</span>
                  <span className="ml-auto text-[11px] text-white/50">
                    {p.key === 'default' ? 'Prism' : p.name}
                  </span>
                </label>
              )
            })}
            <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-[12px] hover:bg-white/[0.04]">
              <input
                type="radio"
                name="persona-preset"
                checked={draftPreset === 'custom'}
                onChange={() => setDraftPreset('custom')}
                className="accent-cyan-400"
              />
              <Sparkles className="h-3.5 w-3.5 shrink-0 text-cyan-300/90" aria-hidden="true" />
              <span>Custom…</span>
              <span className="ml-auto text-[11px] text-white/40">Prism</span>
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
              Use workspace default ({capitalize(workspaceDefault)} · {presetInfo(workspaceDefault).name})
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
