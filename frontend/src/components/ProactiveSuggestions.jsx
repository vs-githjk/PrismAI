import { useState } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function computeSuggestions(result) {
  const suggestions = []

  // 1. Calendar deep link — highest priority, zero-cost action
  if (result.calendar_suggestion?.recommended) {
    const title = encodeURIComponent('Follow-up Meeting')
    const details = encodeURIComponent(result.calendar_suggestion.reason || 'Follow-up from meeting')
    const calUrl = `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${title}&details=${details}`
    suggestions.push({
      id: 'calendar',
      accentColor: '#ec4899',
      label: 'Follow-up meeting recommended — add to Google Calendar?',
      actionLabel: 'Open Calendar',
      actionType: 'link',
      href: calUrl,
    })
  }

  // 2. Slack update — if 3+ action items
  if (result.action_items?.length >= 3) {
    suggestions.push({
      id: 'slack',
      accentColor: '#0ea5e9',
      label: `${result.action_items.length} action items detected — draft a Slack update?`,
      actionLabel: 'Draft Update',
      actionType: 'chat',
      instruction: 'Write a short, Slack-style team update (max 5 lines, no markdown headers, no bullet symbols) summarizing the key outcomes and action items from this meeting.',
    })
  }

  // 3. Facilitation tip — if tension detected
  const hasTension =
    ['tense', 'unresolved', 'conflicted'].includes(result.sentiment?.overall?.toLowerCase()) ||
    result.sentiment?.tension_moments?.length > 0
  if (hasTension) {
    suggestions.push({
      id: 'tension',
      accentColor: '#f59e0b',
      label: 'Tension detected — want a facilitation coaching tip?',
      actionLabel: 'Get Tip',
      actionType: 'chat',
      instruction: 'Give me one specific, actionable facilitation technique I can use in my next meeting to reduce tension and improve psychological safety. Keep it to 3–4 sentences.',
    })
  }

  // 4. Health improvement tips — if score < 60
  const score = result.health_score?.score
  if (score !== undefined && score !== null && score < 60 && score > 0) {
    suggestions.push({
      id: 'health',
      accentColor: '#8b5cf6',
      label: `Low health score (${score}/100) — want tips to improve?`,
      actionLabel: 'Get Tips',
      actionType: 'chat',
      instruction: `Our meeting health score was ${score}/100 (verdict: "${result.health_score.verdict}"). Give me 3 specific, concrete things we can do differently next time to improve the score. Be direct and practical.`,
    })
  }

  return suggestions.slice(0, 3)
}

export default function ProactiveSuggestions({ result, transcript }) {
  const [state, setState] = useState({})

  // Only render once health_score is present (signals stream is complete)
  if (!result?.health_score?.score && result?.health_score?.score !== 0) return null

  const suggestions = computeSuggestions(result)
  const visible = suggestions.filter(s => !state[s.id]?.dismissed)
  if (!visible.length) return null

  async function handleAction(s) {
    if (s.actionType === 'link') {
      window.open(s.href, '_blank', 'noopener,noreferrer')
      setState(prev => ({ ...prev, [s.id]: { ...prev[s.id], dismissed: true } }))
      return
    }

    setState(prev => ({ ...prev, [s.id]: { ...prev[s.id], loading: true, error: null } }))
    try {
      const res = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: s.instruction, transcript: transcript || '' }),
      })
      if (!res.ok) throw new Error('Request failed')
      const data = await res.json()
      setState(prev => ({ ...prev, [s.id]: { ...prev[s.id], loading: false, response: data.response } }))
    } catch {
      setState(prev => ({ ...prev, [s.id]: { ...prev[s.id], loading: false, error: 'Something went wrong — try again.' } }))
    }
  }

  function dismiss(id) {
    setState(prev => ({ ...prev, [id]: { ...prev[id], dismissed: true } }))
  }

  return (
    <div className="rounded-2xl overflow-hidden animate-fade-in-up"
      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
      {/* Top accent bar */}
      <div className="h-0.5 w-full" style={{ background: 'linear-gradient(90deg, #0ea5e9, #8b5cf6, transparent)' }} />

      <div className="p-4">
        {/* Panel header */}
        <div className="flex items-center gap-2 mb-3">
          <div className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.25)' }}>
            {/* Sparkle icon */}
            <svg className="w-3.5 h-3.5 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
            </svg>
          </div>
          <span className="text-xs font-semibold text-gray-300">Suggested Actions</span>
          <span className="ml-auto text-[10px] text-gray-600">
            {visible.length} suggestion{visible.length !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Suggestion rows */}
        <div className="space-y-2">
          {visible.map(s => {
            const st = state[s.id] || {}
            return (
              <div key={s.id} className="rounded-xl p-3 flex items-start gap-3"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>

                {/* Accent dot */}
                <div className="w-2 h-2 rounded-full flex-shrink-0 mt-1.5"
                  style={{ background: s.accentColor, boxShadow: `0 0 6px ${s.accentColor}80` }} />

                {/* Label + response */}
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-300 leading-relaxed">{s.label}</p>

                  {st.response && (
                    <div className="mt-2 p-2.5 rounded-lg text-xs text-gray-300 leading-relaxed whitespace-pre-wrap"
                      style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.06)' }}>
                      {st.response}
                    </div>
                  )}

                  {st.error && (
                    <p className="mt-1.5 text-[11px] text-red-400">{st.error}</p>
                  )}
                </div>

                {/* Action button + dismiss */}
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  {!st.response && (
                    <button
                      onClick={() => handleAction(s)}
                      disabled={st.loading}
                      className="text-[11px] px-2.5 py-1.5 rounded-lg font-medium transition-all hover:scale-105 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
                      style={{
                        background: `${s.accentColor}20`,
                        color: s.accentColor,
                        border: `1px solid ${s.accentColor}50`,
                      }}>
                      {st.loading ? (
                        <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor"
                            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                      ) : s.actionLabel}
                    </button>
                  )}
                  <button
                    onClick={() => dismiss(s.id)}
                    className="text-gray-700 hover:text-gray-400 transition-colors p-0.5"
                    title="Dismiss">
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
