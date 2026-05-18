import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  Copy,
  Download,
  FileText,
  MessageSquare,
  MessagesSquare,
  Share2,
  X,
} from 'lucide-react'
import { glassCard, cardGlowStyle } from './dashboard/dashboardStyles'
import { formatHistoryDate } from './dashboard/chrome'
import { apiFetch } from '../lib/api'
import { deriveDisplayTitle } from '../lib/insights'
import StatsCanvas from './dashboard/StatsCanvas'
import {
  DropdownMenu,
  DropdownMenuContent,
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
import DashboardSidebar from './dashboard/DashboardSidebar'
import DashboardTopbar from './dashboard/DashboardTopbar'

const SIDEBAR_MIN = 200
const SIDEBAR_MAX = 420
const SIDEBAR_DEFAULT = 248

const MeetingView = lazy(() => import('./dashboard/MeetingView'))
const IntelligenceView = lazy(() => import('./dashboard/IntelligenceView'))
const ChatPanel = lazy(() => import('./ChatPanel'))
const UpcomingMeetings = lazy(() => import('./UpcomingMeetings'))

const secondaryButtonClass = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-white/[0.16] bg-[#151515] px-4 text-sm font-semibold text-white/86 transition hover:border-white/[0.24] hover:bg-[#1d1d1d] hover:text-white'

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
                  <UpcomingMeetings
                    workspaces={props.workspaces || []}
                    onJoin={(url, wsId) => {
                      props.setMeetingUrl(url)
                      if (wsId) props.onJoinWithWorkspace?.(wsId)
                    }}
                  />
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

              {props.dedupBotInfo && (
                <div className="flex items-center gap-2 rounded-xl border border-cyan-400/[0.15] bg-cyan-400/[0.05] px-3 py-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-cyan-400/60" />
                  <p className="text-[11px] text-cyan-300/70">
                    Prism is already in this meeting via {props.dedupBotInfo.ownerUserEmail || 'a teammate'} — results will appear here when done.
                  </p>
                </div>
              )}

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
                <div className="flex items-center gap-2 rounded-xl border border-red-400/20 bg-red-400/[0.07] px-3 py-2">
                  <p className="flex-1 text-xs text-red-300">{props.botError}</p>
                  <button type="button" onClick={props.rejoinMeeting}
                    className="shrink-0 text-[10px] font-semibold text-cyan-300 transition hover:text-cyan-200">
                    Rejoin
                  </button>
                </div>
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
                  isDone ? `${agent.done} agent-pop` : 'animate-pulse border-white/[0.09] bg-white/[0.04] text-white/38'
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
  const [historySearchOpen, setHistorySearchOpen] = useState(false)
  const [newMeetingOpen, setNewMeetingOpen] = useState(false)
  const [activeView, setActiveView] = useState(
    () => sessionStorage.getItem('prism_active_view') ||
          (sessionStorage.getItem('prism_last_meeting_id') ? 'meeting' : 'home')
  )
  const [showGateDialog, setShowGateDialog] = useState(false)

  // --- Workspace state (activeWorkspaceId owned by App.jsx, synced via props) ---
  const [workspaces, setWorkspaces] = useState([])
  const activeWorkspaceId = props.activeWorkspaceId ?? null
  const [newWorkspaceName, setNewWorkspaceName] = useState('')
  const [creatingWorkspace, setCreatingWorkspace] = useState(false)
  const [workspaceCreateError, setWorkspaceCreateError] = useState('')
  const [workspaceCreating, setWorkspaceCreating] = useState(false)
  const [wsSettingsId, setWsSettingsId] = useState(null)
  const [wsDetails, setWsDetails] = useState(null)
  const [wsDetailsLoading, setWsDetailsLoading] = useState(false)
  const [inviteCopied, setInviteCopied] = useState(false)
  const [workspaceMemberMap, setWorkspaceMemberMap] = useState({})
  const [workspacesLoaded, setWorkspacesLoaded] = useState(false)
  const [workspaceNudgeDismissed, setWorkspaceNudgeDismissed] = useState(
    () => { try { return localStorage.getItem('prismai:workspace-nudge-dismissed') === '1' } catch { return false } }
  )
  const [shareWorkspaceId, setShareWorkspaceId] = useState(null)
  const [shareErrorId, setShareErrorId] = useState(null)

  // --- Sidebar resize / collapse (persisted) ---
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('prismai:sidebar-collapsed') === '1' } catch { return false }
  })
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const v = parseInt(localStorage.getItem('prismai:sidebar-width'), 10)
      return Number.isFinite(v) ? Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, v)) : SIDEBAR_DEFAULT
    } catch { return SIDEBAR_DEFAULT }
  })
  const [isResizing, setIsResizing] = useState(false)
  const sidebarWidthRef = useRef(sidebarWidth)

  useEffect(() => {
    try { localStorage.setItem('prismai:sidebar-collapsed', sidebarCollapsed ? '1' : '0') } catch { /* ignore */ }
  }, [sidebarCollapsed])
  useEffect(() => {
    sidebarWidthRef.current = sidebarWidth
    try { localStorage.setItem('prismai:sidebar-width', String(sidebarWidth)) } catch { /* ignore */ }
  }, [sidebarWidth])

  const toggleSidebar = useCallback(() => setSidebarCollapsed((v) => !v), [])

  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === '\\') {
        e.preventDefault()
        toggleSidebar()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [toggleSidebar])

  const onResizeHandlePointerDown = useCallback((e) => {
    e.preventDefault()
    setIsResizing(true)
    const startX = e.clientX
    const startW = sidebarWidthRef.current
    const onMove = (ev) => {
      const next = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, startW + (ev.clientX - startX)))
      setSidebarWidth(next)
    }
    const onUp = () => {
      setIsResizing(false)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }, [])

  // Persist active view so hard refresh restores the same view
  const persistView = (view) => {
    sessionStorage.setItem('prism_active_view', view)
    setActiveView(view)
  }

  const historyCount = props.history?.length || 0
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
    if (props.loading) persistView('meeting')
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
    if (props.result && activeView !== 'intelligence') {
      persistView(showingLatestSample && !userSelectedMeetingRef.current ? 'home' : 'meeting')
      userSelectedMeetingRef.current = false
    }
  }, [props.result, props.isTestAccount, props.meetingId, props.history])

  useEffect(() => {
    if (props.isTestAccount && props.inputTab === 'join') {
      props.setInputTab?.('paste')
    }
  }, [props.isTestAccount, props.inputTab, props.setInputTab])

  // Fetch workspace list when user is signed in
  useEffect(() => {
    if (!props.user) { setWorkspaces([]); setWorkspacesLoaded(false); return }
    apiFetch('/workspaces')
      .then((r) => r.ok ? r.json() : [])
      .then((data) => { setWorkspaces(data); setWorkspacesLoaded(true) })
      .catch(() => { setWorkspaces([]); setWorkspacesLoaded(true) })
  }, [props.user])

  // Build userId→email map for attribution when active workspace changes
  useEffect(() => {
    if (!activeWorkspaceId || !props.user) { setWorkspaceMemberMap({}); return }
    apiFetch(`/workspaces/${activeWorkspaceId}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.members) return
        const map = {}
        for (const m of data.members) {
          if (m.user_id && m.user_email) map[m.user_id] = m.user_email
        }
        setWorkspaceMemberMap(map)
      })
      .catch(() => {})
  }, [activeWorkspaceId, props.user?.id])

  // When active workspace changes: persist to sessionStorage and re-fetch scoped data
  function switchWorkspace(wsId) {
    props.onWorkspaceChange?.(wsId)
    persistView('home')
    setWsSettingsId(null)
    setWsDetails(null)
  }

  function dismissWorkspaceNudge() {
    setWorkspaceNudgeDismissed(true)
    try { localStorage.setItem('prismai:workspace-nudge-dismissed', '1') } catch { /* ignore */ }
  }

  async function createWorkspace() {
    const name = newWorkspaceName.trim()
    if (!name) return
    setWorkspaceCreateError('')
    setWorkspaceCreating(true)
    try {
      const r = await apiFetch('/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, user_email: props.user?.email || '' }),
      })
      if (r.ok) {
        const ws = await r.json()
        setWorkspaces((prev) => [...prev, { ...ws, role: 'owner', member_count: 1 }])
        setNewWorkspaceName('')
        setCreatingWorkspace(false)
        switchWorkspace(ws.id)
      } else {
        setWorkspaceCreateError('Failed to create — try again')
      }
    } catch {
      setWorkspaceCreateError('Could not reach server')
    } finally {
      setWorkspaceCreating(false)
    }
  }

  async function toggleWsSettings(wsId) {
    if (wsSettingsId === wsId) {
      setWsSettingsId(null)
      setWsDetails(null)
      return
    }
    setWsSettingsId(wsId)
    setWsDetails(null)
    setWsDetailsLoading(true)
    try {
      const r = await apiFetch(`/workspaces/${wsId}`)
      if (r.ok) setWsDetails(await r.json())
    } catch {}
    finally { setWsDetailsLoading(false) }
  }

  async function regenerateInvite() {
    if (!wsSettingsId) return
    const r = await apiFetch(`/workspaces/${wsSettingsId}/regenerate-invite`, { method: 'POST' })
    if (r.ok) {
      const data = await r.json()
      setWsDetails(prev => prev ? { ...prev, invite_token: data.invite_token } : prev)
      setWorkspaces(prev => prev.map(ws => ws.id === wsSettingsId ? { ...ws, invite_token: data.invite_token } : ws))
    }
  }

  async function removeMember(wsId, targetUserId) {
    const r = await apiFetch(`/workspaces/${wsId}/members/${targetUserId}`, { method: 'DELETE' })
    if (r.ok) {
      if (targetUserId === props.user?.id) {
        setWorkspaces(prev => prev.filter(ws => ws.id !== wsId))
        if (activeWorkspaceId === wsId) switchWorkspace(null)
        setWsSettingsId(null)
        setWsDetails(null)
      } else {
        setWsDetails(prev => prev ? { ...prev, members: prev.members.filter(m => m.user_id !== targetUserId) } : prev)
      }
    }
  }

  async function deleteWorkspaceFromSettings() {
    if (!wsSettingsId) return
    const r = await apiFetch(`/workspaces/${wsSettingsId}`, { method: 'DELETE' })
    if (r.ok) {
      setWorkspaces(prev => prev.filter(ws => ws.id !== wsSettingsId))
      if (activeWorkspaceId === wsSettingsId) switchWorkspace(null)
      setWsSettingsId(null)
      setWsDetails(null)
    }
  }

  function copyInviteLink(token) {
    const url = `${window.location.origin}/dashboard#invite/${token}`
    navigator.clipboard.writeText(url).then(() => {
      setInviteCopied(true)
      setTimeout(() => setInviteCopied(false), 2000)
    })
  }

  // Best-effort copy: Clipboard API, then a hidden-textarea/execCommand
  // fallback for insecure contexts where navigator.clipboard is unavailable.
  async function copyText(text) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
        return true
      }
    } catch { /* fall through to legacy path */ }
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch { return false }
  }

  // Per-row Share: fetch the workspace's invite token and copy the link
  // directly. Surfaces a transient error state if fetch or copy fails so the
  // click never silently no-ops.
  async function shareWorkspace(wsId) {
    setShareErrorId(null)
    try {
      const r = await apiFetch(`/workspaces/${wsId}`)
      if (!r.ok) throw new Error('fetch failed')
      const data = await r.json()
      const url = `${window.location.origin}/dashboard#invite/${data.invite_token}`
      const copied = await copyText(url)
      if (!copied) throw new Error('copy failed')
      setShareWorkspaceId(wsId)
      setTimeout(() => setShareWorkspaceId(null), 2000)
    } catch {
      setShareErrorId(wsId)
      setTimeout(() => setShareErrorId(null), 2500)
    }
  }

  function closeWsSettings() {
    setWsSettingsId(null)
    setWsDetails(null)
  }

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
      persistView('home')
    }
  }

  // Wrapped handler: load meeting AND switch to meeting view
  function handleSelectMeeting(entry) {
    userSelectedMeetingRef.current = true
    props.setShowHistory?.(false)
    props.loadFromHistory?.(entry)
    persistView('meeting')
  }

  // Find the currently loaded meeting metadata (for MeetingView title/date)
  const currentMeeting = useMemo(
    () => (props.meetingId ? (props.history || []).find((m) => m.id === props.meetingId) || null : null),
    [props.meetingId, props.history],
  )

  const recordedByEmail = useMemo(() => {
    if (!currentMeeting?.recorded_by_user_id) return null
    if (currentMeeting.recorded_by_user_id === props.user?.id) return null
    return workspaceMemberMap[currentMeeting.recorded_by_user_id] || null
  }, [currentMeeting, props.user?.id, workspaceMemberMap])

  // A meeting is "in focus" when the focused surface is a real meeting.
  // Cross-meeting intelligence is always reached via a focused meeting (ADR 0001),
  // so the switch stays enabled there too. A stale 'meeting' view with no
  // meeting/result/loading keeps the switch grayed.
  const meetingInFocus =
    activeView === 'intelligence' ||
    (activeView === 'meeting' && (!!props.meetingId || !!props.result || props.loading))
  const switchView = activeView === 'intelligence' ? 'cross' : 'current'

  function handleSelectSwitchView(v) {
    if (v === 'cross') {
      if (historyCount < 2) {
        setShowGateDialog(true)
        return
      }
      persistView('intelligence')
    } else {
      persistView('meeting')
    }
  }

  const showHomeNudge =
    props.user &&
    workspacesLoaded &&
    workspaces.length === 0 &&
    !workspaceNudgeDismissed &&
    activeView === 'home'

  return (
    <div
      className={`landing-page dashboard-page min-h-dvh overflow-x-hidden text-[color:var(--landing-text)] ${isResizing ? 'is-resizing' : ''}`}
      style={{ '--dashboard-sidebar-w': sidebarCollapsed ? '56px' : `${sidebarWidth}px` }}
    >
      <DashboardTopbar
        newMeetingOpen={newMeetingOpen}
        setNewMeetingOpen={setNewMeetingOpen}
        onOpenNewMeeting={() => (props.prepareNewMeeting ?? props.resetTranscriptWorkspaces)?.()}
        newMeetingPanel={
          <NewMeetingPanel {...props} workspaces={workspaces} onClose={() => setNewMeetingOpen(false)} />
        }
        meetingInFocus={meetingInFocus}
        view={switchView}
        onSelectView={handleSelectSwitchView}
      />

      <DashboardSidebar
        collapsed={sidebarCollapsed}
        onToggleCollapse={toggleSidebar}
        onResizeHandlePointerDown={onResizeHandlePointerDown}
        user={props.user}
        isTestAccount={props.isTestAccount}
        isDemoMode={props.isDemoMode}
        workspaces={workspaces}
        activeWorkspaceId={activeWorkspaceId}
        switchWorkspace={switchWorkspace}
        creatingWorkspace={creatingWorkspace}
        setCreatingWorkspace={setCreatingWorkspace}
        newWorkspaceName={newWorkspaceName}
        setNewWorkspaceName={setNewWorkspaceName}
        createWorkspace={createWorkspace}
        workspaceCreating={workspaceCreating}
        workspaceCreateError={workspaceCreateError}
        setWorkspaceCreateError={setWorkspaceCreateError}
        shareWorkspace={shareWorkspace}
        shareWorkspaceId={shareWorkspaceId}
        shareErrorId={shareErrorId}
        toggleWsSettings={toggleWsSettings}
        wsSettingsId={wsSettingsId}
        wsDetails={wsDetails}
        wsDetailsLoading={wsDetailsLoading}
        regenerateInvite={regenerateInvite}
        removeMember={removeMember}
        deleteWorkspaceFromSettings={deleteWorkspaceFromSettings}
        copyInviteLink={copyInviteLink}
        inviteCopied={inviteCopied}
        closeWsSettings={closeWsSettings}
        history={props.history || []}
        filteredHistory={filteredHistory}
        historySearch={props.historySearch}
        historySearchOpen={historySearchOpen}
        toggleHistorySearch={toggleHistorySearch}
        onHistorySearchChange={handleHistorySearchChange}
        activeView={activeView}
        onGoHome={() => persistView('home')}
        onSelectMeeting={handleSelectMeeting}
        onDeleteMeeting={handleDeleteHistoryEntry}
        currentMeetingId={props.meetingId}
        botActive={props.botStatus && !['done', 'error'].includes(props.botStatus)}
        setShowIntegrations={props.setShowIntegrations}
        signOut={props.signOut}
      />

      <div className="dashboard-content">
        {showHomeNudge && (
          <div className="px-5 pt-4 sm:px-8">
            <div className="mx-auto flex max-w-[92rem] items-center gap-3 rounded-xl border border-cyan-400/[0.15] bg-cyan-400/[0.05] px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-[12px] font-semibold text-cyan-200/90">Invite your team</p>
                <p className="mt-0.5 text-[11px] leading-5 text-white/50">
                  Create a workspace to share meeting summaries, action items, and insights with teammates.
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCreatingWorkspace(true)}
                  className="rounded-full border border-cyan-400/40 bg-cyan-400/[0.12] px-3 py-1 text-[10px] font-semibold text-cyan-300 transition hover:bg-cyan-400/[0.22]"
                >
                  Create workspace
                </button>
                <button
                  type="button"
                  onClick={dismissWorkspaceNudge}
                  aria-label="Dismiss invite prompt"
                  className="text-white/30 transition hover:text-white/60"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
        )}

        <main className="relative z-10 mx-auto mt-2 max-w-[92rem] px-5 pb-28 sm:px-8">
          <div key={activeView} className="animate-fade-in-up">
          {(activeView === 'home' || (activeView === 'meeting' && !props.result)) && (
            <StatsCanvas
              history={props.history}
              loadFromHistory={handleSelectMeeting}
              loadSample={props.loadDashboardSample}
              canLoadSample={props.canLoadSample}
              selectedMeetingId={props.selectedMeetingId}
              memberEmailMap={workspaceMemberMap}
              currentUserId={props.user?.id}
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
                      onBack={() => { sessionStorage.removeItem('prism_last_meeting_id'); persistView('home') }}
                      recordedByEmail={recordedByEmail}
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
                workspaceName={activeWorkspaceId ? (workspaces.find((ws) => ws.id === activeWorkspaceId)?.name ?? null) : null}
              />
            </Suspense>
          )}
          </div>
        </main>
      </div>

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

          {/* Bottom-right docked chat panel */}
          <div
            aria-hidden={!chatOpen}
            className={`dashboard-chat-panel fixed z-50 flex flex-col overflow-hidden transition-all duration-300 ease-out ${
              chatOpen ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-4 opacity-0'
            } ${glassCard} ${
              isNarrow
                ? 'inset-x-3 bottom-3 top-16'
                : 'bottom-5 right-5 h-[min(640px,calc(100dvh-7rem))] w-[400px]'
            }`}
            style={cardGlowStyle}
          >
            <button
              type="button"
              onClick={() => setChatOpen(false)}
              aria-label="Close chat"
              className="absolute right-3 top-3 z-10 flex h-7 w-7 items-center justify-center rounded-full text-white/45 transition hover:bg-white/[0.08] hover:text-white/80"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
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

          {/* Bottom-right launcher (hidden while the panel is open) */}
          {!chatOpen && (
            <button
              type="button"
              onClick={() => setChatOpen(true)}
              aria-label="Open chat"
              aria-pressed={false}
              className="dashboard-chat-trigger fixed bottom-5 right-5 z-50 flex h-12 w-12 items-center justify-center rounded-full border border-cyan-400/35 bg-[#0c0d0f] text-cyan-200 shadow-[0_12px_30px_rgba(0,0,0,0.4)] transition-all duration-200 ease-out hover:scale-105 hover:border-cyan-300/55 hover:text-cyan-100"
            >
              <MessagesSquare className="h-5 w-5" aria-hidden="true" />
            </button>
          )}
        </>
      )}

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
