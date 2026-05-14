import { useEffect, useState, useCallback } from 'react'
import { Plus, BookOpen } from 'lucide-react'
import { listDocs } from '../lib/knowledge'
import KnowledgeDocCard from './KnowledgeDocCard'
import KnowledgeUploadModal from './KnowledgeUploadModal'

export default function KnowledgeBase({ meetingId } = {}) {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const list = await listDocs({ meetingId })
      setDocs(list)
    } finally {
      setLoading(false)
    }
  }, [meetingId])

  useEffect(() => { refresh() }, [refresh])

  // Poll while any doc is processing
  useEffect(() => {
    if (!docs.some(d => d.status === 'processing')) return
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [docs, refresh])

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-cyan-300" />
          <h1 className="text-xl font-semibold text-white">Knowledge Base</h1>
        </div>
        <button onClick={() => setModalOpen(true)}
                className="flex items-center gap-1.5 rounded-lg bg-cyan-400 px-3 py-1.5 text-xs font-semibold text-[#07040f] hover:bg-cyan-300">
          <Plus className="h-3.5 w-3.5" /> Add Document
        </button>
      </div>

      {loading && docs.length === 0 ? (
        <p className="text-sm text-white/50">Loading…</p>
      ) : docs.length === 0 ? (
        <p className="text-sm text-white/50">No documents yet. Click "Add Document" to upload.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {docs.map(d => <KnowledgeDocCard key={d.id} doc={d} onChange={refresh} />)}
        </div>
      )}

      <KnowledgeUploadModal open={modalOpen} onClose={() => setModalOpen(false)}
                            meetingId={meetingId} onUploaded={refresh} />
    </div>
  )
}
