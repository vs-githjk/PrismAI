export default function SkeletonCard({ lines = 3, tall = false }) {
  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}>
      <div className="h-0.5 w-full animate-pulse" style={{ background: 'linear-gradient(90deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03), rgba(255,255,255,0.08))' }} />
      <div className="p-5">
        {/* Header shimmer */}
        <div className="flex items-center gap-2 mb-4">
          <div className="w-7 h-7 rounded-lg animate-pulse" style={{ background: 'rgba(255,255,255,0.06)' }} />
          <div className="h-3 w-24 rounded-full animate-pulse" style={{ background: 'rgba(255,255,255,0.06)' }} />
        </div>
        {/* Body shimmers */}
        <div className={`space-y-2.5 ${tall ? 'pb-4' : ''}`}>
          {Array.from({ length: lines }).map((_, i) => (
            <div key={i} className="h-3 rounded-full animate-pulse"
              style={{ background: 'rgba(255,255,255,0.05)', width: `${[95, 80, 65, 85, 70][i % 5]}%`, animationDelay: `${i * 0.1}s` }} />
          ))}
        </div>
      </div>
    </div>
  )
}
