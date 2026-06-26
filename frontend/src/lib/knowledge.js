import { apiFetch } from './api'

async function asJson(r) {
  if (!r.ok) {
    let msg = `Request failed (${r.status})`
    try {
      const body = await r.json()
      if (body?.detail) msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* not JSON */ }
    throw new Error(msg)
  }
  try { return await r.json() } catch { return {} }
}

export async function listDocs({ meetingId, workspaceId } = {}) {
  const params = new URLSearchParams()
  if (meetingId) params.set('meeting_id', meetingId)
  if (workspaceId) params.set('workspace_id', workspaceId)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const data = await asJson(await apiFetch(`/knowledge/docs${qs}`))
  return data.docs || []
}

export async function uploadFile(file, { meetingId, workspaceId, sensitivity = 'internal' } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (meetingId) form.append('meeting_id', meetingId)
  if (workspaceId) form.append('workspace_id', workspaceId)
  form.append('sensitivity', sensitivity)
  return asJson(await apiFetch('/knowledge/upload', { method: 'POST', body: form }))
}

export async function uploadUrl(url, { meetingId, workspaceId, sensitivity = 'internal' } = {}) {
  return asJson(await apiFetch('/knowledge/upload-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, meeting_id: meetingId, workspace_id: workspaceId, sensitivity }),
  }))
}

export async function connectSource({ sourceType, sourceId, name, meetingId, workspaceId, sensitivity = 'internal' }) {
  return asJson(await apiFetch('/knowledge/connect-source', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_type: sourceType, source_id: sourceId, name,
      meeting_id: meetingId, workspace_id: workspaceId, sensitivity,
    }),
  }))
}

export async function getDoc(docId) {
  const data = await asJson(await apiFetch(`/knowledge/docs/${docId}`))
  return data.doc || null
}

export async function updateDoc(docId, patch) {
  return asJson(await apiFetch(`/knowledge/docs/${docId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }))
}

export async function deleteDoc(docId) {
  return asJson(await apiFetch(`/knowledge/docs/${docId}`, { method: 'DELETE' }))
}

export async function resyncDoc(docId) {
  return asJson(await apiFetch(`/knowledge/docs/${docId}/resync`, { method: 'POST' }))
}
