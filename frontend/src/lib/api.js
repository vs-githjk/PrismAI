import { supabase } from './supabase'

export const API = import.meta.env.VITE_API_URL || 'http://localhost:8001'

export async function getAccessToken() {
  if (!supabase) return null
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token || null
}

export async function apiFetch(path, options = {}) {
  const { skipAuth = false, headers, ...rest } = options
  const requestHeaders = new Headers(headers || {})

  if (!skipAuth) {
    const token = await getAccessToken()
    if (token) requestHeaders.set('Authorization', `Bearer ${token}`)
  }

  return fetch(`${API}${path}`, {
    // Authed API reads must never be served from the browser HTTP cache: a stale
    // /meetings response would keep showing an out-of-date meeting after a backend
    // change (or another account's data) until the cache is manually cleared. Default
    // to no-store; a caller can override via options.cache if it ever needs caching.
    cache: 'no-store',
    ...rest,
    headers: requestHeaders,
  })
}

