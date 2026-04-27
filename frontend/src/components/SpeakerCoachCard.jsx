import { useState, useEffect } from 'react'

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
  const color = percent >= 60 ? '#ef4444' : percent >= 30 ? '#6366f1' : '#10b981'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
        <div
          className="h-1.5 rounded-full"
          style={{ width: `${displayed}%`, background: color, transition: 'width 16ms linear' }}
        />
      </div>
      <span className="text-[10px] text-gray-400 font-mono w-8 text-right flex-shrink-0">{displayed}%</span>
    </div>
  )
}

function SpeakerRow({ speaker }) {
  const { name, talk_percent, decisions_owned, action_items_owned, coaching_note } = speaker
  const initials = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-3">
        {/* Avatar */}
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-[11px] font-bold text-white/80"
          style={{ background: 'linear-gradient(135deg, rgba(244,63,94,0.4), rgba(251,113,133,0.2))', border: '1px solid rgba(244,63,94,0.3)' }}
        >
          {initials}
        </div>

        <div className="flex-1 min-w-0">
          {/* Name row + owned pills */}
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-medium text-gray-200 truncate">{name}</span>
            <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
              {decisions_owned > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-500/15 border border-yellow-500/25 text-yellow-300">
                  ⚖️ {decisions_owned}
                </span>
              )}
              {action_items_owned > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-orange-500/15 border border-orange-500/25 text-orange-300">
                  ✅ {action_items_owned}
                </span>
              )}
            </div>
          </div>
          <TalkBar percent={talk_percent} />
        </div>
      </div>

      {coaching_note && (
        <p className="text-[11px] text-gray-400 leading-relaxed pl-11">{coaching_note}</p>
      )}
    </div>
  )
}

function BalanceBar({ score }) {
  const displayed = useCountUp(score ?? 100, 1000)
  const color = score >= 70 ? '#10b981' : score >= 40 ? '#f59e0b' : '#ef4444'
  const label = score >= 70 ? 'Balanced' : score >= 40 ? 'Moderate' : 'Unbalanced'

  return (
    <div className="mb-5">
      <div className="flex justify-between mb-1">
        <span className="text-[11px] text-gray-500">Conversation balance</span>
        <span className="text-[11px] font-medium" style={{ color }}>{label} · {displayed}/100</span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
        <div
          className="h-1.5 rounded-full transition-all duration-1000"
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
    <div
      className="rounded-2xl border border-rose-500/25 overflow-hidden transition-transform duration-200 hover:-translate-y-0.5"
      style={{ background: 'rgba(255,255,255,0.03)' }}
    >
      <div className="h-0.5 w-full" style={{ background: 'linear-gradient(90deg, #f43f5e, #fb7185, transparent)' }} />
      <div className="p-5">
        {/* Header */}
        <div className="flex items-center gap-2 mb-5">
          <div className="w-7 h-7 rounded-lg bg-rose-500/10 border border-rose-500/25 flex items-center justify-center text-sm">
            🎤
          </div>
          <h3 className="text-sm font-semibold text-rose-300">Speaker Coaching</h3>
          <span className="ml-auto text-[11px] font-semibold px-2 py-0.5 rounded-full bg-rose-500/10 border border-rose-500/25 text-rose-300">
            {speakers.length} speaker{speakers.length !== 1 ? 's' : ''}
          </span>
        </div>

        <BalanceBar score={balance_score} />

        {/* Speaker rows */}
        <div className="space-y-4 pt-1">
          {speakers.map((speaker, i) => (
            <SpeakerRow key={speaker.name || i} speaker={speaker} />
          ))}
        </div>

        <div className="mt-4 pt-4 border-t border-white/5 flex items-start gap-2">
          <svg className="w-3.5 h-3.5 text-gray-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-[11px] text-gray-500 leading-relaxed">
            Talk-time estimates are based on transcript word counts. Coaching notes are suggestions, not evaluations.
          </p>
        </div>
      </div>
    </div>
  )
}
