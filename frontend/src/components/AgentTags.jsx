// ROYGBIV — one color per agent, white = orchestrator/input
const AGENT_CONFIG = {
  summarizer:         { label: 'Summarizer',   icon: '📝', bg: 'bg-red-500/20',    border: 'border-red-500/40',    text: 'text-red-300',    dot: 'bg-red-400' },
  action_items:       { label: 'Action Items', icon: '✅', bg: 'bg-orange-500/20', border: 'border-orange-500/40', text: 'text-orange-300', dot: 'bg-orange-400' },
  decisions:          { label: 'Decisions',    icon: '⚖️', bg: 'bg-yellow-500/20', border: 'border-yellow-500/40', text: 'text-yellow-200', dot: 'bg-yellow-400' },
  sentiment:          { label: 'Sentiment',    icon: '💬', bg: 'bg-emerald-500/20',border: 'border-emerald-500/40',text: 'text-emerald-300',dot: 'bg-emerald-400' },
  email_drafter:      { label: 'Email Draft',  icon: '✉️', bg: 'bg-blue-500/20',   border: 'border-blue-500/40',   text: 'text-blue-300',   dot: 'bg-blue-400' },
  calendar_suggester: { label: 'Calendar',     icon: '📅', bg: 'bg-indigo-500/20', border: 'border-indigo-500/40', text: 'text-indigo-300', dot: 'bg-indigo-400' },
  health_score:       { label: 'Health Score', icon: '📊', bg: 'bg-violet-500/20', border: 'border-violet-500/40', text: 'text-violet-300', dot: 'bg-violet-400' },
}

export default function AgentTags({ agents }) {
  if (!agents || agents.length === 0) return null

  return (
    <div className="rounded-2xl border border-white/8 p-4 animate-fade-in-up card-delay-0"
      style={{ background: 'rgba(255,255,255,0.02)' }}>
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        {/* Orchestrator badge */}
        <div className="flex items-center gap-2 pr-4 sm:border-r border-white/10">
          <div className="w-7 h-7 rounded-lg bg-white/10 border border-white/20 flex items-center justify-center flex-shrink-0">
            <svg className="w-3.5 h-3.5 text-white/70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
          </div>
          <div>
            <p className="text-[11px] font-semibold text-gray-300 leading-none">Orchestrator</p>
            <p className="text-[10px] text-gray-500 mt-0.5">dispatched {agents.length} agent{agents.length !== 1 ? 's' : ''}</p>
          </div>
        </div>

        {/* Arrow */}
        <svg className="hidden sm:block w-4 h-4 text-gray-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>

        {/* Agent tags */}
        <div className="flex flex-wrap gap-2">
          {agents.map((agent, i) => {
            const config = AGENT_CONFIG[agent] || {
              label: agent, icon: '⚙️', bg: 'bg-gray-500/15', border: 'border-gray-500/35', text: 'text-gray-300', dot: 'bg-gray-400'
            }
            return (
              <div
                key={agent}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium ${config.bg} ${config.border} ${config.text} animate-fade-in-up`}
                style={{ animationDelay: `${i * 0.07}s` }}
              >
                <span className="text-sm leading-none">{config.icon}</span>
                {config.label}
                <div className={`w-1.5 h-1.5 rounded-full ${config.dot} opacity-70`}></div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
