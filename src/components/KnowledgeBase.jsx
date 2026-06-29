import { useEffect, useState, useCallback } from 'react'
import { Plus, BookOpen } from 'lucide-react'
import { listDocs } from '../lib/knowledge'
import KnowledgeDocCard from './KnowledgeDocCard'
import KnowledgeUploadModal from './KnowledgeUploadModal'
import { glassCard, cardGlowStyle, eyebrow, subtleText } from './dashboard/dashboardStyles'

export default function KnowledgeBase({ meetingId, workspaceId, workspaceName } = {}) {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)

  const scopeLabel = workspaceId ? (workspaceName || 'Workspace') : 'Personal'

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const list = await listDocs({ meetingId, workspaceId })
      setDocs(list)
    } finally {
      setLoading(false)
    }
  }, [meetingId, workspaceId])

  useEffect(() => { refresh() }, [refresh])

  // Poll while any doc is processing
  useEffect(() => {
    if (!docs.some(d => d.status === 'processing')) return
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [docs, refresh])

  return (
    <div className="space-y-4">
      {/* Page header — mirrors MeetingView's eyebrow + title pattern */}
      <div className="flex items-end justify-between gap-3 px-0.5">
        <div>
          <p className={eyebrow}>Knowledge base</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-white">
            {scopeLabel} documents
          </h1>
          <p className={`mt-0.5 ${subtleText}`}>
            {workspaceId
              ? 'Shared with everyone in this workspace — grounds Prism’s answers during meetings.'
              : 'Private to you. Switch to a workspace to add shared team knowledge.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-cyan-400 px-3.5 py-2 text-[13px] font-semibold text-[#07040f] transition hover:bg-cyan-300"
        >
          <Plus className="h-4 w-4" /> Add document
        </button>
      </div>

      {loading && docs.length === 0 ? (
        <section className={`${glassCard} p-8`} style={cardGlowStyle}>
          <p className={subtleText}>Loading documents…</p>
        </section>
      ) : docs.length === 0 ? (
        <section className={`${glassCard} flex flex-col items-center justify-center gap-3 px-6 py-14 text-center`} style={cardGlowStyle}>
          <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/[0.12] bg-white/[0.04]">
            <BookOpen className="h-5 w-5 text-cyan-200/70" aria-hidden="true" />
          </div>
          <div>
            <p className="text-sm font-semibold text-white/90">No documents in {scopeLabel.toLowerCase()} yet</p>
            <p className={`mt-1 ${subtleText}`}>
              Add a PDF, doc, URL, or Notion page — Prism cites them when answering questions.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="mt-1 inline-flex items-center gap-1.5 rounded-full border border-cyan-400/30 bg-cyan-400/[0.10] px-3.5 py-2 text-[13px] font-semibold text-cyan-200 transition hover:border-cyan-400/50 hover:bg-cyan-400/[0.16]"
          >
            <Plus className="h-4 w-4" /> Add your first document
          </button>
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {docs.map(d => <KnowledgeDocCard key={d.id} doc={d} onChange={refresh} />)}
        </div>
      )}

      <KnowledgeUploadModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        meetingId={meetingId}
        workspaceId={workspaceId}
        onUploaded={refresh}
      />
    </div>
  )
}
