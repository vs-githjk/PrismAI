import { useState, useEffect, useCallback, useRef } from 'react'
import { supabase } from '../../lib/supabase'
import { apiFetch } from '../../lib/api'
import { notifyStatus } from '../../lib/statusNotify'
import AgentTags from '../AgentTags'
import HealthScoreCard from '../HealthScoreCard'
import SummaryCard from '../SummaryCard'
import ActionItemsCard from '../ActionItemsCard'
import DecisionsCard from '../DecisionsCard'
import SentimentCard from '../SentimentCard'
import EmailCard from './EmailCard'
import CalendarCard from './CalendarCard'
import SpeakerCoachCard from './SpeakerCoachCard'
import LiveCatchup from '../LiveCatchup'

// Collapsible pre-meeting brief shown above the live transcript while a meeting
// is in progress. Only used by LiveMeetingView, so it lives here.
function PreMeetingBrief({ brief }) {
  const [expanded, setExpanded] = useState(false)
  if (!brief) return null
  const totalCount = (brief.open_items?.length || 0) + (brief.recent_decisions?.length || 0) + (brief.blockers?.length || 0)
  if (totalCount === 0) return null
  return (
    <div className="rounded-2xl overflow-hidden cursor-pointer"
      style={{ background: 'rgba(14,165,233,0.06)', border: '1px solid rgba(14,165,233,0.2)' }}
      onClick={() => setExpanded(e => !e)}>
      <div className="px-4 py-3 flex items-center gap-2">
        <svg className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
        <span className="text-xs font-semibold text-sky-300">Pre-Meeting Brief</span>
        <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded-full text-sky-200" style={{ background: 'rgba(14,165,233,0.15)' }}>
          {totalCount} item{totalCount !== 1 ? 's' : ''}
        </span>
        <svg className={`w-3 h-3 text-sky-500 ml-auto transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
      {expanded && (
        <div className="px-4 pb-4 space-y-3" style={{ borderTop: '1px solid rgba(14,165,233,0.12)' }}>
          {brief.open_items?.length > 0 && (
            <div className="pt-3">
              <p className="text-[10px] font-semibold text-orange-400 mb-1.5">○ Open Action Items</p>
              {brief.open_items.map((item, i) => (
                <div key={i} className="flex items-start gap-1.5 mb-1">
                  <span className="text-orange-500 text-[10px] mt-0.5 flex-shrink-0">○</span>
                  <div>
                    <p className="text-[11px] text-gray-300">{item.task}</p>
                    {(item.owner || item.due || item.meeting_date) && (
                      <p className="text-[10px] text-gray-600">{[item.owner, item.due, item.meeting_date].filter(Boolean).join(' · ')}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {brief.recent_decisions?.length > 0 && (
            <div className={brief.open_items?.length > 0 ? '' : 'pt-3'}>
              <p className="text-[10px] font-semibold text-yellow-400 mb-1.5">⚖ Recent Decisions</p>
              {brief.recent_decisions.map((d, i) => (
                <div key={i} className="flex items-start gap-1.5 mb-1">
                  <span className="text-yellow-500 text-[10px] mt-0.5 flex-shrink-0">⚖</span>
                  <div>
                    <p className="text-[11px] text-gray-300">{d.decision}</p>
                    {(d.owner || d.meeting_date) && (
                      <p className="text-[10px] text-gray-600">{[d.owner, d.meeting_date].filter(Boolean).join(' · ')}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {brief.blockers?.length > 0 && (
            <div className={(!brief.open_items?.length && !brief.recent_decisions?.length) ? 'pt-3' : ''}>
              <p className="text-[10px] font-semibold text-red-400 mb-1.5">⚠ Recurring Blockers</p>
              {brief.blockers.map((b, i) => (
                <div key={i} className="flex items-start gap-1.5 mb-1">
                  <span className="text-red-500 text-[10px] mt-0.5 flex-shrink-0">⚠</span>
                  <div>
                    <p className="text-[11px] text-gray-300">{b.snippet}</p>
                    {b.meeting_date && <p className="text-[10px] text-gray-600">{b.meeting_date}</p>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * LiveMeetingView — the live-meeting surface, rendered as a dashboard sub-view
 * (activeView === 'live'). It polls /live/{token} every 3s and renders the
 * pre-meeting brief, command log, live transcript, and (when the meeting ends)
 * the full analysis with a save action.
 *
 * Chromeless by design: it renders only its content stack and lives inside the
 * dashboard's shared chrome (sidebar + topbar + status island). `onStatusChange`
 * surfaces the polled status (joining|recording|processing|done|error) up to the
 * dashboard so the status island can reflect live progress.
 */
export default function LiveMeetingView({ token, onStatusChange }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [session, setSession] = useState(null)
  const [saveState, setSaveState] = useState('idle')
  const intervalRef = useRef(null)
  const disconnectedRef = useRef(false)

  useEffect(() => {
    supabase?.auth.getSession().then(({ data: s }) => setSession(s?.session ?? null))
  }, [])

  const handleSave = async () => {
    if (saveState !== 'idle') return
    setSaveState('saving')
    const result = data?.result || {}
    try {
      await apiFetch('/meetings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: Date.now(),
          date: new Date().toISOString().slice(0, 10),
          title: result.title || result.summary?.slice(0, 80).split('.')[0] || 'Meeting',
          score: result.health_score?.score || null,
          transcript: data?.transcript || '',
          result,
          share_token: '',
        }),
      })
      setSaveState('saved')
      notifyStatus({ kind: 'success', message: 'Meeting saved' })
    } catch {
      setSaveState('error')
    }
  }

  const poll = useCallback(async () => {
    const onDisconnect = () => {
      if (!disconnectedRef.current) {
        disconnectedRef.current = true
        notifyStatus({ kind: 'reconnect', message: 'Reconnecting…' })
      }
    }
    try {
      // apiFetch sends cache:'no-store' — this endpoint is polled for live updates, so it
      // must never be served stale from the browser HTTP cache.
      const res = await apiFetch(`/live/${token}`)
      if (res.status === 404) { setError('Live session not found or has expired.'); clearInterval(intervalRef.current); return }
      if (!res.ok) { onDisconnect(); return }
      const json = await res.json()
      // Recovered from a transient network blip — let the user know.
      if (disconnectedRef.current) {
        disconnectedRef.current = false
        notifyStatus({ kind: 'reconnect', message: 'Reconnected' })
      }
      setData(json)
      if (['done', 'error'].includes(json.status)) clearInterval(intervalRef.current)
    } catch { onDisconnect() /* network blip — keep polling */ }
  }, [token])

  useEffect(() => {
    poll()
    intervalRef.current = setInterval(poll, 3000)
    return () => clearInterval(intervalRef.current)
  }, [poll])

  const status = data?.status
  const commands = data?.commands || []
  const lines = data?.transcript_lines || []
  const result = data?.result || {}
  const standinUpdates = data?.standin_updates || []

  // Surface the live status up to the dashboard (status island).
  useEffect(() => {
    onStatusChange?.(error ? 'error' : status || null)
  }, [status, error, onStatusChange])

  if (error) return (
    <div className="mx-auto max-w-2xl py-16 text-center">
      <p className="text-sm text-white/50">{error}</p>
    </div>
  )

  if (!data) return (
    <div className="mx-auto flex max-w-2xl flex-col items-center gap-3 py-16">
      <div className="w-8 h-8 rounded-xl flex items-center justify-center animate-pulse" style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
        <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
      </div>
      <p className="text-xs text-white/40">Connecting to live meeting…</p>
    </div>
  )

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      {/* Live status (joining/recording/processing/done) is reflected by the
          topbar status island via onStatusChange — no in-content pill needed. */}
      {status === 'recording' && (
        <LiveCatchup liveToken={token} accessToken={session?.access_token || null} />
      )}
      {standinUpdates.length > 0 && (
        <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(34,211,238,0.14)' }}>
          <div className="px-4 py-2.5 flex items-center gap-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <span className="text-xs">📋</span>
            <span className="text-xs font-semibold text-cyan-200">Stand-in updates</span>
            <span className="ml-auto text-[10px] text-gray-600">{standinUpdates.length}</span>
          </div>
          <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,0.04)' }}>
            {standinUpdates.map((u, i) => (
              <div key={i} className="px-4 py-2.5">
                <p className="text-[11px] font-semibold text-cyan-300/80">{u.name} · couldn’t attend</p>
                <p className="text-[12px] text-gray-300 mt-0.5 leading-relaxed">{u.body}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      {status !== 'done' && <PreMeetingBrief brief={data?.brief} />}
      {/* Prism commands log */}
      {commands.length > 0 && (
        <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)' }}>
          <div className="px-4 py-2.5 flex items-center gap-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <svg className="w-3.5 h-3.5 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
            <span className="text-xs font-semibold text-violet-300">Prism Commands</span>
            <span className="ml-auto text-[10px] text-gray-600">{commands.length}</span>
          </div>
          <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,0.04)' }}>
            {commands.map((cmd, i) => (
              <div key={i} className="px-4 py-3">
                <div className="flex items-start gap-2">
                  <svg className="w-3 h-3 text-emerald-400 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-gray-200">"{cmd.command}"</p>
                    {cmd.speaker && <p className="text-[10px] text-gray-600 mt-0.5">{cmd.speaker}{cmd.tools?.length ? ` · ${cmd.tools.join(', ')}` : ''}</p>}
                    {cmd.reply && <p className="text-[11px] text-gray-400 mt-1 leading-relaxed">{cmd.reply}</p>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Live transcript */}
      {lines.length > 0 && status !== 'done' && (
        <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)' }}>
          <div className="px-4 py-2.5 flex items-center gap-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
            <span className="text-xs font-semibold text-gray-400">Live Transcript</span>
          </div>
          <div className="px-4 py-3 max-h-64 overflow-y-auto space-y-1">
            {lines.slice(-30).map((line, i) => (
              <p key={i} className="text-[11px] text-gray-400 leading-relaxed">{line}</p>
            ))}
          </div>
        </div>
      )}

      {/* Full results when done */}
      {status === 'done' && result && (
        <>
          {result.agents_run?.length > 0 && <AgentTags agents={result.agents_run} />}
          <HealthScoreCard healthScore={result.health_score} />
          <SummaryCard summary={result.summary} />
          <ActionItemsCard actionItems={result.action_items} readOnly />
          <DecisionsCard decisions={result.decisions} />
          {result.sentiment && <SentimentCard sentiment={result.sentiment} />}
          <EmailCard email={result.follow_up_email} readOnly />
          <CalendarCard suggestion={result.calendar_suggestion} readOnly />
          <SpeakerCoachCard speakerCoach={result.speaker_coach} />
          {session && (
            <button
              onClick={handleSave}
              disabled={saveState !== 'idle'}
              className="w-full py-2.5 rounded-xl text-sm font-semibold transition-all hover:scale-[1.02] disabled:opacity-60 disabled:cursor-not-allowed"
              style={{ background: 'linear-gradient(135deg, rgba(2,132,199,0.25), rgba(13,148,136,0.2))', border: '1px solid rgba(14,165,233,0.35)', color: '#7dd3fc' }}>
              {saveState === 'idle' && 'Save to my history'}
              {saveState === 'saving' && 'Saving…'}
              {saveState === 'saved' && '✓ Saved'}
              {saveState === 'error' && 'Save failed — try again'}
            </button>
          )}
        </>
      )}

      {status === 'processing' && (
        <div className="flex items-center gap-3 px-4 py-4 rounded-2xl" style={{ background: 'rgba(14,165,233,0.06)', border: '1px solid rgba(14,165,233,0.15)' }}>
          <svg className="w-4 h-4 text-sky-400 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
          <p className="text-xs text-sky-300">Meeting ended — running analysis across 7 agents…</p>
        </div>
      )}

      {status === 'error' && data.error && (
        <div className="px-4 py-3 rounded-2xl" style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)' }}>
          <p className="text-xs text-red-400">{data.error}</p>
        </div>
      )}

      {!commands.length && !lines.length && ['joining', 'recording'].includes(status) && (
        <div className="text-center py-12">
          <div className="w-10 h-10 rounded-2xl mx-auto mb-3 flex items-center justify-center animate-pulse" style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.15)' }}>
            <svg className="w-5 h-5 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" /></svg>
          </div>
          <p className="text-xs text-gray-600">Waiting for conversation…</p>
          <p className="text-[10px] text-gray-700 mt-1">Commands and transcript will appear here as the meeting progresses.</p>
        </div>
      )}
    </div>
  )
}
