import { supabase } from './supabase'

export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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
    ...rest,
    headers: requestHeaders,
  })
}

