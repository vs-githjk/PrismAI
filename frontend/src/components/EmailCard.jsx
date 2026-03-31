import { useState } from 'react'

export default function EmailCard({ email }) {
  const [copied, setCopied] = useState(false)

  if (!email || (!email.subject && !email.body)) return null

  const handleCopy = () => {
    const text = `Subject: ${email.subject}\n\n${email.body}`
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="rounded-2xl border border-white/8 overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)' }}>
      <div className="h-0.5 w-full" style={{ background: 'linear-gradient(90deg, #10b981, #34d399, transparent)' }}></div>
      <div className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center">
              <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <h3 className="text-xs font-semibold text-emerald-400 uppercase tracking-widest">Follow-up Email Draft</h3>
          </div>
          <button
            onClick={handleCopy}
            className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-all ${
              copied
                ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300'
                : 'bg-white/5 border-white/10 text-gray-400 hover:bg-white/10 hover:text-gray-200'
            }`}
          >
            {copied ? (
              <>
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Copied!
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                Copy
              </>
            )}
          </button>
        </div>

        {/* Email chrome */}
        <div className="rounded-xl border border-white/8 overflow-hidden" style={{ background: 'rgba(0,0,0,0.3)' }}>
          {email.subject && (
            <div className="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
              <span className="text-xs text-gray-500 flex-shrink-0">Subject:</span>
              <span className="text-sm text-gray-200 font-medium">{email.subject}</span>
            </div>
          )}
          <pre className="font-mono text-sm text-gray-300 whitespace-pre-wrap p-4 leading-relaxed overflow-x-auto">
            {email.body}
          </pre>
        </div>
      </div>
    </div>
  )
}
