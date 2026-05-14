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

export async function listDocs({ meetingId } = {}) {
  const qs = meetingId ? `?meeting_id=${encodeURIComponent(meetingId)}` : ''
  const data = await asJson(await apiFetch(`/knowledge/docs${qs}`))
  return data.docs || []
}

export async function uploadFile(file, { meetingId, sensitivity = 'internal' } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (meetingId) form.append('meeting_id', meetingId)
  form.append('sensitivity', sensitivity)
  return asJson(await apiFetch('/knowledge/upload', { method: 'POST', body: form }))
}

export async function uploadUrl(url, { meetingId, sensitivity = 'internal' } = {}) {
  return asJson(await apiFetch('/knowledge/upload-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, meeting_id: meetingId, sensitivity }),
  }))
}

export async function connectSource({ sourceType, sourceId, name, meetingId, sensitivity = 'internal' }) {
  return asJson(await apiFetch('/knowledge/connect-source', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_type: sourceType, source_id: sourceId, name,
      meeting_id: meetingId, sensitivity,
    }),
  }))
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
