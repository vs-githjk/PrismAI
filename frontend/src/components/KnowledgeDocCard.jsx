import { FileText, Globe, RefreshCw, Trash2 } from 'lucide-react'
import { deleteDoc, resyncDoc, updateDoc } from '../lib/knowledge'

const SENSITIVITY_COLOR = {
  public: 'text-emerald-300 bg-emerald-500/10',
  internal: 'text-sky-300 bg-sky-500/10',
  confidential: 'text-rose-300 bg-rose-500/10',
}

const STATUS_LABEL = {
  processing: 'Processing…',
  ready: 'Ready',
  error: 'Error',
  stale: 'Stale',
}

export default function KnowledgeDocCard({ doc, onChange }) {
  const Icon = doc.source_type === 'url' ? Globe : FileText

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
    <div className="flex flex-col gap-2 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className="h-4 w-4 text-cyan-200/70 flex-shrink-0" />
          <span className="text-sm font-medium text-white truncate">{doc.name}</span>
        </div>
        <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wider ${SENSITIVITY_COLOR[doc.sensitivity] || ''}`}>
          {doc.sensitivity}
        </span>
      </div>
      <div className="flex items-center gap-3 text-[11px] text-white/50">
        <span>{STATUS_LABEL[doc.status] || doc.status}</span>
        <span>·</span>
        <span>{doc.chunk_count ?? 0} chunks</span>
        {doc.meeting_id && <><span>·</span><span>Pinned</span></>}
      </div>
      {doc.error_message && (
        <p className="text-[11px] text-rose-300/80">{doc.error_message}</p>
      )}
      <div className="flex items-center gap-2 pt-1">
        <select
          value={doc.sensitivity}
          onChange={handleSensitivity}
          className="rounded border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/80"
        >
          <option value="public">Public</option>
          <option value="internal">Internal</option>
          <option value="confidential">Confidential</option>
        </select>
        <button onClick={handleResync} className="rounded border border-white/10 bg-white/5 p-1 hover:text-cyan-300" title="Re-sync">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
        <button onClick={handleDelete} className="rounded border border-white/10 bg-white/5 p-1 hover:text-rose-300" title="Delete">
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}
