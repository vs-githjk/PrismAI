import { useState, useEffect } from 'react'
import { Mic } from 'lucide-react'
import { cardGlowStyle, eyebrow, glassCard, subtleText } from './dashboardStyles'

function useCountUp(target, duration = 1000) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    if (target === undefined || target === null) return
    let start = null
    const step = (timestamp) => {
      if (!start) start = timestamp
      const progress = Math.min((timestamp - start) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(eased * target))
      if (progress < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }, [target, duration])
  return display
}

function TalkBar({ percent }) {
  const displayed = useCountUp(percent || 0, 1000)
  const color = percent >= 60 ? '#f87171' : percent >= 30 ? '#818cf8' : '#34d399'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-1 rounded-full"
          style={{ width: `${displayed}%`, background: color, transition: 'width 16ms linear' }}
        />
      </div>
      <span className="w-8 flex-shrink-0 text-right font-mono text-[10px] text-white/40">{displayed}%</span>
    </div>
  )
}

function SpeakerRow({ speaker, isLast }) {
  const { name, talk_percent, decisions_owned, action_items_owned, coaching_note } = speaker
  const initials = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()

  return (
    <div className={`px-3 py-2.5 ${isLast ? '' : 'border-b border-white/[0.07]'}`}>
      <div className="mb-1.5 flex items-center gap-3">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/[0.14] bg-white/[0.05] text-[10px] font-bold text-white/70">
          {initials}
        </div>
        <span className="flex-1 truncate text-sm font-medium text-white">{name}</span>
        <div className="flex shrink-0 items-center gap-1">
          {decisions_owned > 0 && (
            <span className="rounded border border-yellow-500/25 bg-yellow-500/15 px-1.5 py-0.5 text-[10px] text-yellow-300">
              ⚖️ {decisions_owned}
            </span>
          )}
          {action_items_owned > 0 && (
            <span className="rounded border border-orange-500/25 bg-orange-500/15 px-1.5 py-0.5 text-[10px] text-orange-300">
              ✅ {action_items_owned}
            </span>
          )}
        </div>
      </div>
      <TalkBar percent={talk_percent} />
      {coaching_note && (
        <p className={`mt-1.5 pl-10 ${subtleText}`}>{coaching_note}</p>
      )}
    </div>
  )
}

function BalanceBar({ score }) {
  const displayed = useCountUp(score ?? 100, 1000)
  const color = score >= 70 ? '#34d399' : score >= 40 ? '#fbbf24' : '#f87171'
  const label = score >= 70 ? 'Balanced' : score >= 40 ? 'Moderate' : 'Unbalanced'

  return (
    <div className="border-b border-white/[0.07] px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <span className={subtleText}>Conversation balance</span>
        <span className="text-[11px] font-medium" style={{ color }}>{label} · {displayed}/100</span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-1 rounded-full transition-all duration-1000"
          style={{ width: `${displayed}%`, background: color, boxShadow: `0 0 6px ${color}60` }}
        />
      </div>
    </div>
  )
}

export default function SpeakerCoachCard({ speakerCoach }) {
  if (!speakerCoach || !speakerCoach.speakers?.length) return null

  const { speakers, balance_score } = speakerCoach

  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3 flex items-center gap-2">
        <Mic className="h-4 w-4 text-cyan-200/70" aria-hidden="true" />
        <p className={eyebrow}>Speaker Coaching</p>
        <span className="ml-auto rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-white/50">
          {speakers.length} speaker{speakers.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="overflow-hidden rounded-lg border border-white/[0.08]">
        <BalanceBar score={balance_score} />
        {speakers.map((speaker, i) => (
          <SpeakerRow key={speaker.name || i} speaker={speaker} isLast={i === speakers.length - 1} />
        ))}
      </div>

      <p className={`mt-3 ${subtleText}`}>
        Talk-time estimates are based on transcript word counts. Coaching notes are suggestions, not evaluations.
      </p>
    </section>
  )
}
