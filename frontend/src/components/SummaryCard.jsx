export default function SummaryCard({ summary }) {
  if (!summary) return null

  return (
    <div className="rounded-2xl overflow-hidden card-glow-indigo" style={{ background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.2)' }}>
      <div className="h-0.5 w-full" style={{ background: 'linear-gradient(90deg, #6366f1, #38bdf8, transparent)' }}></div>
      <div className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-7 h-7 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center">
            <svg className="w-3.5 h-3.5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <h3 className="text-xs font-semibold text-indigo-400 uppercase tracking-widest">Summary</h3>
        </div>
        <p className="text-gray-200 leading-relaxed text-sm">{summary}</p>
      </div>
    </div>
  )
}
