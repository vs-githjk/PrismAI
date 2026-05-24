import { FileText, Globe, RefreshCw, Trash2 } from 'lucide-react'
import { deleteDoc, resyncDoc, updateDoc } from '../lib/knowledge'
import { glassCard, cardGlowStyle, subtleText } from './dashboard/dashboardStyles'

const SENSITIVITY_META = {
  public:       { label: 'Public',       cls: 'border-emerald-400/30 bg-emerald-400/[0.10] text-emerald-300' },
  internal:     { label: 'Internal',     cls: 'border-sky-400/30 bg-sky-400/[0.10] text-sky-300' },
  confidential: { label: 'Confidential', cls: 'border-rose-400/30 bg-rose-400/[0.10] text-rose-300' },
}

const STATUS_META = {
  processing: { label: 'Processing', dot: 'bg-amber-400 animate-pulse' },
  ready:      { label: 'Ready',      dot: 'bg-emerald-400' },
  error:      { label: 'Error',      dot: 'bg-rose-400' },
  stale:      { label: 'Stale',      dot: 'bg-white/40' },
}

export default function KnowledgeDocCard({ doc, onChange }) {
  const Icon = doc.source_type === 'url' ? Globe : FileText
  const sens = SENSITIVITY_META[doc.sensitivity] || SENSITIVITY_META.internal
  const status = STATUS_META[doc.status] || { label: doc.status, dot: 'bg-white/40' }

  const handleDelete = async () => {
    if (!confirm(`Delete "${doc.name}"?`)) return
    await deleteDoc(doc.id)
    onChange?.()
  }

  const handleResync = async () => {
    await resyncDoc(doc.id)
    onChange?.()
  }

  const handleSensitivity = async (e) => {
    await updateDoc(doc.id, { sensitivity: e.target.value })
    onChange?.()
  }

  return (
    <section className={`${glassCard} flex flex-col gap-3 p-4`} style={cardGlowStyle}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/[0.12] bg-white/[0.04]">
            <Icon className="h-3.5 w-3.5 text-cyan-200/80" aria-hidden="true" />
          </div>
          <span className="truncate text-sm font-semibold text-white">{doc.name}</span>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${sens.cls}`}>
          {sens.label}
        </span>
      </div>

      <div className="flex items-center gap-2 text-[11px] text-white/55">
        <span className="flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
          {status.label}
        </span>
        <span className="text-white/25">·</span>
        <span>{doc.chunk_count ?? 0} chunks</span>
        {doc.meeting_id && (
          <>
            <span className="text-white/25">·</span>
            <span className="text-cyan-200/70">Pinned</span>
          </>
        )}
      </div>

      {doc.error_message && (
        <p className="rounded-lg border border-rose-400/[0.18] bg-rose-400/[0.05] px-2.5 py-1.5 text-[11px] leading-snug text-rose-300/90">
          {doc.error_message}
        </p>
      )}

      <div className="flex items-center gap-2 border-t border-white/[0.07] pt-3">
        <select
          value={doc.sensitivity}
          onChange={handleSensitivity}
          aria-label="Sensitivity"
          className="rounded-lg border border-white/[0.12] bg-white/[0.04] px-2 py-1 text-[11px] text-white/80 focus:border-cyan-400/40 focus:outline-none"
        >
          <option value="public">Public</option>
          <option value="internal">Internal</option>
          <option value="confidential">Confidential</option>
        </select>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            onClick={handleResync}
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/[0.12] bg-white/[0.04] text-white/55 transition hover:border-white/[0.2] hover:text-cyan-300"
            title="Re-sync"
            aria-label="Re-sync document"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={handleDelete}
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/[0.12] bg-white/[0.04] text-white/55 transition hover:border-rose-400/30 hover:text-rose-300"
            title="Delete"
            aria-label="Delete document"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </section>
  )
}
