import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  CalendarPlus,
  Check,
  Copy,
  Download,
  FileText,
  FolderInput,
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
import MeetingTypeControl from './dashboard/MeetingTypeControl'
import { INPUT_TYPE_OPTIONS } from '../lib/meetingType'
import LiveCatchup from './LiveCatchup'
import StandInComposer from './StandInComposer'
const ProxyProfile = lazy(() => import('./ProxyProfile'))
const CalendarView = lazy(() => import('./CalendarView'))
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs'
import { Button } from './ui/button'
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
import LiveMeetingView from './dashboard/LiveMeetingView'
import { deriveStatus } from './dashboard/StatusIsland'
import { useStatusNotification, notifyStatus } from '../lib/statusNotify'
import WorkspaceIsland from './dashboard/WorkspaceIsland'

const MeetingView = lazy(() => import('./dashboard/MeetingView'))
const IntelligenceView = lazy(() => import('./dashboard/IntelligenceView'))
const KnowledgeBase = lazy(() => import('./KnowledgeBase'))
const ChatPanel = lazy(() => import('./ChatPanel'))
const UpcomingMeetings = lazy(() => import('./UpcomingMeetings'))

const secondaryButtonClass = 'inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/[0.10] bg-white/[0.04] text-white/85 transition hover:border-cyan-400/45 hover:bg-white/[0.06] hover:text-white'

function MeetingActionsBar({
  shareToken,
  shareCopied,
  setShareCopied,
  mdCopied,
  copyMarkdown,
  exportMarkdown,
  exportPDF,
  exportTranscriptPDF,
  downloadTranscriptTxt,
  hasTranscript = false,
  exportToSlack,
  exportToNotion,
  exportingSlack,
  exportingNotion,
  integrations,
  canMove = false,
  currentWorkspaceId = null,
  workspaces = [],
  onMoveMeeting,
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

  const curWs = currentWorkspaceId || null

  return (
    <div className="flex items-center gap-2">
      {canMove && (
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <button type="button" className={secondaryButtonClass} aria-label="Move meeting" title="Move to…">
              <FolderInput className="h-4 w-4" aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="dashboard-body-font w-56 rounded-xl border-[#2f2f2f] bg-[#0b0b0b] p-1.5"
          >
            <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-white/35">Move to</div>
            <DropdownMenuItem
              disabled={curWs === null}
              onSelect={() => onMoveMeeting?.(null)}
              className={itemClass}
            >
              <span className="flex-1">Personal</span>
              {curWs === null && <Check className="h-3.5 w-3.5 shrink-0 text-cyan-300" aria-hidden="true" />}
            </DropdownMenuItem>
            {workspaces.map((ws) => (
              <DropdownMenuItem
                key={ws.id}
                disabled={curWs === ws.id}
                onSelect={() => onMoveMeeting?.(ws.id)}
                className={itemClass}
              >
                <span className="min-w-0 flex-1 truncate">{ws.name}</span>
                {curWs === ws.id && <Check className="h-3.5 w-3.5 shrink-0 text-cyan-300" aria-hidden="true" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {shareToken && (
        <button
          type="button"
          onClick={handleShare}
          className={secondaryButtonClass}
          style={shareCopied ? { borderColor: 'rgba(34,211,238,0.45)', color: '#67e8f9' } : undefined}
          aria-label={shareCopied ? 'Share link copied' : 'Copy share link'}
          title={shareCopied ? 'Copied!' : 'Share'}
        >
          {shareCopied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Share2 className="h-4 w-4" aria-hidden="true" />}
        </button>
      )}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button type="button" className={secondaryButtonClass} aria-label="Export meeting" title="Export">
            <Download className="h-4 w-4" aria-hidden="true" />
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
          {hasTranscript && (
            <>
              <DropdownMenuItem onSelect={() => exportTranscriptPDF?.()} className={itemClass}>
                <FileText className={iconClass} aria-hidden="true" />
                Transcript → PDF
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => downloadTranscriptTxt?.()} className={itemClass}>
                <Download className={iconClass} aria-hidden="true" />
                Download transcript .txt
              </DropdownMenuItem>
            </>
          )}
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

function AnalyzeButton({ loading, handleAnalyzeClick, cancelActiveAnalysis, transcript, meetingType, setMeetingType }) {
  if (loading) {
    return (
      <button type="button" onClick={cancelActiveAnalysis} className="w-full rounded-full border border-white/[0.10] py-2.5 text-sm font-semibold text-white/60 transition hover:bg-white/[0.05]">
        Analyzing… (cancel)
      </button>
    )
  }
  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <MeetingTypeControl
          label="Type"
          value={meetingType || 'auto'}
          onChange={setMeetingType}
          options={INPUT_TYPE_OPTIONS}
          title="Auto detects pitch / interview meetings for a deeper, type-specific analysis. Pick one to force it."
        />
      </div>
      <Button
        variant="primary"
        size="cta"
        onClick={handleAnalyzeClick}
        disabled={!transcript}
        title={!transcript ? 'Add a transcript first' : undefined}
        className="w-full disabled:cursor-not-allowed disabled:opacity-40"
      >
        Analyze Meeting
      </Button>
      {!transcript && (
        <p className="text-center text-[11px] text-white/40">Paste, upload, record, or join a meeting to analyze.</p>
      )}
    </div>
  )
}

function NewMeetingPanel(props) {
  const activeTab = props.isTestAccount && props.inputTab === 'join' ? 'paste' : (props.inputTab || 'paste')
  const botActive = props.botStatus && !['done', 'error'].includes(props.botStatus)

  return (
    <div className="dashboard-body-font w-full overflow-hidden rounded-2xl">
      <div className="flex items-center justify-between px-4 pb-3 pt-3.5">
        <p className="text-[13px] font-semibold text-white/90">New Meeting</p>
        <Button
          variant="subtle"
          size="icon-xs"
          onClick={props.onClose}
          className="rounded-full"
          aria-label="Close"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
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
                placeholder="Paste a transcript, article, or report…"
                rows={7}
                className="w-full resize-none rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 text-sm text-white/90 outline-none placeholder:text-white/28 focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/20"
              />
              {/* Upload a document instead of pasting — extracts text server-side
                  (.docx/.pdf/.txt). Handy for the Article / Report lens. */}
              <input
                ref={props.docInputRef}
                type="file"
                accept=".docx,.pdf,.txt,.md,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                className="hidden"
                onChange={props.handleDocumentUpload}
              />
              <div className="flex items-center justify-between gap-2">
                {props.transcriptStats?.words > 0 ? (
                  <p className="text-[10.5px] text-white/38">
                    {props.transcriptStats.words} words
                    {/* Speaker count is meaningless for a single-authored article/report. */}
                    {props.meetingType !== 'article' && ` · ${props.transcriptSpeakerCount || 0} speaker${props.transcriptSpeakerCount !== 1 ? 's' : ''}`}
                  </p>
                ) : <span />}
                <button
                  type="button"
                  onClick={() => props.docInputRef?.current?.click()}
                  disabled={props.extractingDoc}
                  title="Upload a .docx, .pdf, or .txt"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 py-1.5 text-[11px] font-medium text-white/55 transition hover:border-cyan-400/30 hover:bg-white/[0.06] hover:text-white/85 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {props.extractingDoc ? (
                    <>
                      <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
                        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                      </svg>
                      Reading…
                    </>
                  ) : (
                    <>
                      <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 3v4a1 1 0 0 0 1 1h4" />
                        <path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2Z" />
                        <path d="M12 18v-6" />
                        <path d="m9.5 14.5 2.5-2.5 2.5 2.5" />
                      </svg>
                      Upload a document
                    </>
                  )}
                </button>
              </div>
              {props.docError && (
                <p className="rounded-lg border border-red-400/25 bg-red-400/[0.08] px-3 py-2 text-[11px] leading-relaxed text-red-200">
                  {props.docError}
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
                accept="audio/*,video/*,.mp3,.wav,.m4a,.ogg,.webm,.mp4,.mov,.mkv,.m4v"
                className="hidden"
                onChange={props.handleAudioUpload}
              />
              <button
                type="button"
                onClick={() => props.fileInputRef?.current?.click()}
                disabled={props.transcribing}
                className="w-full rounded-xl border border-white/[0.10] bg-white/[0.05] px-4 py-2.5 text-sm font-semibold text-white/80 transition hover:bg-white/[0.08] disabled:opacity-50"
              >
                {props.transcribing ? `⏳ ${props.transcribeStatus || 'Working…'}` : '📎 Choose Audio or Video'}
              </button>
              {!props.transcribing && !props.transcript && !props.transcribeError && (
                <p className="text-[10.5px] leading-relaxed text-white/38">
                  Audio or video. Video audio is extracted in your browser — the first
                  large file loads a converter (~30MB, cached after). Keep recordings
                  under ~70 min.
                </p>
              )}
              {props.transcribeError && !props.transcribing && (
                <p className="rounded-lg border border-red-400/25 bg-red-400/[0.08] px-3 py-2 text-[11px] leading-relaxed text-red-200">
                  {props.transcribeError}
                </p>
              )}
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
                // Bound the upcoming-meetings region (its Briefs expand tall) so
                // it scrolls internally — keeps the URL input + Join button in view.
                <div className="max-h-[40vh] overflow-y-auto">
                  <Suspense fallback={null}>
                    <UpcomingMeetings
                      workspaces={props.workspaces || []}
                      user={props.user}
                      onCantMakeIt={props.onCantMakeIt}
                      onJoin={(url, wsId) => {
                        props.setMeetingUrl(url)
                        if (wsId) props.onJoinWithWorkspace?.(wsId)
                      }}
                      onOpenMeeting={props.onOpenMeeting}
                    />
                  </Suspense>
                </div>
              )}
              {!props.calendarConnected && props.user && !props.isTestAccount && (
                // Calendar not connected → the upcoming-meetings list can't render, so
                // fill that spot with the exact CTA the user needs here (auto-join is
                // the highest-value setup step). Opens Integrations → Calendar tab, where
                // both Google Calendar and Outlook are offered.
                <button
                  type="button"
                  onClick={() => { props.onClose?.(); props.onOpenCalendarSetup?.() }}
                  className="group flex w-full items-center gap-3 rounded-xl border border-cyan-400/20 bg-cyan-400/[0.06] px-3 py-2.5 text-left transition hover:bg-cyan-400/[0.11]"
                >
                  <CalendarPlus className="h-4 w-4 shrink-0 text-cyan-300" aria-hidden="true" />
                  <span className="min-w-0 flex-1 text-[12px] leading-snug text-cyan-100/80">
                    Connect Google or Outlook calendar to see your upcoming meetings and one-click join.
                  </span>
                  <span className="shrink-0 text-[12px] font-semibold text-cyan-200">Connect →</span>
                </button>
              )}
              <input
                type="url"
                value={props.meetingUrl || ''}
                onChange={(e) => props.setMeetingUrl(e.target.value)}
                placeholder="Paste Zoom / Meet / Teams link..."
                disabled={botActive}
                className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-3 py-2.5 text-sm text-white/90 outline-none placeholder:text-white/28 focus:border-cyan-400/40 focus:ring-1 focus:ring-cyan-400/20 disabled:opacity-50"
              />

              <div className="space-y-1.5">
                <p className="text-[10.5px] font-medium uppercase tracking-wide text-white/40">Response mode</p>
                <div className="flex gap-1 rounded-xl border border-white/[0.08] bg-white/[0.03] p-1">
                  {[
                    { id: 'auto', label: 'Auto', hint: 'Speaks when it judges a contribution is warranted' },
                    { id: 'manual', label: 'Manual', hint: 'Only responds when addressed ("Prism, …")' },
                  ].map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      disabled={botActive}
                      title={m.hint}
                      onClick={() => props.setJoinMode?.(m.id)}
                      className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
                        (props.joinMode || 'auto') === m.id
                          ? 'bg-cyan-400/[0.16] text-cyan-200'
                          : 'text-white/50 hover:text-white/75'
                      }`}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
                <p className="text-[10px] text-white/30">
                  {(props.joinMode || 'auto') === 'auto'
                    ? 'Prism will proactively contribute throughout the meeting.'
                    : 'Prism stays silent until you address it by name.'}
                </p>
              </div>

              {props.dedupBotInfo && (
                <div className="flex items-center gap-2 rounded-xl border border-cyan-400/[0.15] bg-cyan-400/[0.05] px-3 py-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-cyan-400/60" />
                  <p className="text-[11px] text-cyan-300/70">
                    {props.dedupBotInfo.self
                      ? 'Prism is already in this meeting — reconnecting to your existing session.'
                      : `Prism is already in this meeting via ${props.dedupBotInfo.ownerUserEmail || 'a teammate'} — results will appear here when done.`}
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
                  <div className="ml-auto flex items-center gap-2">
                    {props.botStatus === 'recording' && (
                      <button
                        type="button"
                        onClick={props.toggleBotMute}
                        title={props.botMuted ? 'Prism will not offer suggestions' : 'Stop Prism from chiming in'}
                        className={`rounded-full px-2 py-0.5 text-[10px] font-semibold transition ${
                          props.botMuted
                            ? 'bg-amber-400/15 text-amber-300 hover:bg-amber-400/25'
                            : 'bg-white/[0.06] text-white/55 hover:text-white/85'
                        }`}
                      >
                        {props.botMuted ? 'Muted' : 'Mute Prism'}
                      </button>
                    )}
                    <button type="button" onClick={props.cancelBot} className="text-[10px] text-white/36 hover:text-white/60">
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* Where this live meeting's notes will be saved — the bot's workspace is
                  fixed at join, so this stays accurate even if the global chip changes. */}
              {botActive && (
                <p className="px-1 text-[10.5px] text-white/40">
                  Recording into:{' '}
                  <span className="font-medium text-white/65">
                    {props.botWorkspaceId
                      ? (props.workspaces?.find((w) => w.id === props.botWorkspaceId)?.name ?? 'a workspace')
                      : 'Personal'}
                  </span>
                </p>
              )}

              {props.botStatus === 'recording' && props.activeLiveToken && (
                <LiveCatchup liveToken={props.activeLiveToken} accessToken={props.accessToken} />
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

              <Button
                variant="primary"
                size="cta"
                onClick={props.joinMeeting}
                disabled={!props.meetingUrl || botActive}
                className="w-full disabled:cursor-not-allowed disabled:opacity-40"
              >
                {props.botStatus === 'joining' ? 'Joining…' :
                 props.botStatus === 'recording' ? 'Recording…' :
                 props.botStatus === 'processing' ? 'Processing…' :
                 'Join Meeting'}
              </Button>
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
  const [newMeetingOpen, setNewMeetingOpen] = useState(false)
  // Stand-in composer lives at page level (NOT inside the New Meeting dropdown):
  // the dropdown closes on outside-click, so a portaled modal inside it would be
  // torn down the moment you interact with it.
  const [standIn, setStandIn] = useState(null)
  const [activeView, setActiveView] = useState(() => {
    // A live/share token (deep-link) wins over the persisted view.
    if (props.liveToken) return 'live'
    if (props.shareData || props.shareLoading) return 'shared'
    return sessionStorage.getItem('prism_active_view') ||
      (sessionStorage.getItem('prism_last_meeting_id') ? 'meeting' : 'home')
  })
  const [showGateDialog, setShowGateDialog] = useState(false)
  // Live sub-view status, lifted from LiveMeetingView so the status island can
  // reflect live progress (joining|recording|processing|done|error).
  const [liveStatus, setLiveStatus] = useState(null)
  // Transient island notifications (fire-and-forget; preempt the base state ~2.5s).
  const notification = useStatusNotification()
  // Unauthenticated viewer (arrived via a live/share link): the dashboard chrome
  // renders but every feature is locked behind the sign-in gate.
  const signedOut = !props.user && !props.isDemoMode
  const [showSignInGate, setShowSignInGate] = useState(false)
  const requestSignIn = useCallback(() => setShowSignInGate(true), [])

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
  // Attendee emails harvested from the user's connected calendars (Google + Outlook)
  // upcoming events — fed into the follow-up CalendarCard + EmailCard suggestion chips
  // alongside workspace members, so you can one-click the people you actually meet with.
  const [calendarAttendeeEmails, setCalendarAttendeeEmails] = useState([])
  const [workspacesLoaded, setWorkspacesLoaded] = useState(false)
  const [workspaceNudgeDismissed, setWorkspaceNudgeDismissed] = useState(
    () => { try { return localStorage.getItem('prismai:workspace-nudge-dismissed') === '1' } catch { return false } }
  )
  const [shareWorkspaceId, setShareWorkspaceId] = useState(null)
  const [shareErrorId, setShareErrorId] = useState(null)

  // Persist active view so hard refresh restores the same view. Live/shared are
  // token-driven (not persisted) so they never become the restored default.
  // Remember where the user was before opening a meeting, so the back arrow returns
  // there (e.g. Calendar → meeting → back → Calendar) instead of always going Home.
  const lastNonMeetingViewRef = useRef('home')
  const persistView = (view) => {
    if (view !== 'meeting') lastNonMeetingViewRef.current = view
    sessionStorage.setItem('prism_active_view', view)
    setActiveView(view)
  }
  const goBackFromMeeting = () => persistView(lastNonMeetingViewRef.current || 'home')

  // Keep activeView in sync with the live/share hash router (App owns the tokens
  // and updates them on deep-link, in-app nav, and browser back/forward). A token
  // switches us into the sub-view; clearing it (e.g. back) restores the last
  // persisted view.
  useEffect(() => {
    if (props.liveToken) { setActiveView('live'); return }
    setLiveStatus(null) // left the live sub-view — reset so the island doesn't keep a stale live state
    if (props.shareData || props.shareLoading) { setActiveView('shared'); return }
    setActiveView((prev) =>
      prev === 'live' || prev === 'shared'
        ? (sessionStorage.getItem('prism_active_view') || 'home')
        : prev,
    )
  }, [props.liveToken, props.shareData, props.shareLoading])

  const historyCount = props.history?.length || 0
  const isFirstRender = useRef(true)
  const userSelectedMeetingRef = useRef(false)
  // The meeting the auto-switch effect last acted on, so history mutations
  // (e.g. checking off an action item) don't re-trigger a stray navigation.
  const lastNavMeetingRef = useRef(undefined)

  // --- Chat panel state ---
  const [chatOpen, setChatOpen] = useState(() => {
    try { return localStorage.getItem('prismai:dashboard-chat-open') === '1' } catch { return false }
  })
  const [isNarrow, setIsNarrow] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia('(max-width: 1023px)').matches
  })
  // Off-canvas nav drawer (mobile). Opened by the topbar hamburger; closed by the
  // backdrop, Escape, navigating, or growing back to desktop width.
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [pastSessions, setPastSessions] = useState([])

  useEffect(() => {
    try { localStorage.setItem('prismai:dashboard-chat-open', chatOpen ? '1' : '0') } catch { /* ignore */ }
  }, [chatOpen])

  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const mql = window.matchMedia('(max-width: 1023px)')
    const handler = (e) => { setIsNarrow(e.matches); if (!e.matches) setMobileNavOpen(false) }
    mql.addEventListener?.('change', handler)
    return () => mql.removeEventListener?.('change', handler)
  }, [])

  // Close the mobile drawer whenever the view or workspace changes (a nav/meeting
  // tap), and on Escape.
  useEffect(() => { setMobileNavOpen(false) }, [activeView, activeWorkspaceId])
  useEffect(() => {
    if (!mobileNavOpen) return undefined
    const handler = (e) => { if (e.key === 'Escape') setMobileNavOpen(false) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [mobileNavOpen])

  useEffect(() => {
    if (!chatOpen) return undefined
    const handler = (e) => { if (e.key === 'Escape') setChatOpen(false) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [chatOpen])

  // Fetch up to 3 past chat sessions for this meeting on entry. If there's a pending
  // exit-save POST for the same meeting, wait for it first so the fetch sees the new row.
  // Merge a partial result update into the live result AND persist it, so card edits
  // and chat-driven regenerations (email edits, calendar, etc.) survive a refresh
  // instead of reverting to the saved version. Shared by MeetingView + ChatPanel.
  const persistResultPatch = useCallback((patch) => {
    const merged = { ...(props.result || {}), ...patch }
    props.setResult(merged)
    if (props.meetingId) {
      // Keep the in-memory history entry in sync too — Home cards and "reopen from
      // history" read from `history`, so without this a re-lens / edit shows stale
      // (e.g. the meeting-type override wouldn't reflect on Home or on reopen).
      props.setHistory?.((prev) =>
        prev.map((e) => (String(e.id) === String(props.meetingId) ? { ...e, result: merged } : e)),
      )
      apiFetch(`/meetings/${props.meetingId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ result: merged }),
      }).catch(() => {})
    }
  }, [props.result, props.meetingId, props.setResult, props.setHistory])

  // A chat correction (correct_meeting_text) already persisted the fresh result +
  // transcript server-side. Reflect it in the live view (cards + transcript) and the
  // in-memory history WITHOUT re-persisting — the server is already the source of truth.
  const onCorrectApplied = useCallback((data) => {
    if (!data) return
    if (data.result) props.setResult(data.result)
    if (typeof data.transcript === 'string') props.setTranscript?.(data.transcript)
    if (props.meetingId) {
      props.setHistory?.((prev) =>
        prev.map((e) => (String(e.id) === String(props.meetingId)
          ? {
              ...e,
              ...(data.result ? { result: data.result } : {}),
              ...(typeof data.transcript === 'string' ? { transcript: data.transcript } : {}),
            }
          : e)),
      )
    }
  }, [props.meetingId, props.setResult, props.setTranscript, props.setHistory])

  // Per-meeting chat history. ChatPanel saves the live thread continuously
  // (one growing session per meeting); this just (re)loads the session list —
  // called on meeting change and whenever ChatPanel reports a brand-new session.
  // Which meeting the currently-held pastSessions belong to. A freshly-keyed
  // ChatPanel initializes its thread from activeSession DURING render — before the
  // clear-and-refetch effect runs — so without this guard it would seed the new
  // meeting with the PREVIOUS meeting's thread and then auto-save it under the new
  // id (cross-meeting chat bleed). We only hand sessions to ChatPanel when they were
  // fetched for the meeting currently open.
  const [sessionsForMeeting, setSessionsForMeeting] = useState(null)

  const refreshPastSessions = useCallback(() => {
    if (!props.meetingId || !props.user) { setPastSessions([]); setSessionsForMeeting(props.meetingId ?? null); return }
    const forId = props.meetingId
    apiFetch(`/chat-sessions/${forId}`)
      .then((res) => (res.ok ? res.json() : { sessions: [] }))
      .then((data) => { setPastSessions(data.sessions || []); setSessionsForMeeting(forId) })
      .catch(() => { setPastSessions([]); setSessionsForMeeting(forId) })
  }, [props.meetingId, props.user?.id])

  // Clear stale sessions immediately on meeting switch (ChatPanel is keyed by
  // meetingId and remounts before the new fetch lands — must not see the old
  // meeting's thread), then load the new meeting's.
  useEffect(() => { setPastSessions([]); setSessionsForMeeting(null); refreshPastSessions() }, [refreshPastSessions])

  // Only the sessions confirmed to belong to the open meeting are visible to ChatPanel.
  const scopedSessions = sessionsForMeeting === props.meetingId ? pastSessions : []

  // Switch to meeting view immediately when analysis starts
  useEffect(() => {
    if (props.loading) persistView('meeting')
  }, [props.loading])

  // Auto-switch to meeting view when a new result is loaded (not on initial mount).
  // Guarded on the OPEN meeting changing: history is in the deps for the sample
  // check below, but a history mutation alone (e.g. checking off an action item)
  // must NOT navigate — that pulled the user into the last-loaded meeting.
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false
      lastNavMeetingRef.current = props.meetingId
      return
    }
    if (props.meetingId === lastNavMeetingRef.current) return
    lastNavMeetingRef.current = props.meetingId
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
  }, [props.user?.id])

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

  async function saveWorkspacePersona(workspaceId, defaultPersona) {
    const r = await apiFetch(`/workspaces/${workspaceId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ default_persona: defaultPersona }),
    })
    if (r.ok) {
      setWsDetails(prev => prev ? { ...prev, default_persona: defaultPersona } : prev)
      setWorkspaces(prev => prev.map(ws =>
        ws.id === workspaceId ? { ...ws, default_persona: defaultPersona } : ws
      ))
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

  function handleHistorySearchChange(value) {
    props.setHistorySearch?.(value)
  }

  async function handleDeleteHistoryEntry(entry) {
    const clearIfOpen = () => {
      if (entry.id === props.meetingId) {
        sessionStorage.setItem('prism_new_meeting', '1')
        props.clearWorkspaceState?.()
        persistView('home')
      }
    }
    if (props.isTestAccount) {
      props.setHistory?.((prev) => prev.filter((item) => item.id !== entry.id))
      clearIfOpen()
      return
    }
    // Confirm the server actually removed it before hiding it — a silent failure used to
    // vanish from the list then reappear on refresh. Report what happened instead.
    try {
      const res = await apiFetch(`/meetings/${entry.id}`, { method: 'DELETE' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        notifyStatus({ kind: 'error', message: `Delete failed (HTTP ${res.status})` })
        return
      }
      if (!data.deleted) {
        notifyStatus({ kind: 'error', message: `Delete matched 0 rows (${data.scope || 'unknown'})` })
        return
      }
      props.setHistory?.((prev) => prev.filter((item) => item.id !== entry.id))
      notifyStatus({ kind: 'success', message: 'Meeting deleted' })
      clearIfOpen()
    } catch {
      notifyStatus({ kind: 'error', message: 'Delete failed (network)' })
    }
  }

  // Wrapped handler: load meeting AND switch to meeting view
  function handleSelectMeeting(entry) {
    userSelectedMeetingRef.current = true
    props.setShowHistory?.(false)
    props.loadFromHistory?.(entry)
    persistView('meeting')
    setMobileNavOpen(false)
  }

  // Open a meeting by id — fetches the full row first so this works even when the
  // meeting belongs to a workspace not currently loaded in history. Used by the
  // upcoming-meeting Brief panel where each open item links back to its source.
  const handleOpenMeetingById = useCallback(async (meetingId) => {
    if (!meetingId) return
    setNewMeetingOpen(false)
    const existing = (props.history || []).find((m) => m.id === meetingId)
    if (existing) {
      handleSelectMeeting(existing)
      return
    }
    try {
      const res = await apiFetch(`/meetings/${meetingId}`)
      if (!res.ok) return
      const entry = await res.json()
      handleSelectMeeting(entry)
    } catch { /* swallow — user can retry */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.history])

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

  // Only the meeting owner (recorder) may move it; a fan-out recipient can't (they'd
  // request the owner to move it — deferred). A meeting with no recorder set is your own.
  const canMoveCurrentMeeting = !!currentMeeting && (
    !currentMeeting.recorded_by_user_id ||
    currentMeeting.recorded_by_user_id === props.user?.id
  )

  // Move the current meeting between Personal and a workspace — moves ONLY the caller's
  // copy (backend enforces owner-gate + membership). Updates the list in place; drops it
  // from view if it left the currently-active scope.
  async function moveCurrentMeeting(targetWorkspaceId) {
    const id = currentMeeting?.id
    if (!id) return
    try {
      const res = await apiFetch(`/meetings/${id}/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: targetWorkspaceId || '' }),
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({})))?.detail || 'Could not move meeting'
        notifyStatus({ kind: 'error', message: detail })
        return
      }
      const data = await res.json()
      const newWs = data.workspace_id || null
      const activeWs = activeWorkspaceId || null
      props.setHistory?.((prev) => prev
        .map((m) => (m.id === id ? { ...m, workspace_id: newWs } : m))
        .filter((m) => m.id !== id || (m.workspace_id || null) === activeWs))
      const label = newWs
        ? (workspaces.find((w) => w.id === newWs)?.name ?? 'workspace')
        : 'Personal'
      notifyStatus({ kind: 'success', message: `Moved to ${label}` })
    } catch (e) {
      notifyStatus({ kind: 'error', message: 'Could not move meeting' })
    }
  }

  // Workspace teammates (minus the organizer) — offered as one-click invite
  // suggestions when scheduling a follow-up from a workspace meeting.
  // Harvest attendee emails from connected calendars (Google + Outlook) so the
  // follow-up cards can suggest the people you meet with, not just teammates. Both
  // are pulled in parallel; a provider that isn't connected (404/401) is skipped.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const settled = await Promise.allSettled([
          apiFetch('/calendar/events?days_ahead=14'),
          apiFetch('/ms-calendar/events?days_ahead=14'),
        ])
        const emails = new Set()
        for (const s of settled) {
          if (s.status !== 'fulfilled' || !s.value.ok) continue
          const data = await s.value.json()
          for (const ev of (data.events || [])) {
            for (const e of (ev.attendee_emails || [])) {
              if (e) emails.add(e.toLowerCase())
            }
          }
        }
        if (!cancelled) setCalendarAttendeeEmails([...emails])
      } catch {
        /* best-effort — suggestions still fall back to workspace members */
      }
    })()
    return () => { cancelled = true }
  }, [])

  const suggestedAttendeeEmails = useMemo(() => {
    const own = (props.user?.email || '').toLowerCase()
    // Dedup case-insensitively (a teammate may also be a calendar attendee); keep the
    // first-seen display form, preferring workspace members.
    const byKey = new Map()
    for (const e of [...Object.values(workspaceMemberMap), ...calendarAttendeeEmails]) {
      if (!e) continue
      const key = e.toLowerCase()
      if (key !== own && !byKey.has(key)) byKey.set(key, e)
    }
    return [...byKey.values()]
  }, [workspaceMemberMap, calendarAttendeeEmails, props.user?.email])

  // Which integrations the SuggestedActions card can execute against. Gmail + Calendar
  // ride the Google connection; Jira/Linear/Slack are server-side tokens; Teams is the
  // browser-local recap webhook. Gates each suggested action's tool resolution.
  const actionConnections = useMemo(() => ({
    email: !!props.calendarConnected,
    calendar: !!props.calendarConnected,
    jira: !!props.integrations?.jira_api_token,
    linear: !!props.integrations?.linear_api_key,
    slack: !!props.integrations?.slack_bot_token,
    teams: !!props.integrations?.teams_webhook,
  }), [props.calendarConnected, props.integrations])

  // Trend (cross-meeting intelligence) is its own top-level view, gated on
  // having at least two meetings to compare.
  function handleOpenTrend() {
    if (historyCount < 2) {
      setShowGateDialog(true)
      return
    }
    persistView('intelligence')
  }

  // Page title shown in the topbar island: the focused meeting's name, or the
  // current view's label.
  const pageTitle =
    activeView === 'live'
      ? 'Live meeting'
      : activeView === 'shared'
        ? (props.shareData?.title || 'Shared meeting')
        : activeView === 'intelligence'
          ? 'Trend'
          : activeView === 'knowledge'
            ? 'Knowledge'
            : activeView === 'standin'
              ? 'Stand-in'
              : activeView === 'calendar'
                ? 'Calendar'
                : activeView === 'meeting' && (currentMeeting || props.result)
                  ? deriveDisplayTitle(currentMeeting || { result: props.result })
                  : 'Home'

  // Status island state — single source of truth, derived per active view:
  //  - live: maps the lifted live status (recording/joining → live, processing →
  //    analysing, done → analysed). A live error surfaces in-view, not the island.
  //  - shared: a read-only shared meeting.
  //  - meeting: a manual analysis (analysing while loading, analysed when result
  //    lands, or the persistent error pill keyed off App's `error` state).
  let islandStatus
  if (activeView === 'live') {
    if (liveStatus === 'processing') islandStatus = deriveStatus(null, true)
    else if (liveStatus === 'done') islandStatus = deriveStatus('analysed', false)
    else islandStatus = deriveStatus('live', false) // joining / recording / null
  } else if (activeView === 'shared') {
    islandStatus = deriveStatus('shared', false)
  } else {
    const islandMode = activeView === 'meeting' && props.result ? 'analysed' : null
    const islandError = props.error
      ? { detail: 'Analysis failed', onRetry: props.onRetryAnalysis, onDismiss: props.onDismissError }
      : null
    islandStatus = deriveStatus(islandMode, !!props.loading, {}, islandError)
  }

  // A live notification preempts the base state (except the persistent error pill,
  // which must not be hidden by a transient toast).
  if (notification && islandStatus.state !== 'error') {
    islandStatus = { state: 'notify', detail: notification.message, kind: notification.kind }
  }

  const showHomeNudge =
    props.user &&
    workspacesLoaded &&
    workspaces.length === 0 &&
    !workspaceNudgeDismissed &&
    activeView === 'home'

  return (
    <div
      className={`landing-page dashboard-page min-h-dvh overflow-x-hidden text-[color:var(--landing-text)]${mobileNavOpen ? ' nav-open' : ''}`}
    >
      {/* Mobile drawer backdrop — taps close the nav. */}
      {mobileNavOpen && (
        <div
          className="dashboard-nav-backdrop lg:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      )}
      {!signedOut && (
      <WorkspaceIsland
        user={props.user}
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
        onSaveWorkspacePersona={saveWorkspacePersona}
      />
      )}

      <DashboardTopbar
        title={pageTitle}
        status={islandStatus}
        searchValue={props.historySearch}
        onSearchChange={handleHistorySearchChange}
        signedOut={signedOut}
        onLockedFeature={requestSignIn}
        onMenu={signedOut ? null : () => setMobileNavOpen(true)}
        onBack={activeView === 'meeting' ? goBackFromMeeting : null}
        actions={
          activeView === 'meeting' && props.result && !props.loading ? (
            <MeetingActionsBar
              shareToken={props.shareToken}
              shareCopied={props.shareCopied}
              setShareCopied={props.setShareCopied}
              mdCopied={props.mdCopied}
              copyMarkdown={props.copyMarkdown}
              exportMarkdown={props.exportMarkdown}
              exportPDF={props.exportPDF}
              exportTranscriptPDF={props.exportTranscriptPDF}
              downloadTranscriptTxt={props.downloadTranscriptTxt}
              hasTranscript={!!props.transcript?.trim()}
              exportToSlack={props.exportToSlack}
              exportToNotion={props.exportToNotion}
              exportingSlack={props.exportingSlack}
              exportingNotion={props.exportingNotion}
              integrations={props.integrations}
              canMove={canMoveCurrentMeeting && !!currentMeeting}
              currentWorkspaceId={currentMeeting?.workspace_id || null}
              workspaces={workspaces}
              onMoveMeeting={moveCurrentMeeting}
            />
          ) : null
        }
      />

      <DashboardSidebar
        user={props.user}
        isTestAccount={props.isTestAccount}
        isDemoMode={props.isDemoMode}
        personaPreset={props.personaPreset}
        personaCustomPrompt={props.personaCustomPrompt}
        onSavePersonalPersona={props.onSavePersonalPersona}
        history={props.history || []}
        filteredHistory={filteredHistory}
        activeView={activeView}
        onGoHome={() => persistView('home')}
        onOpenStandin={() => persistView('standin')}
        onOpenCalendar={() => persistView('calendar')}
        onOpenTrend={handleOpenTrend}
        onOpenKnowledge={() => persistView('knowledge')}
        onSelectMeeting={handleSelectMeeting}
        onDeleteMeeting={handleDeleteHistoryEntry}
        currentMeetingId={props.meetingId}
        botActive={props.botStatus && !['done', 'error'].includes(props.botStatus)}
        hasLiveSession={!!props.liveToken}
        liveStatus={liveStatus}
        liveActive={activeView === 'live'}
        onSelectLive={() => persistView('live')}
        setShowIntegrations={props.setShowIntegrations}
        signOut={props.signOut}
        newMeetingOpen={newMeetingOpen}
        setNewMeetingOpen={setNewMeetingOpen}
        newMeetingCollisionPadding={isNarrow ? 12 : 64}
        onOpenNewMeeting={() => (props.prepareNewMeeting ?? props.resetTranscriptWorkspaces)?.()}
        newMeetingPanel={
          <NewMeetingPanel
            {...props}
            workspaces={workspaces}
            onClose={() => setNewMeetingOpen(false)}
            onOpenMeeting={handleOpenMeetingById}
            onCantMakeIt={(m) => { setNewMeetingOpen(false); setStandIn(m) }}
          />
        }
        signedOut={signedOut}
        onLockedFeature={requestSignIn}
      />

      <div className={`dashboard-content ${activeView === 'home' ? 'is-home' : ''}`}>
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

        <main
          className={`relative z-10 mx-auto mt-2 w-full max-w-[92rem] px-5 sm:px-8 ${
            activeView === 'home'
              ? 'flex min-h-0 flex-1 flex-col pb-[var(--dashboard-edge)]'
              : 'pb-28 pt-6'
          }`}
        >
          <div key={activeView} className={`animate-fade-in-up ${activeView === 'home' ? 'flex min-h-0 flex-1 flex-col' : ''}`}>
          {props.viewingSample && (
            <div className="mb-4 flex items-center gap-3 rounded-xl border border-cyan-400/25 bg-cyan-400/[0.08] px-4 py-2.5">
              <span className="inline-flex h-2 w-2 shrink-0 rounded-full bg-cyan-300" />
              <p className="flex-1 text-[13px] text-cyan-100/90">
                <span className="font-semibold">Example data</span>
                <span className="text-cyan-100/60"> — this isn&rsquo;t your history. It&rsquo;s here so you can see what Prism produces.</span>
              </p>
              <button
                type="button"
                onClick={props.clearSample}
                className="shrink-0 rounded-full border border-cyan-300/30 px-3 py-1 text-[12px] font-semibold text-cyan-100 transition hover:bg-cyan-300/15"
              >
                Clear
              </button>
            </div>
          )}
          {(activeView === 'home' || (activeView === 'meeting' && !props.result)) && (
            <StatsCanvas
              history={props.history}
              loadFromHistory={handleSelectMeeting}
              loadSample={props.loadDashboardSample}
              canLoadSample={props.canLoadSample}
              onStartMeeting={() => { props.setInputTab?.('join'); setNewMeetingOpen(true) }}
              onPasteTranscript={() => { props.setInputTab?.('paste'); setNewMeetingOpen(true) }}
              showConnectCalendar={!!props.user && !props.calendarConnected && !props.isTestAccount}
              onConnectCalendar={props.onOpenCalendarSetup}
              selectedMeetingId={props.selectedMeetingId}
              memberEmailMap={workspaceMemberMap}
              currentUserId={props.user?.id}
              onToggleAction={props.toggleHistoryActionItem}
            />
          )}
          {activeView === 'meeting' && (
            <>
              {props.loading && <AnalyzingBanner result={props.result} />}
              {props.loading && !props.result ? (
                <MeetingViewSkeleton />
              ) : (
                <>
                  <Suspense fallback={<SkeletonCard lines={4} tall />}>
                    <MeetingView
                      result={props.result}
                      meeting={currentMeeting}
                      gmailConnected={props.calendarConnected}
                      onToggleActionItem={props.toggleActionItem}
                      transcript={props.transcript}
                      onBack={() => { sessionStorage.removeItem('prism_last_meeting_id'); goBackFromMeeting() }}
                      recordedByEmail={recordedByEmail}
                      workspaceId={activeWorkspaceId}
                      suggestedEmails={suggestedAttendeeEmails}
                      onResultUpdate={persistResultPatch}
                      viewerName={props.user?.user_metadata?.full_name || props.user?.email?.split('@')[0] || ''}
                      actionConnections={actionConnections}
                      teamsWebhook={props.integrations?.teams_webhook || ''}
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
                workspaceId={activeWorkspaceId}
                workspaceName={activeWorkspaceId ? (workspaces.find((ws) => ws.id === activeWorkspaceId)?.name ?? null) : null}
                actionConnections={actionConnections}
                suggestedEmails={suggestedAttendeeEmails}
                teamsWebhook={props.integrations?.teams_webhook || ''}
              />
            </Suspense>
          )}
          {activeView === 'knowledge' && (
            <Suspense fallback={<SkeletonCard lines={4} tall />}>
              <KnowledgeBase
                workspaceId={activeWorkspaceId}
                workspaceName={activeWorkspaceId ? (workspaces.find((ws) => ws.id === activeWorkspaceId)?.name ?? null) : null}
              />
            </Suspense>
          )}
          {activeView === 'live' && props.liveToken && (
            <LiveMeetingView token={props.liveToken} onStatusChange={setLiveStatus} />
          )}
          {activeView === 'shared' && (
            props.shareLoading ? (
              <div className="mx-auto flex max-w-2xl flex-col items-center gap-3 py-16">
                <div className="h-8 w-8 animate-pulse rounded-xl" style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }} />
                <p className="text-xs text-white/40">Loading shared meeting…</p>
              </div>
            ) : props.shareData ? (
              <Suspense fallback={<SkeletonCard lines={4} tall />}>
                <MeetingView
                  result={props.shareData.result || {}}
                  meeting={{ title: props.shareData.title, date: props.shareData.date }}
                  readOnly
                  transcript={props.shareData.transcript || ''}
                />
                <section className="mt-8 rounded-xl border border-white/[0.08] bg-white/[0.02] px-5 py-6 text-center">
                  <p className="text-sm font-semibold text-white">Analyze your own meetings</p>
                  <p className="mt-1 text-xs text-white/85">Paste any transcript — 8 AI agents produce a full analysis in seconds.</p>
                  <a
                    href={`${window.location.origin}/`}
                    className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-full border border-cyan-400/30 bg-cyan-400/[0.10] px-4 text-[13px] font-semibold text-cyan-200 transition hover:border-cyan-400/50 hover:bg-cyan-400/[0.16]"
                  >
                    Try PrismAI free →
                  </a>
                </section>
              </Suspense>
            ) : (
              <div className="mx-auto max-w-2xl py-16 text-center">
                <p className="text-sm text-white/50">This shared meeting could not be found or has expired.</p>
              </div>
            )
          )}
          {activeView === 'standin' && (
            <Suspense fallback={<SkeletonCard lines={4} tall />}>
              <ProxyProfile
                user={props.user}
                workspaceId={activeWorkspaceId}
                workspaceName={activeWorkspaceId ? (workspaces.find((ws) => ws.id === activeWorkspaceId)?.name ?? null) : null}
                onOpenMeeting={handleOpenMeetingById}
              />
            </Suspense>
          )}
          {activeView === 'calendar' && (
            <Suspense fallback={<SkeletonCard lines={4} tall />}>
              <CalendarView
                history={props.history}
                onOpenMeeting={handleOpenMeetingById}
                workspaceName={activeWorkspaceId ? (workspaces.find((ws) => ws.id === activeWorkspaceId)?.name ?? null) : null}
                calendarConnected={props.calendarConnected}
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
                activeSession={scopedSessions[0] || null}
                pastSessions={scopedSessions}
                onPastSessionsChange={setPastSessions}
                onThreadSaved={refreshPastSessions}
                transcript={props.transcript}
                result={props.result}
                onResultUpdate={persistResultPatch}
                onCorrectApplied={onCorrectApplied}
                onExportTranscriptPDF={props.exportTranscriptPDF}
                onDownloadTranscriptTxt={props.downloadTranscriptTxt}
                isSignedIn={!!props.user}
                personaPreset={props.personaPreset}
                personaCustomPrompt={props.personaCustomPrompt}
                workspaceDefaultPersona={workspaces.find(w => w.id === activeWorkspaceId)?.default_persona || null}
                onSavePersona={props.onSavePersonalPersona}
                activeWorkspaceId={activeWorkspaceId}
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

      {standIn && (
        <StandInComposer meeting={standIn} user={props.user} onClose={() => setStandIn(null)} />
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

      <Dialog open={showSignInGate} onOpenChange={setShowSignInGate}>
        <DialogContent className="dashboard-body-font border-[#2f2f2f] bg-[#0f0f11] text-white sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold text-white">Sign in to access this</DialogTitle>
            <DialogDescription className="mt-2 text-sm leading-5 text-white/58">
              Create a free account to analyze your own meetings, save history, and use the full dashboard.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-3 flex flex-col gap-2">
            <button
              type="button"
              onClick={() => { setShowSignInGate(false); props.onSignIn?.() }}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-[#191c1e] transition hover:bg-white/90"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
              </svg>
              Sign in with Google
            </button>
            <button
              type="button"
              onClick={() => setShowSignInGate(false)}
              className="rounded-full px-4 py-1.5 text-sm font-medium text-white/55 transition hover:text-white/80"
            >
              Not now
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
