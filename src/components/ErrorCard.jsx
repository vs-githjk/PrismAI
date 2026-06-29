export default function ErrorCard({ message, onRetry }) {
  const isTimeout = message?.toLowerCase().includes('timed out') || message?.toLowerCase().includes('abort')
  const isRateLimit = message?.includes('429') || message?.toLowerCase().includes('rate limit') || message?.toLowerCase().includes('too many')
  const isNetwork = message?.toLowerCase().includes('failed to fetch') || message?.toLowerCase().includes('network') || message?.toLowerCase().includes('load failed')

  let title, detail, retryLabel
  if (isTimeout) {
    title = 'Server is waking up'
    detail = 'The backend spins down when idle. First requests can take 30–60s. Try again in a moment.'
    retryLabel = 'Retry Analysis'
  } else if (isRateLimit) {
    title = 'Too many requests'
    detail = 'The AI API rate limit was hit. Wait a few seconds and try again.'
    retryLabel = 'Try Again'
  } else if (isNetwork) {
    title = 'Cannot reach the server'
    detail = 'Check your connection or try again shortly.'
    retryLabel = 'Retry'
  } else {
    title = 'Something went wrong'
    detail = message || 'An unexpected error occurred.'
    retryLabel = 'Retry'
  }

  return (
    <div className="mx-6 mb-3 rounded-xl overflow-hidden animate-fade-in-up"
      style={{ background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.25)' }}>
      <div className="h-0.5 w-full" style={{ background: 'linear-gradient(90deg, #ef4444, #f87171, transparent)' }} />
      <div className="px-4 py-3 flex items-start gap-3">
        {/* Icon */}
        <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
          style={{ background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)' }}>
          <svg className="w-3.5 h-3.5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
        </div>

        {/* Text */}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-red-300">{title}</p>
          <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{detail}</p>
        </div>

        {/* Retry button */}
        {onRetry && (
          <button
            onClick={onRetry}
            className="flex-shrink-0 text-[11px] px-3 py-1.5 rounded-lg font-medium transition-all hover:scale-105 active:scale-95"
            style={{ background: 'rgba(239,68,68,0.15)', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.35)' }}>
            {retryLabel}
          </button>
        )}
      </div>
    </div>
  )
}
