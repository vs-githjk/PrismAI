import { useEffect, useState } from 'react'
import { ExternalLink, FileText, Globe, Loader2 } from 'lucide-react'
import { getDoc } from '../lib/knowledge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog'

const SENSITIVITY_META = {
  public:       { label: 'Public',       cls: 'border-emerald-400/30 bg-emerald-400/[0.10] text-emerald-300' },
  internal:     { label: 'Internal',     cls: 'border-sky-400/30 bg-sky-400/[0.10] text-sky-300' },
  confidential: { label: 'Confidential', cls: 'border-rose-400/30 bg-rose-400/[0.10] text-rose-300' },
}

// Modal that shows the extracted text Prism actually indexed for a doc, plus a
// link to the original file/source when one exists.
export default function KnowledgeDocViewer({ doc, open, onOpenChange }) {
  const [full, setFull] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !doc?.id) return
    let cancelled = false
    setLoading(true)
    setError('')
    setFull(null)
    getDoc(doc.id)
      .then((d) => { if (!cancelled) setFull(d) })
      .catch((e) => { if (!cancelled) setError(e.message || 'Could not load this document.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [open, doc?.id])

  const Icon = doc?.source_type === 'url' ? Globe : FileText
  const sens = SENSITIVITY_META[doc?.sensitivity] || SENSITIVITY_META.internal
  const originalUrl = full?.original_url
  const originalLabel = doc?.source_type === 'url' || doc?.source_type === 'notion' || doc?.source_type === 'gdrive'
    ? 'Open source'
    : 'Open original'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="dashboard-popup dashboard-body-font text-white sm:max-w-2xl" showCloseButton>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 pr-8 text-white">
            <Icon className="h-4 w-4 shrink-0 text-cyan-200/80" aria-hidden="true" />
            <span className="min-w-0 truncate">{doc?.name || 'Document'}</span>
          </DialogTitle>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-white/55">
            <span className={`rounded-full border px-2 py-0.5 font-medium ${sens.cls}`}>{sens.label}</span>
            <span>{full?.chunk_count ?? doc?.chunk_count ?? 0} chunks</span>
            {originalUrl && (
              <a
                href={originalUrl}
                target="_blank"
                rel="noreferrer"
                className="ml-auto inline-flex items-center gap-1 text-cyan-300 transition hover:text-cyan-200"
              >
                {originalLabel} <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </DialogHeader>

        <div className="mt-1 max-h-[60vh] overflow-y-auto rounded-lg border border-white/[0.08] bg-black/30 p-3.5">
          {loading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-white/55">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading extracted text…
            </div>
          ) : error ? (
            <p className="py-4 text-sm text-rose-300/90">{error}</p>
          ) : doc?.status === 'processing' ? (
            <p className="py-4 text-sm text-amber-300/90">Still processing — extracted text will appear once indexing finishes.</p>
          ) : full?.content ? (
            <pre className="whitespace-pre-wrap break-words font-sans text-[13px] leading-6 text-white/80">
              {full.content}
            </pre>
          ) : (
            <p className="py-4 text-sm text-white/45">No extracted text for this document.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
