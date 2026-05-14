import { useState } from 'react'
import { X, Upload, Link as LinkIcon, FileText } from 'lucide-react'
import { uploadFile, uploadUrl, connectSource } from '../lib/knowledge'

export default function KnowledgeUploadModal({ open, onClose, meetingId, onUploaded }) {
  const [tab, setTab] = useState('file')
  const [url, setUrl] = useState('')
  const [notionId, setNotionId] = useState('')
  const [notionName, setNotionName] = useState('')
  const [sensitivity, setSensitivity] = useState('internal')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (!open) return null

  const close = () => { setError(null); setBusy(false); onClose() }

  const handleFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy(true); setError(null)
    try {
      await uploadFile(file, { meetingId, sensitivity })
      onUploaded?.(); close()
    } catch (err) {
      setError(err?.message || 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  const handleUrl = async () => {
    if (!url.trim()) return
    setBusy(true); setError(null)
    try {
      await uploadUrl(url.trim(), { meetingId, sensitivity })
      onUploaded?.(); close()
    } catch (err) {
      setError(err?.message || 'Failed to ingest URL')
    } finally {
      setBusy(false)
    }
  }

  const handleNotion = async () => {
    if (!notionId.trim() || !notionName.trim()) return
    setBusy(true); setError(null)
    try {
      await connectSource({ sourceType: 'notion', sourceId: notionId.trim(), name: notionName.trim(), meetingId, sensitivity })
      onUploaded?.(); close()
    } catch (err) {
      setError(err?.message || 'Failed to connect Notion page')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0c0a17] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-white">Add to Knowledge Base</h3>
          <button onClick={close}><X className="h-4 w-4 text-white/60" /></button>
        </div>

        <div className="mb-4 flex gap-1 rounded-lg bg-white/5 p-1">
          {[
            { id: 'file', label: 'File', icon: Upload },
            { id: 'url', label: 'URL', icon: LinkIcon },
            { id: 'notion', label: 'Notion', icon: FileText },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs ${tab === t.id ? 'bg-cyan-400/20 text-cyan-200' : 'text-white/60 hover:text-white'}`}
            >
              <t.icon className="h-3 w-3" /> {t.label}
            </button>
          ))}
        </div>

        <div className="mb-3 flex items-center gap-2 text-xs text-white/60">
          Sensitivity:
          <select value={sensitivity} onChange={e => setSensitivity(e.target.value)}
                  className="rounded border border-white/10 bg-white/5 px-2 py-1 text-white/80">
            <option value="public">Public</option>
            <option value="internal">Internal</option>
            <option value="confidential">Confidential</option>
          </select>
        </div>

        {tab === 'file' && (
          <input type="file" accept=".pdf,.docx,.txt,.md" onChange={handleFile} disabled={busy}
                 className="block w-full rounded border border-white/10 bg-white/5 p-3 text-sm text-white/80" />
        )}

        {tab === 'url' && (
          <div className="space-y-2">
            <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com/article"
                   className="w-full rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-white" />
            <button onClick={handleUrl} disabled={busy || !url.trim()}
                    className="w-full rounded bg-cyan-400 px-3 py-2 text-sm font-semibold text-[#07040f] disabled:opacity-40">
              {busy ? 'Ingesting…' : 'Add URL'}
            </button>
          </div>
        )}

        {tab === 'notion' && (
          <div className="space-y-2">
            <input value={notionName} onChange={e => setNotionName(e.target.value)} placeholder="Display name"
                   className="w-full rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-white" />
            <input value={notionId} onChange={e => setNotionId(e.target.value)} placeholder="Notion page ID (UUID)"
                   className="w-full rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-white" />
            <p className="text-[11px] text-white/40">
              Paste the page ID from the Notion URL. Make sure the page is shared with your integration.
            </p>
            <button onClick={handleNotion} disabled={busy || !notionId.trim() || !notionName.trim()}
                    className="w-full rounded bg-cyan-400 px-3 py-2 text-sm font-semibold text-[#07040f] disabled:opacity-40">
              {busy ? 'Connecting…' : 'Add Notion Page'}
            </button>
          </div>
        )}

        {error && <p className="mt-3 text-xs text-rose-300">{error}</p>}
      </div>
    </div>
  )
}
