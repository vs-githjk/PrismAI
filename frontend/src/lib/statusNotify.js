import { useEffect, useState } from 'react'

/**
 * statusNotify — a tiny fire-and-forget pub/sub for transient StatusIsland
 * notifications. Any success handler (in App.jsx or deep in a component) can call
 * `notifyStatus({ kind, message })` without threading a setter through props.
 *
 * The island treats a notification as a transient state that PREEMPTS the base
 * derived state for ~2.5s, then reverts (interrupt-and-revert, per the plan). A
 * new notification replaces the current one and restarts the timer.
 *
 * `kind` selects the leading icon in the island (see StatusIsland NOTIFY_ICONS):
 *   success | bot | calendar | send | doc | team | reconnect
 */

const NOTIFY_MS = 2500

let current = null
let timer = null
const subscribers = new Set()

function emit() {
  for (const fn of subscribers) fn(current)
}

export function notifyStatus(notification) {
  if (!notification?.message) return
  current = { kind: 'success', ...notification }
  emit()
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    current = null
    timer = null
    emit()
  }, notification.duration || NOTIFY_MS)
}

// Subscribe a React component to the current notification (null when none).
export function useStatusNotification() {
  const [n, setN] = useState(current)
  useEffect(() => {
    subscribers.add(setN)
    return () => subscribers.delete(setN)
  }, [])
  return n
}
