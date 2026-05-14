import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Bolt,
  BookOpen,
  Brain,
  Copy,
  DoorOpen,
  Download,
  FileText,
  History,
  LayoutDashboard,
  MessageSquare,
  MessagesSquare,
  Plus,
  Search,
  Share2,
  Trash2,
  UserCircle,
  X,
} from 'lucide-react'
import { glassCard, cardGlowStyle } from './dashboard/dashboardStyles'
import { apiFetch } from '../lib/api'
import { deriveDisplayTitle } from '../lib/insights'
import DotField from './DotField'
import LogoIcon from './LogoIcon'
import StatsCanvas from './dashboard/StatsCanvas'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from './ui/dialog'
import SkeletonCard from './SkeletonCard'
import { UI_SCREEN_KEY } from '../lib/sessionKeys'

const MeetingView = lazy(() => import('./dashboard/MeetingView'))
const IntelligenceView = lazy(() => import('./dashboard/IntelligenceView'))
const ChatPanel = lazy(() => import('./ChatPanel'))
const UpcomingMeetings = lazy(() => import('./UpcomingMeetings'))

const secondaryButtonClass = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-white/[0.16] bg-[#151515] px-4 text-sm font-semibold text-white/86 transition hover:border-white/[0.24] hover:bg-[#1d1d1d] hover:text-white'
const eyebrowClass = 'text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-200/90'
const darkCircleButtonClass = 'flex items-center justify-center rounded-full border border-[#2f2f2f] bg-[#18181b] text-[#f2f2f2] shadow-xl transition-all hover:bg-[#27272a] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan-300/18 data-[state=open]:bg-[#27272a]'

function formatHistoryDate(date) {
  if (!date) return 'Saved meeting'
  const parsed = new Date(date)
  if (Number.isNaN(parsed.getTime())) return 'Saved meeting'
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function IntegrationsIcon({ className = '' }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="4.25" cy="4.25" r="2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="11.75" cy="4.25" r="2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="4.25" cy="11.75" r="2" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="11.75" cy="11.75" r="2" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

function MeetingActionsBar({
  shareToken,
  shareCopied,
  setShareCopied,
  mdCopied,
  copyMarkdown,
  exportMarkdown,
  exportPDF,
  exportToSlack,
  exportToNotion,
  exportingSlack,
  exportingNotion,
  integrations,
}) {
  const handleShare = () => {
    if (!shareToken) return
    const url = `${window.location.origin}${window.location.pathname}#share/${shareToken}`
    navigator.clipboard.writeText(url).then(() => {
      setShareCopied(true)
      setTimeout(() => setShareCopied(false), 2000)
    })
  }

  const itemClass = 'cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-white/84 focus:bg-cyan-300/[0.08]'
  const connectItemClass = 'cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-cyan-300 focus:bg-cyan-300/[0.12]'
  const iconClass = 'h-4 w-4 shrink-0 text-white/62'
  const connectIconClass = 'h-4 w-4 shrink-0 text-cyan-300'

  const slackConnected = !!integrations?.slack_webhook
  const notionConnected = !!(integrations?.notion_token && integrations?.notion_page_id)

  return (
    <div className="mb-3 flex items-center justify-end gap-2">
      {shareToken && (
        <button
          type="button"
          onClick={handleShare}
          className={secondaryButtonClass}
          style={shareCopied ? { borderColor: 'rgba(34,211,238,0.45)', color: '#67e8f9' } : undefined}
          aria-label="Copy share link"
        >
          <Share2 className="h-4 w-4" aria-hidden="true" />
          {shareCopied ? 'Copied!' : 'Share'}
        </button>
      )}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button type="button" className={secondaryButtonClass} aria-label="Export meeting">
            <Download className="h-4 w-4" aria-hidden="true" />
            Export
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="dashboard-body-font w-56 rounded-xl border-[#2f2f2f] bg-[#0b0b0b] p-1.5"
        >
          <DropdownMenuItem onSelect={() => copyMarkdown()} className={itemClass}>
            <Copy className={iconClass} aria-hidden="true" />
            {mdCopied ? 'Copied!' : 'Copy markdown'}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => exportMarkdown()} className={itemClass}>
            <Download className={iconClass} aria-hidden="true" />
            Download .md
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => exportPDF()} className={itemClass}>
            <FileText className={iconClass} aria-hidden="true" />
            Open print view
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            disabled={exportingSlack}
            onSelect={() => exportToSlack()}
            className={slackConnected ? itemClass : connectItemClass}
          >
            <MessageSquare className={slackConnected ? iconClass : connectIconClass} aria-hidden="true" />
            {exportingSlack ? 'Sending…' : slackConnected ? 'Send to Slack' : 'Connect Slack →'}
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={exportingNotion}
            onSelect={() => exportToNotion()}
            className={notionConnected ? itemClass : connectItemClass}
          >
            <BookOpen className={notionConnected ? iconClass : connectIconClass} aria-hidden="true" />
            {exportingNotion ? 'Sending…' : notionConnected ? 'Send to Notion' : 'Connect Notion →'}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function AnalyzeButton({ loading, handleAnalyzeClick, cancelActiveAnalysis, transcript }) {
  if (loading) {
    return (
      <button type="button" onClick={cancelActiveAnalysis} className="w-full rounded-full border border-white/[0.10] py-2.5 text-sm font-semibold text-white/60 transition hover:bg-white/[0.05]">
        Analyzing… (cancel)
      </button>
    )
  }
  return (
    <button
      type="button"
      onClick={handleAnalyzeClick}
      disabled={!transcript}
      className="w-full rounded-full bg-cyan-400 py-2.5 text-sm font-semibold text-[#07040f] transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-40"
    >
      Analyze Meeting
    </button>
  )
}

function NewMeetingPanel(props) {
  const activeTab = props.isTestAccount && props.inputTab === 'join' ? 'paste' : (props.inputTab || 'paste')
  const botActive = props.botStatus && !['done', 'error'].includes(props.botStatus)

  return (
    <div className="dashboard-body-font w-full overflow-hidden rounded-2xl">
      <div className="flex items-center justify-between px-4 pb-3 pt-3.5">
        <p className="text-[13px] font-semibold text-white/90">New Meeting</p>
        <button
          type="button"
          onClick={props.onClose}
          className="flex h-6 w-6 items-center justify-center rounded-full text-white/40 transition hover:bg-white/[0.07] hover:text-white/70"
          aria-label="Close"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <Tabs value={activeTab} onValueChange={props.setInputTab} className="w-full">
        <div className="px-4 pb-3">
          <TabsList className="w-full">
            <TabsTrigger value="paste" className="flex-1">Paste</TabsTrigger>
            {props.micSupported && <TabsTrigger value="record" className="flex-1">Record</TabsTrigger>}
            <TabsTrigger value="upload" className="flex-1">Upload</TabsTrigger>
            {!props.isTestAccount && <TabsTrigger value="join" className="flex-1">Join</TabsTrigger>}
          </TabsList>
        </div>

        <div className="px-4 pb-4">
          <TabsContent value="paste">
            <div className="space-y-3">
              <textarea
                value={props.transcript || ''}
                onChange={(e) => props.setTranscriptForTab(e.target.value, 'paste')}
                placeholder="Paste your meeting transcript here..."
                rows={7}
                className="w-full resize-none rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 text-sm text-white/90 outline-none placeholder:text-white/28 focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/20"
              />
              {props.transcriptStats?.words > 0 && (
                <p className="text-[10.5px] text-white/38">
                  {props.transcriptStats.words} words · {props.transcriptSpeakerCount || 0} speaker{props.transcriptSpeakerCount !== 1 ? 's' : ''}
                </p>
              )}
              <AnalyzeButton {...props} />
            </div>
          </TabsContent>

          {props.micSupported && (
            <TabsContent value="record">
              <div className="space-y-3">
                <button
                  type="button"
                  onClick={props.recording ? props.stopRecording : props.startRecording}
                  className={`w-full rounded-xl border px-4 py-2.5 text-sm font-semibold transition ${
                    props.recording
                      ? 'border-red-400/30 bg-red-400/[0.09] text-red-300 hover:bg-red-400/[0.13]'
                      : 'border-white/[0.10] bg-white/[0.05] text-white/80 hover:bg-white/[0.08]'
                  }`}
                >
                  {props.recording ? '⏹ Stop Recording' : '⏺ Start Recording'}
                </button>
                {props.transcript && (
                  <textarea
                    value={props.transcript}
                    onChange={(e) => props.setTranscriptForTab(e.target.value, 'record')}
                    rows={5}
                    className="w-full resize-none rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 text-sm text-white/90 outline-none"
                  />
                )}
                {props.transcriptStats?.words > 0 && (
                  <p className="text-[10.5px] text-white/38">{props.transcriptStats.words} words</p>
                )}
                {props.transcript && <AnalyzeButton {...props} />}
              </div>
            </TabsContent>
          )}

          <TabsContent value="upload">
            <div className="space-y-3">
              <input
                ref={props.fileInputRef}
                type="file"
                accept="audio/*,.mp3,.wav,.m4a,.ogg,.webm"
                className="hidden"
                onChange={props.handleAudioUpload}
              />
              <button
                type="button"
                onClick={() => props.fileInputRef?.current?.click()}
                disabled={props.transcribing}
                className="w-full rounded-xl border border-white/[0.10] bg-white/[0.05] px-4 py-2.5 text-sm font-semibold text-white/80 transition hover:bg-white/[0.08] disabled:opacity-50"
              >
                {props.transcribing ? '⏳ Transcribing…' : '📎 Choose Audio File'}
              </button>
              {props.transcript && (
                <>
                  <textarea
                    value={props.transcript}
                    onChange={(e) => props.setTranscriptForTab(e.target.value, 'upload')}
                    rows={5}
                    className="w-full resize-none rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 text-sm text-white/90 outline-none"
                  />
                  {props.transcriptStats?.words > 0 && (
                    <p className="text-[10.5px] text-white/38">{props.transcriptStats.words} words</p>
                  )}
                  <AnalyzeButton {...props} />
                </>
              )}
            </div>
          </TabsContent>

          <TabsContent value="join">
            <div className="space-y-3">
              {props.calendarConnected && props.user && !props.isTestAccount && (
                <Suspense fallback={null}>
                  <UpcomingMeetings onJoin={(url) => props.setMeetingUrl(url)} />
                </Suspense>
              )}
              <input
                type="url"
                value={props.meetingUrl || ''}
                onChange={(e) => props.setMeetingUrl(e.target.value)}
                placeholder="Paste Zoom / Meet / Teams link..."
                disabled={botActive}
                className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 text-sm text-white/90 outline-none placeholder:text-white/28 focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/20 disabled:opacity-50"
              />

              {botActive && (
                <div className="flex items-center gap-2 rounded-xl border border-white/[0.06] bg-white/[0.04] px-3 py-2">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" />
                  <p className="text-xs text-white/70">
                    {props.botStatus === 'joining' ? 'Bot is joining the meeting…' :
                     props.botStatus === 'recording' ? 'Bot is recording…' :
                     'Meeting ended — analyzing…'}
                  </p>
                  <button type="button" onClick={props.cancelBot} className="ml-auto text-[10px] text-white/36 hover:text-white/60">
                    Cancel
                  </button>
                </div>
              )}

              {props.liveCommands?.length > 0 && (
                <div className="max-h-28 space-y-1 overflow-y-auto">
                  {props.liveCommands.slice(-5).map((cmd, i) => (
                    <div key={i} className="rounded-lg border border-white/[0.05] bg-white/[0.03] px-3 py-1.5">
                      <p className="text-[10.5px] font-semibold text-cyan-300/80">{cmd.speaker || 'Prism'}</p>
                      <p className="text-[11px] text-white/60">{cmd.reply || cmd.command}</p>
                    </div>
                  ))}
                </div>
              )}

              {props.botError && (
                <p className="rounded-xl border border-red-400/20 bg-red-400/[0.07] px-3 py-2 text-xs text-red-300">{props.botError}</p>
              )}

              {props.botStatus === 'done' && props.result && (
                <p className="text-center text-xs font-semibold text-cyan-300">✓ Analysis complete — view results above</p>
              )}
              {props.botStatus === 'done' && props.botTranscriptReady && !props.result && (
                <button
                  type="button"
                  onClick={() => { props.setInputTab('paste'); props.handleAnalyzeClick() }}
                  className="w-full rounded-xl bg-cyan-400/[0.12] py-2 text-xs font-semibold text-cyan-300 hover:bg-cyan-400/[0.18]"
                >
                  Transcript ready — analyze now
                </button>
              )}

              <button
                type="button"
                onClick={props.joinMeeting}
                disabled={!props.meetingUrl || botActive}
                className="w-full rounded-full bg-cyan-400 py-2.5 text-sm font-semibold text-[#07040f] transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {props.botStatus === 'joining' ? 'Joining…' :
                 props.botStatus === 'recording' ? 'Recording…' :
                 props.botStatus === 'processing' ? 'Processing…' :
                 'Join Meeting'}
              </button>
            </div>
          </TabsContent>
        </div>
      </Tabs>
    </div>
  )
}

const ANALYZING_AGENTS = [
  { id: 'summarizer',         label: 'Summary',   icon: '📝', done: 'bg-red-500/20 border-red-500/40 text-red-300',           dot: 'bg-red-400' },
  { id: 'action_items',       label: 'Actions',   icon: '✅', done: 'bg-orange-500/20 border-orange-500/40 text-orange-300',   dot: 'bg-orange-400' },
  { id: 'decisions',          label: 'Decisions', icon: '⚖️', done: 'bg-yellow-500/20 border-yellow-500/40 text-yellow-200',   dot: 'bg-yellow-400' },
  { id: 'sentiment',          label: 'Sentiment', icon: '💬', done: 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300', dot: 'bg-emerald-400' },
  { id: 'email_drafter',      label: 'Email',     icon: '✉️', done: 'bg-blue-500/20 border-blue-500/40 text-blue-300',         dot: 'bg-blue-400' },
  { id: 'calendar_suggester', label: 'Calendar',  icon: '📅', done: 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300',   dot: 'bg-indigo-400' },
  { id: 'health_score',       label: 'Health',    icon: '📊', done: 'bg-violet-500/20 border-violet-500/40 text-violet-300',   dot: 'bg-violet-400' },
  { id: 'speaker_coach',      label: 'Coach',     icon: '🎤', done: 'bg-rose-500/20 border-rose-500/40 text-rose-300',         dot: 'bg-rose-400' },
]

function MeetingViewSkeleton() {
  return (
    <div className="space-y-3">
      <div className="space-y-2 px-0.5">
        <div className="h-2 w-20 animate-pulse rounded-full bg-white/[0.06]" />
        <div className="h-7 w-56 animate-pulse rounded-xl bg-white/[0.08]" style={{ animationDelay: '60ms' }} />
        <div className="h-2 w-28 animate-pulse rounded-full bg-white/[0.05]" style={{ animationDelay: '120ms' }} />
      </div>
      <div className="grid gap-3 lg:grid-cols-[minmax(280px,1fr)_minmax(0,2fr)]">
        <SkeletonCard lines={3} />
        <SkeletonCard lines={5} />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <SkeletonCard lines={3} />
        <SkeletonCard lines={3} />
      </div>
      <SkeletonCard lines={1} />
      <SkeletonCard lines={5} />
      <SkeletonCard lines={2} />
      <SkeletonCard lines={4} />
    </div>
  )
}

function AnalyzingBanner({ result }) {
  const agentsRun = result?.agents_run || []
  const doneCount = agentsRun.length

  return (
    <div className="mb-3 overflow-hidden rounded-2xl border border-cyan-400/[0.18]" style={{ background: 'rgba(34,211,238,0.04)' }}>
      <div className="prism-spectrum-bar h-0.5 w-full" />
      <div className="p-4">
        <div className="mb-3 flex items-center gap-2.5">
          <span className="h-2 w-2 flex-shrink-0 animate-pulse rounded-full bg-cyan-400" />
          <p className="text-sm font-semibold text-white">Prism is analyzing your meeting</p>
          <span className="ml-auto text-[11px] text-white/38">{doneCount} / {ANALYZING_AGENTS.length}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {ANALYZING_AGENTS.map((agent) => {
            const isDone = agentsRun.includes(agent.id)
            return (
              <div
                key={agent.id}
                className={`flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-medium transition-all duration-300 ${
                  isDone ? agent.done : 'animate-pulse border-white/[0.09] bg-white/[0.04] text-white/38'
                }`}
              >
                <span className="text-sm leading-none">{agent.icon}</span>
                {agent.label}
                <span className={`h-1.5 w-1.5 rounded-full ${isDone ? agent.dot : 'bg-white/20'}`} />
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default function DashboardPage(props) {
  const [profileMenuOpen, setProfileMenuOpen] = useState(false)
  const [profileMenuPinned, setProfileMenuPinned] = useState(false)
  const [historySearchOpen, setHistorySearchOpen] = useState(false)
  const [newMeetingOpen, setNewMeetingOpen] = useState(false)
  const [activeView, setActiveView] = useState(
    () => sessionStorage.getItem('prism_last_meeting_id') ? 'meeting' : 'home'
  )
  const [showGateDialog, setShowGateDialog] = useState(false)

  const historyCount = props.history?.length || 0
  const profileCloseTimer = useRef(null)
  const profileAreaRef = useRef(null)
  const profileContentRef = useRef(null)
  const historySearchInputRef = useRef(null)
  const profileTriggerHovered = useRef(false)
  const profileContentHovered = useRef(false)
  const isFirstRender = useRef(true)
  const userSelectedMeetingRef = useRef(false)

  // --- Chat panel state ---
  const [chatOpen, setChatOpen] = useState(() => {
    try { return localStorage.getItem('prismai:dashboard-chat-open') === '1' } catch { return false }
  })
  const [isNarrow, setIsNarrow] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia('(max-width: 1023px)').matches
  })
  const [pastSessions, setPastSessions] = useState([])
  const pendingFlushesRef = useRef(new Map()) // meetingId → in-flight POST promise

  useEffect(() => {
    try { localStorage.setItem('prismai:dashboard-chat-open', chatOpen ? '1' : '0') } catch { /* ignore */ }
  }, [chatOpen])

  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const mql = window.matchMedia('(max-width: 1023px)')
    const handler = (e) => setIsNarrow(e.matches)
    mql.addEventListener?.('change', handler)
    return () => mql.removeEventListener?.('change', handler)
  }, [])

  useEffect(() => {
    if (!chatOpen) return undefined
    const handler = (e) => { if (e.key === 'Escape') setChatOpen(false) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [chatOpen])

  // Fetch up to 3 past chat sessions for this meeting on entry. If there's a pending
  // exit-save POST for the same meeting, wait for it first so the fetch sees the new row.
  useEffect(() => {
    if (!props.meetingId || !props.user) { setPastSessions([]); return undefined }
    let cancelled = false
    const meetingId = props.meetingId
    const pending = pendingFlushesRef.current.get(meetingId)
    Promise.resolve(pending).then(() => (
      apiFetch(`/chat-sessions/${meetingId}`)
        .then((res) => (res.ok ? res.json() : { sessions: [] }))
        .then((data) => { if (!cancelled) setPastSessions(data.sessions || []) })
        .catch(() => { if (!cancelled) setPastSessions([]) })
    ))
    return () => { cancelled = true }
  }, [props.meetingId, props.user])

  // Called from ChatPanel's unmount cleanup. Captures the unmounting panel's own meetingId,
  // so it works correctly when meetingId changes (the new ChatPanel has already mounted).
  const handleChatCommitOnExit = useCallback((mid, finalMessages) => {
    if (!props.user || !mid) return
    if (!finalMessages.some((m) => m.role === 'user')) return
    const flush = apiFetch(`/chat-sessions/${mid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: finalMessages }),
    }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
    pendingFlushesRef.current.set(mid, flush)
    flush.finally(() => {
      if (pendingFlushesRef.current.get(mid) === flush) {
        pendingFlushesRef.current.delete(mid)
      }
      // If user is still viewing the same meeting, refresh the per-meeting history
      if (props.meetingId === mid) {
        apiFetch(`/chat-sessions/${mid}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((data) => { if (data) setPastSessions(data.sessions || []) })
          .catch(() => {})
      }
    })
  }, [props.user, props.meetingId])

  // Switch to meeting view immediately when analysis starts
  useEffect(() => {
    if (props.loading) setActiveView('meeting')
  }, [props.loading])

  // Auto-switch to meeting view when a new result is loaded (not on initial mount)
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false
      return
    }
    const latest = props.history?.[0]
    const showingLatestSample =
      props.isTestAccount &&
      props.history?.length >= 2 &&
      props.meetingId === latest?.id &&
      String(latest?.share_token || '').startsWith('sample')
    if (props.result) {
      setActiveView(showingLatestSample && !userSelectedMeetingRef.current ? 'home' : 'meeting')
      userSelectedMeetingRef.current = false
    }
  }, [props.result, props.isTestAccount, props.meetingId, props.history])

  useEffect(() => {
    if (props.isTestAccount && props.inputTab === 'join') {
      props.setInputTab?.('paste')
    }
  }, [props.isTestAccount, props.inputTab, props.setInputTab])

  useEffect(() => {
    if (!profileMenuOpen) return undefined

    function handlePointerMove(event) {
      const rects = [
        profileAreaRef.current?.getBoundingClientRect(),
        profileContentRef.current?.getBoundingClientRect(),
      ].filter(Boolean)

      if (rects.length === 0) return

      const buffer = 28
      const isNearProfileMenu = rects.some((rect) => (
        event.clientX >= rect.left - buffer &&
        event.clientX <= rect.right + buffer &&
        event.clientY >= rect.top - buffer &&
        event.clientY <= rect.bottom + buffer
      ))

      if (!isNearProfileMenu) {
        setProfileMenuPinned(false)
        setProfileMenuOpen(false)
      }
    }

    window.addEventListener('pointermove', handlePointerMove)
    return () => window.removeEventListener('pointermove', handlePointerMove)
  }, [profileMenuOpen])

  useEffect(() => {
    if (!props.showHistory) setHistorySearchOpen(false)
  }, [props.showHistory])

  useEffect(() => {
    if (props.showHistory && historySearchOpen) {
      historySearchInputRef.current?.focus()
    }
  }, [historySearchOpen, props.showHistory])

  const filteredHistory = useMemo(() => {
    const query = `${props.historySearch || ''}`.trim().toLowerCase()
    const entries = props.history || []
    if (!query) return entries

    return entries.filter((entry) => {
      const result = entry?.result || {}
      const actionItems = (result.action_items || [])
        .map((item) => [item.task, item.owner, item.due].filter(Boolean).join(' '))
        .join(' ')
      const decisions = (result.decisions || [])
        .map((item) => [item.decision, item.owner].filter(Boolean).join(' '))
        .join(' ')
      const searchable = [
        entry?.title,
        entry?.transcript,
        formatHistoryDate(entry?.date),
        result.summary,
        result.health_score?.verdict,
        result.sentiment?.overall,
        result.sentiment?.notes,
        actionItems,
        decisions,
      ].filter(Boolean).join(' ').toLowerCase()

      return searchable.includes(query)
    })
  }, [props.history, props.historySearch])

  function openProfileMenu() {
    if (profileCloseTimer.current) {
      clearTimeout(profileCloseTimer.current)
      profileCloseTimer.current = null
    }
    setProfileMenuOpen(true)
  }

  function closeProfileMenuSoon() {
    if (profileMenuPinned) return
    if (profileCloseTimer.current) clearTimeout(profileCloseTimer.current)
    profileCloseTimer.current = setTimeout(() => {
      if (profileTriggerHovered.current || profileContentHovered.current) return
      setProfileMenuOpen(false)
      profileCloseTimer.current = null
    }, 120)
  }

  function toggleProfileMenuPinned(event) {
    event.preventDefault()
    setProfileMenuPinned((isPinned) => {
      const nextPinned = !isPinned
      setProfileMenuOpen(nextPinned)
      return nextPinned
    })
  }

  function handleHistorySearchChange(event) {
    props.setHistorySearch?.(event.target.value)
  }

  function toggleHistorySearch() {
    setHistorySearchOpen((open) => {
      if (open) props.setHistorySearch?.('')
      return !open
    })
  }

  function handleDeleteHistoryEntry(entry) {
    props.setHistory?.((prev) => prev.filter((item) => item.id !== entry.id))
    if (!props.isTestAccount) {
      props.apiFetch?.(`/meetings/${entry.id}`, { method: 'DELETE' }).catch(() => {})
    }
    if (entry.id === props.meetingId) {
      sessionStorage.setItem('prism_new_meeting', '1')
      props.clearWorkspaceState?.()
      setActiveView('home')
    }
  }

  function handleSelectHistoryEntry(entry) {
    props.setShowHistory?.(false)
    props.loadFromHistory?.(entry)
  }

  // Wrapped handler: load meeting AND switch to meeting view
  function handleSelectMeeting(entry) {
    userSelectedMeetingRef.current = true
    props.setShowHistory?.(false)
    props.loadFromHistory?.(entry)
    setActiveView('meeting')
  }

  function handleSwitchView() {
    if (activeView === 'intelligence') {
      setActiveView(props.result ? 'meeting' : 'home')
    } else {
      if (historyCount < 2) {
        setShowGateDialog(true)
      } else {
        setActiveView('intelligence')
      }
    }
  }

  // Find the currently loaded meeting metadata (for MeetingView title/date)
  const currentMeeting = useMemo(
    () => (props.meetingId ? (props.history || []).find((m) => m.id === props.meetingId) || null : null),
    [props.meetingId, props.history],
  )

  const inIntelligence = activeView === 'intelligence'

  return (
    <div className="landing-page dashboard-page min-h-dvh overflow-x-hidden text-[color:var(--landing-text)]">
      <div className="dashboard-dot-field-bg" aria-hidden="true">
        <div className="dashboard-dot-field-frame">
          <DotField
            dotRadius={3}
            dotSpacing={14}
            cursorRadius={250}
            cursorForce={0.1}
            bulgeOnly
            bulgeStrength={67}
            glowRadius={80}
            sparkle={false}
            waveAmplitude={0}
            gradientFrom="#0071dc"
            gradientTo="#000000"
            glowColor="#120F17"
          />
        </div>
      </div>

      <header className="sticky top-0 z-30 bg-transparent px-6 py-4 sm:px-7">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                sessionStorage.setItem(UI_SCREEN_KEY, 'landing')
                window.location.href = '/'
              }}
              className="logo-btn flex items-center gap-2"
              aria-label="Back to landing page"
            >
              <LogoIcon className="h-11 w-11" />
              <span className="prism-logo-text text-2xl font-light tracking-wider" data-text="prism">prism</span>
            </button>
          </div>

          <div className="flex items-center gap-2">
            {props.authReady && props.user ? (
              <div ref={profileAreaRef}>
                <DropdownMenu
                  modal={false}
                  open={profileMenuOpen}
                  onOpenChange={(open) => {
                    if (!open && (profileMenuPinned || profileTriggerHovered.current || profileContentHovered.current)) return
                    setProfileMenuOpen(open)
                    if (!open) setProfileMenuPinned(false)
                  }}
                >
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      onPointerEnter={() => {
                        profileTriggerHovered.current = true
                        openProfileMenu()
                      }}
                      onPointerLeave={() => {
                        profileTriggerHovered.current = false
                        closeProfileMenuSoon()
                      }}
                      onPointerDown={toggleProfileMenuPinned}
                      className={`${darkCircleButtonClass} h-9 w-9 shadow-[0_10px_28px_rgba(0,0,0,0.3)]`}
                      aria-label="Open profile menu"
                    >
                      <UserCircle className="h-5.5 w-5.5" aria-hidden="true" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    ref={profileContentRef}
                    align="end"
                    className="dashboard-body-font w-52 rounded-xl border-[#2f2f2f] bg-[#0b0b0b] p-1.5"
                    onPointerEnter={() => {
                      profileContentHovered.current = true
                      openProfileMenu()
                    }}
                    onPointerLeave={() => {
                      profileContentHovered.current = false
                      closeProfileMenuSoon()
                    }}
                    onCloseAutoFocus={(event) => event.preventDefault()}
                  >
                    <DropdownMenuGroup>
                      <DropdownMenuItem onSelect={() => props.setShowIntegrations(true)} className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-white/84 focus:bg-cyan-300/[0.08]">
                        <IntegrationsIcon className="h-4 w-4 shrink-0 text-white/62" />
                        Integrations
                      </DropdownMenuItem>
                      <DropdownMenuItem className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-white/84 focus:bg-cyan-300/[0.08]">
                        <Bolt className="h-4 w-4 shrink-0 text-white/62" aria-hidden="true" />
                        Settings
                      </DropdownMenuItem>
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onSelect={props.signOut} variant="destructive" className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-red-400 focus:bg-red-400/[0.12] focus:text-red-300">
                      <DoorOpen className="h-4 w-4 shrink-0" aria-hidden="true" />
                      {props.isTestAccount ? 'Exit test run' : 'Sign out'}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ) : (
              <button
                type="button"
                className={`${darkCircleButtonClass} h-9 w-9 shadow-[0_10px_28px_rgba(0,0,0,0.3)]`}
                aria-label="Profile"
              >
                <UserCircle className="h-5.5 w-5.5" aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </header>

      {props.isDemoMode && (
        <div className="border-b border-white/[0.14] bg-white/[0.05] px-5 py-3 sm:px-8">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
            <p className={eyebrowClass}>Demo mode active</p>
            <button type="button" onClick={props.exitDemoMode} className={`${secondaryButtonClass} min-h-10 px-3 text-xs`}>Use my transcript</button>
          </div>
        </div>
      )}

      <main
        className={`relative z-10 -mt-3 max-w-[92rem] px-5 pb-28 transition-[padding,margin] duration-300 ease-out sm:px-8 ${
          chatOpen && activeView === 'meeting' && !isNarrow ? '' : 'mx-auto'
        }`}
        style={
          chatOpen && activeView === 'meeting' && !isNarrow
            ? { paddingLeft: '452px' }
            : undefined
        }
      >
        {activeView === 'home' && (
          <StatsCanvas
            history={props.history}
            loadFromHistory={handleSelectMeeting}
            loadSample={props.loadDashboardSample}
            canLoadSample={props.canLoadSample}
            selectedMeetingId={props.selectedMeetingId}
          />
        )}
        {activeView === 'meeting' && (
          <>
            {props.loading && <AnalyzingBanner result={props.result} />}
            {props.loading && !props.result ? (
              <MeetingViewSkeleton />
            ) : (
              <>
                {props.result && !props.loading && (
                  <MeetingActionsBar
                    shareToken={props.shareToken}
                    shareCopied={props.shareCopied}
                    setShareCopied={props.setShareCopied}
                    mdCopied={props.mdCopied}
                    copyMarkdown={props.copyMarkdown}
                    exportMarkdown={props.exportMarkdown}
                    exportPDF={props.exportPDF}
                    exportToSlack={props.exportToSlack}
                    exportToNotion={props.exportToNotion}
                    exportingSlack={props.exportingSlack}
                    exportingNotion={props.exportingNotion}
                    integrations={props.integrations}
                  />
                )}
                <Suspense fallback={<SkeletonCard lines={4} tall />}>
                  <MeetingView
                    result={props.result}
                    meeting={currentMeeting}
                    gmailConnected={props.calendarConnected}
                    onToggleActionItem={props.toggleActionItem}
                    transcript={props.transcript}
                    onBack={() => { sessionStorage.removeItem('prism_last_meeting_id'); setActiveView('home') }}
                  />
                </Suspense>
              </>
            )}
          </>
        )}
        {activeView === 'intelligence' && (
          <Suspense fallback={<SkeletonCard lines={4} tall />}>
            <IntelligenceView
              history={props.history}
              crossMeetingInsights={props.crossMeetingInsights}
              onSelectMeeting={handleSelectMeeting}
            />
          </Suspense>
        )}
      </main>

      {activeView === 'meeting' && props.result && !props.loading && (
        <>
          {/* Mobile backdrop */}
          {chatOpen && isNarrow && (
            <button
              type="button"
              aria-label="Close chat"
              onClick={() => setChatOpen(false)}
              className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px]"
            />
          )}

          {/* Slide-out chat panel */}
          <div
            aria-hidden={!chatOpen}
            className={`fixed left-3 top-[88px] bottom-[120px] z-50 flex flex-col overflow-hidden transition-all duration-300 ease-out ${
              chatOpen ? 'translate-x-0 opacity-100' : 'pointer-events-none -translate-x-[110%] opacity-0'
            } ${glassCard}`}
            style={{
              ...cardGlowStyle,
              width: isNarrow ? 'min(88vw, 420px)' : '420px',
            }}
          >
            <Suspense fallback={<div className="p-4 text-xs text-white/40">Loading chat…</div>}>
              <ChatPanel
                key={props.meetingId || 'no-meeting'}
                meetingId={props.meetingId}
                initialMessages={[]}
                pastSessions={pastSessions}
                onPastSessionsChange={setPastSessions}
                onCommitOnExit={handleChatCommitOnExit}
                transcript={props.transcript}
                result={props.result}
                onResultUpdate={(patch) => props.setResult((prev) => prev ? { ...prev, ...patch } : patch)}
                isSignedIn={!!props.user}
              />
            </Suspense>
          </div>

          {/* Floating trigger button — hidden when the mobile overlay is open (backdrop + Esc handle close) */}
          {!(chatOpen && isNarrow) && (
            <button
              type="button"
              onClick={() => setChatOpen((v) => !v)}
              aria-label={chatOpen ? 'Close chat' : 'Open chat'}
              aria-pressed={chatOpen}
              className={`fixed top-1/2 z-50 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/[0.14] bg-[#0c0d0f] text-white/80 shadow-[0_10px_28px_rgba(0,0,0,0.35)] transition-all duration-300 ease-out hover:border-cyan-300/40 hover:text-cyan-200 ${
                chatOpen ? 'left-[440px]' : 'left-4'
              }`}
              style={chatOpen ? { borderColor: 'rgba(34,211,238,0.45)', color: '#67e8f9' } : undefined}
            >
              {chatOpen ? <X className="h-4 w-4" aria-hidden="true" /> : <MessagesSquare className="h-4 w-4" aria-hidden="true" />}
            </button>
          )}
        </>
      )}

      <nav className="fixed bottom-5 left-1/2 z-30 h-[96px] w-[154px] -translate-x-1/2" aria-label="Dashboard shortcuts" data-node-id="4590:266">
        <div className="absolute bottom-4 left-1" data-history-panel>
          <DropdownMenu modal={false} open={props.showHistory} onOpenChange={props.setShowHistory}>
            <DropdownMenuTrigger asChild>
              <button type="button" className={`${darkCircleButtonClass} relative h-10 w-10`} aria-label="Open meeting history">
                <History className="h-4 w-4" aria-hidden="true" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              side="left"
              align="end"
              alignOffset={52}
              sideOffset={8}
              collisionPadding={16}
              className="dashboard-body-font w-[min(16.5rem,calc(100vw-2rem))] translate-x-1 -translate-y-4 overflow-hidden rounded-xl border-[#2f2f2f] bg-[#0b0b0b] p-1.5 text-white shadow-2xl shadow-black/50"
              data-history-panel
              onCloseAutoFocus={(event) => event.preventDefault()}
            >
              <div className="flex items-center justify-between gap-2 px-3 pb-1.5 pt-2">
                <p className="text-[13px] font-semibold leading-5 text-white/90">History</p>
                <button
                  type="button"
                  onClick={toggleHistorySearch}
                  aria-expanded={historySearchOpen}
                  aria-controls="dashboard-history-search-wrap"
                  aria-label="Search history"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/[0.08] bg-white/[0.035] text-white/48 transition hover:border-cyan-200/24 hover:bg-cyan-300/[0.08] hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/18 data-[state=open]:text-cyan-100"
                  data-state={historySearchOpen ? 'open' : 'closed'}
                >
                  <Search className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>

              {(props.user || props.isDemoMode) ? (
                <>
                  {historySearchOpen && (
                    <div id="dashboard-history-search-wrap" className="px-1.5 pb-1.5">
                      <label className="sr-only" htmlFor="dashboard-history-search">Search meetings</label>
                      <div className="flex h-7 items-center gap-2 rounded-md border border-white/[0.08] bg-white/[0.035] px-2 transition focus-within:border-cyan-400/45 focus-within:bg-white/[0.05] focus-within:ring-2 focus-within:ring-cyan-300/10">
                        <Search className="h-3 w-3 shrink-0 text-white/36" aria-hidden="true" />
                        <input
                          ref={historySearchInputRef}
                          id="dashboard-history-search"
                          value={props.historySearch || ''}
                          onChange={handleHistorySearchChange}
                          placeholder="Search meetings..."
                          className="h-full min-w-0 flex-1 bg-transparent text-[11px] font-medium text-white/80 outline-none placeholder:font-normal placeholder:text-white/32"
                        />
                      </div>
                    </div>
                  )}

                  <div className="max-h-[min(12rem,calc(100dvh-15rem))] space-y-1 overflow-y-auto">
                    {filteredHistory.length > 0 ? (
                      filteredHistory.map((entry) => (
                        <div key={entry.id} className="group flex items-center rounded-md pr-1 transition hover:bg-cyan-300/[0.055] focus-within:bg-cyan-300/[0.075]">
                          <button type="button" onClick={() => handleSelectMeeting(entry)} className="min-w-0 flex-1 rounded-md px-3 py-1.5 text-left focus-visible:outline-none">
                            <p className="truncate text-[13px] font-medium leading-5 text-white/88 group-hover:text-white">{deriveDisplayTitle(entry)}</p>
                            <p className="text-[10.5px] font-normal leading-4 text-white/44">{formatHistoryDate(entry.date)}</p>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteHistoryEntry(entry)}
                            aria-label={`Delete ${deriveDisplayTitle(entry)}`}
                            className="flex h-7 w-7 shrink-0 items-center justify-center text-white/30 opacity-100 transition hover:text-red-300 focus-visible:text-red-300 focus-visible:outline-none sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                          >
                            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                        </div>
                      ))
                    ) : (
                      <p className="px-4 py-6 text-center text-xs leading-5 text-white/46">
                        {props.historySearch ? 'No matching meetings.' : 'Saved meetings will appear here.'}
                      </p>
                    )}
                  </div>
                </>
              ) : (
                <div className="px-4 py-6 text-center">
                  <p className="text-xs font-medium text-white/72">Meeting history appears after you sign in from the landing page.</p>
                </div>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <DropdownMenu open={newMeetingOpen} onOpenChange={setNewMeetingOpen}>
          <DropdownMenuTrigger asChild>
            <button type="button" className="dashboard-signin-button absolute bottom-[38px] left-1/2 flex h-[60px] w-[60px] -translate-x-1/2 items-center justify-center rounded-full border text-cyan-50 shadow-xl transition hover:text-cyan-50" aria-label="New meeting">
              <Plus className="h-[19px] w-[19px]" aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side="top"
            align="center"
            sideOffset={12}
            modal={false}
            className="dashboard-body-font w-[340px] rounded-2xl border border-white/[0.10] bg-[#0f0f11] p-0 shadow-2xl"
            onCloseAutoFocus={(e) => e.preventDefault()}
          >
            <NewMeetingPanel {...props} onClose={() => setNewMeetingOpen(false)} />
          </DropdownMenuContent>
        </DropdownMenu>

        <button
          type="button"
          onClick={handleSwitchView}
          className={`${darkCircleButtonClass} absolute bottom-4 right-1 h-10 w-10`}
          style={inIntelligence ? { borderColor: 'rgba(34,211,238,0.45)', color: '#67e8f9' } : undefined}
          aria-label={inIntelligence ? 'Back to meeting view' : 'Switch to cross-meeting intelligence'}
        >
          {inIntelligence
            ? <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
            : <Brain className="h-4 w-4" aria-hidden="true" />
          }
        </button>
      </nav>

      <div
        className="pointer-events-none fixed bottom-0 left-1/2 z-20 -translate-x-1/2"
        style={{
          width: '800px',
          height: '400px',
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
          maskImage: 'radial-gradient(circle at 50% 90%, black 11%, transparent 25%)',
          WebkitMaskImage: 'radial-gradient(circle at 50% 90%, black 11%, transparent 25%)',
        }}
        aria-hidden="true"
      />


<Dialog open={showGateDialog} onOpenChange={setShowGateDialog}>
        <DialogContent className="dashboard-body-font border-[#2f2f2f] bg-[#0f0f11] text-white sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold text-white">More meetings needed</DialogTitle>
            <DialogDescription className="mt-2 text-sm leading-5 text-white/58">
              Cross-meeting intelligence unlocks after you save at least 2 meetings. Analyze another meeting to get started.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              onClick={() => setShowGateDialog(false)}
              className="rounded-full border border-white/[0.12] bg-white/[0.06] px-4 py-1.5 text-sm font-semibold text-white/80 transition hover:border-white/[0.22] hover:bg-white/[0.10]"
            >
              Got it
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
