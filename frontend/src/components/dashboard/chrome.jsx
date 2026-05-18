// Shared dashboard-chrome helpers. Single source of truth so DashboardPage
// and DashboardSidebar don't redefine these (see CLAUDE.md — the same rule
// the backend applies to strip_fences).

export function formatHistoryDate(date) {
  if (!date) return 'Saved meeting'
  const parsed = new Date(date)
  if (Number.isNaN(parsed.getTime())) return 'Saved meeting'
  return parsed.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function IntegrationsIcon({ className = '' }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="4.25" cy="4.25" r="2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="11.75" cy="4.25" r="2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="4.25" cy="11.75" r="2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="11.75" cy="11.75" r="2" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}
