export function extractSpeakers(transcript) {
  const matches = transcript.match(/^([A-Z][a-zA-Z\s]{1,30}?):/gm) || []
  const names = [...new Set(matches.map(m => m.replace(/:$/, '').trim()))]
  return names
    .filter(n => !/^speaker\s*\d+$/i.test(n))
    .slice(0, 10)
    .map(name => ({ name, role: '' }))
}

export function getTranscriptStats(text = '') {
  const words = text.trim() ? text.trim().split(/\s+/).filter(Boolean).length : 0
  const lines = text.trim() ? text.trim().split('\n').filter(Boolean).length : 0
  return { words, lines }
}

export function countNamedSpeakers(text = '') {
  const matches = text.match(/^([A-Z][a-zA-Z\s]{1,30}?):/gm) || []
  return [...new Set(matches.map((m) => m.replace(/:$/, '').trim()))].length
}

export function hasMeaningfulResult(result) {
  if (!result || typeof result !== 'object') return false
  if (typeof result.summary === 'string' && result.summary.trim()) return true
  if (Array.isArray(result.action_items) && result.action_items.length > 0) return true
  if (Array.isArray(result.decisions) && result.decisions.length > 0) return true
  if (result.health_score?.verdict) return true
  if ((result.health_score?.score ?? 0) > 0) return true
  if (result.sentiment?.notes) return true
  if (result.follow_up_email?.subject || result.follow_up_email?.body) return true
  if (result.calendar_suggestion?.recommended || result.calendar_suggestion?.reason) return true
  return false
}

export function formatRelativeMeetingDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const diffMs = now - date
  const diffHours = Math.round(diffMs / (1000 * 60 * 60))
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24))

  if (Math.abs(diffHours) < 24) {
    return diffHours <= 0 ? 'Just now' : `${diffHours}h ago`
  }

  if (Math.abs(diffDays) < 7) {
    return diffDays <= 0 ? 'Today' : `${diffDays}d ago`
  }

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function formatMinutesUntil(start, end) {
  if (!start) return ''
  const now = new Date()
  const startDate = new Date(start)
  if (Number.isNaN(startDate.getTime())) return ''
  const mins = Math.round((startDate - now) / 60000)
  if (mins <= 0) {
    if (end) {
      const endDate = new Date(end)
      const minsLeft = Math.round((endDate - now) / 60000)
      if (minsLeft <= 0) return 'ended'
      return `in progress · ${minsLeft}m left`
    }
    return 'in progress'
  }
  if (mins < 60) return `in ${mins}m`
  const hours = Math.floor(mins / 60)
  const rem = mins % 60
  return rem ? `in ${hours}h ${rem}m` : `in ${hours}h`
}

export function buildMarkdown(result) {
  const date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  const h = result.health_score
  let md = `# Meeting Summary — ${date}\n\n`
  if (h?.score) {
    md += `## Meeting Health: ${h.score}/100 — ${h.verdict}\n`
    if (h.badges?.length) md += h.badges.map(b => `\`${b}\``).join(' ') + '\n'
    md += '\n'
  }
  if (result.summary) md += `## Summary\n\n${result.summary}\n\n`
  if (result.action_items?.length) {
    md += `## Action Items\n\n`
    result.action_items.forEach(i => {
      md += `- [ ] ${i.task}${i.owner && i.owner !== 'Unassigned' ? ` *(${i.owner})*` : ''}${i.due && i.due !== 'TBD' ? ` — due ${i.due}` : ''}\n`
    })
    md += '\n'
  }
  if (result.decisions?.length) {
    md += `## Decisions\n\n`
    result.decisions.forEach(d => {
      const imp = d.importance === 1 ? 'Critical' : d.importance === 2 ? 'Significant' : 'Minor'
      md += `- **${d.decision}**${d.owner && d.owner !== 'Team' ? ` *(${d.owner})*` : ''} — ${imp}\n`
    })
    md += '\n'
  }
  if (result.sentiment?.overall) {
    md += `## Sentiment: ${result.sentiment.overall} (${result.sentiment.score ?? 50}/100)\n\n`
    if (result.sentiment.notes) md += `${result.sentiment.notes}\n\n`
  }
  if (result.follow_up_email?.subject) {
    md += `## Follow-up Email\n\n**Subject:** ${result.follow_up_email.subject}\n\n${result.follow_up_email.body}\n\n`
  }
  if (result.calendar_suggestion?.recommended) {
    md += `## Calendar\n\n${result.calendar_suggestion.reason}`
    if (result.calendar_suggestion.suggested_timeframe) md += ` — ${result.calendar_suggestion.suggested_timeframe}`
    if (result.calendar_suggestion.resolved_day || result.calendar_suggestion.resolved_date) {
      md += ` (${[result.calendar_suggestion.resolved_day, result.calendar_suggestion.resolved_date].filter(Boolean).join(', ')})`
    }
    md += `\n`
  }
  return md
}

export function buildPrintHTML(result) {
  const date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  const h = result.health_score
  let body = `<h1>Meeting Summary — ${date}</h1>`
  if (h?.score) {
    body += `<h2>Meeting Health: ${h.score}/100 — ${h.verdict}</h2>`
    if (h.badges?.length) body += `<p>${h.badges.map(b => `<code>${b}</code>`).join(' ')}</p>`
    if (h.breakdown) body += `<ul><li>Clarity: ${h.breakdown.clarity}/100</li><li>Action Orientation: ${h.breakdown.action_orientation}/100</li><li>Engagement: ${h.breakdown.engagement}/100</li></ul>`
  }
  if (result.summary) body += `<h2>Summary</h2><p>${result.summary}</p>`
  if (result.action_items?.length) {
    body += `<h2>Action Items</h2><ul>`
    result.action_items.forEach(i => {
      body += `<li>${i.task}${i.owner && i.owner !== 'Unassigned' ? ` <em>(${i.owner})</em>` : ''}${i.due && i.due !== 'TBD' ? ` — due ${i.due}` : ''}</li>`
    })
    body += `</ul>`
  }
  if (result.decisions?.length) {
    body += `<h2>Decisions</h2><ul>`
    result.decisions.forEach(d => {
      const imp = d.importance === 1 ? 'Critical' : d.importance === 2 ? 'Significant' : 'Minor'
      body += `<li><strong>${d.decision}</strong>${d.owner && d.owner !== 'Team' ? ` <em>(${d.owner})</em>` : ''} — ${imp}</li>`
    })
    body += `</ul>`
  }
  if (result.sentiment?.overall) {
    body += `<h2>Sentiment: ${result.sentiment.overall} (${result.sentiment.score ?? 50}/100)</h2>`
    if (result.sentiment.notes) body += `<p>${result.sentiment.notes}</p>`
  }
  if (result.follow_up_email?.subject) {
    body += `<h2>Follow-up Email</h2><p><strong>Subject:</strong> ${result.follow_up_email.subject}</p><p style="white-space:pre-wrap">${result.follow_up_email.body}</p>`
  }
  if (result.calendar_suggestion?.recommended) {
    const resolvedCalendar = [result.calendar_suggestion.resolved_day, result.calendar_suggestion.resolved_date].filter(Boolean).join(', ')
    body += `<h2>Calendar</h2><p>${result.calendar_suggestion.reason}${result.calendar_suggestion.suggested_timeframe ? ` — ${result.calendar_suggestion.suggested_timeframe}` : ''}${resolvedCalendar ? ` (${resolvedCalendar})` : ''}</p>`
  }
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Meeting Summary — ${date}</title><style>
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:720px;margin:40px auto;color:#111;line-height:1.6}
    h1{font-size:1.5rem;margin-bottom:.5rem}
    h2{font-size:1.1rem;margin-top:1.5rem;margin-bottom:.5rem;border-bottom:1px solid #eee;padding-bottom:.25rem}
    ul{padding-left:1.25rem}li{margin-bottom:.25rem}
    code{background:#f0f0f0;padding:2px 6px;border-radius:3px;font-size:.85em}
    p{margin:.5rem 0}
  </style></head><body>${body}</body></html>`
}
