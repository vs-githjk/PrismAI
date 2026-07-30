// Web Push subscription helpers for the #9 meeting_soon reminder.
// The server issues the VAPID public key; we register the service worker,
// request permission, subscribe, and hand the subscription to the backend.

import { apiFetch } from './api'

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const arr = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i += 1) arr[i] = raw.charCodeAt(i)
  return arr
}

export function pushSupported() {
  return (
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

// 'unsupported' | 'denied' | 'subscribed' | 'default'
export async function getPushState() {
  if (!pushSupported()) return 'unsupported'
  if (Notification.permission === 'denied') return 'denied'
  try {
    const reg = await navigator.serviceWorker.getRegistration()
    const sub = reg && (await reg.pushManager.getSubscription())
    return sub ? 'subscribed' : 'default'
  } catch {
    return 'default'
  }
}

export async function subscribePush() {
  if (!pushSupported()) return false
  try {
    const keyRes = await apiFetch('/notifications/push/key')
    if (!keyRes.ok) return false
    const { public_key: publicKey } = await keyRes.json()
    if (!publicKey) return false

    const reg = await navigator.serviceWorker.register('/sw.js')
    await navigator.serviceWorker.ready

    const perm = await Notification.requestPermission()
    if (perm !== 'granted') return false

    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    })
    const json = sub.toJSON()
    const res = await apiFetch('/notifications/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }),
    })
    return res.ok
  } catch (e) {
    return false
  }
}

export async function unsubscribePush() {
  if (!pushSupported()) return
  try {
    const reg = await navigator.serviceWorker.getRegistration()
    const sub = reg && (await reg.pushManager.getSubscription())
    if (sub) {
      const json = sub.toJSON()
      await apiFetch('/notifications/push/unsubscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }),
      })
      await sub.unsubscribe()
    }
  } catch {
    /* ignore */
  }
}
