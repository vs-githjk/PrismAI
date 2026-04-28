import { lazy, Suspense } from 'react'
import {
  BarChart3,
  Bot,
  CalendarClock,
  Download,
  FileAudio,
  History,
  Link,
  Loader2,
  LogIn,
  LogOut,
  Mic,
  PanelRight,
  Plus,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  UserCircle,
} from 'lucide-react'
import AgentTags from './AgentTags'
import HealthScoreCard from './HealthScoreCard'
import SummaryCard from './SummaryCard'
import ActionItemsCard from './ActionItemsCard'
import DecisionsCard from './DecisionsCard'
import SentimentCard from './SentimentCard'
import EmailCard from './EmailCard'
import CalendarCard from './CalendarCard'
import SkeletonCard from './SkeletonCard'
import ErrorCard from './ErrorCard'
import UpcomingMeetings from './UpcomingMeetings'

const ChatPanel = lazy(() => import('./ChatPanel'))
const ProactiveSuggestions = lazy(() => import('./ProactiveSuggestions'))
const ScoreTrendChart = lazy(() => import('./ScoreTrendChart'))
const CrossMeetingInsights = lazy(() => import('./CrossMeetingInsights'))

const tabs = [
  { id: 'join', label: 'Join', icon: Link },
  { id: 'paste', label: 'Paste', icon: Send },
  { id: 'record', label: 'Record', icon: Mic },
  { id: 'upload', label: 'Upload', icon: FileAudio },
]

function MetricTile({ label, value, tone = 'sky' }) {
  const tones = {
    sky: 'border-sky-400/20 bg-sky-400/10 text-sky-100',
    emerald: 'border-emerald-400/20 bg-emerald-400/10 text-emerald-100',
    violet: 'border-violet-400/20 bg-violet-400/10 text-violet-100',
  }

  return (
    <div className={`rounded-lg border px-3 py-2 ${tones[tone]}`}>
      <p className="text-[10px] uppercase tracking-[0.16em] opacity-60">{label}</p>
      <p className="mt-1 text-sm font-semibold">{value}</p>
    </div>
  )
}

function EmptyPanel({ onDemo, inputModeLabel }) {
  return (
    <div className="flex min-h-[280px] flex-col items-center justify-center border border-dashed border-black/20 bg-[#f7f8fa] px-6 text-center">
      <Sparkles className="h-7 w-7 text-[#191c1e]" aria-hidden="true" />
      <h2 className="mt-4 text-sm font-bold uppercase tracking-[0.16em] text-[#191c1e]">No analysis yet</h2>
      <p className="mt-2 max-w-sm text-sm leading-6 text-[#5f666d]">
        Start from {inputModeLabel.toLowerCase()} or load the sample meeting to populate every agent output.
      </p>
      <button
        type="button"
        onClick={onDemo}
        className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg border border-black bg-black px-4 text-sm font-semibold text-white transition hover:bg-[#202326]"
      >
        <Sparkles className="h-4 w-4" aria-hidden="true" />
        Run demo
      </button>
    </div>
  )
}

function ExportMenu({ props }) {
  if (!props.showExportMenu) return null

  return (
    <div
      className="absolute right-0 top-10 z-40 w-48 overflow-hidden rounded-lg border border-black bg-white shadow-xl"
      data-export-menu
    >
      <button type="button" onClick={() => { props.copyMarkdown(); props.setShowExportMenu(false) }} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs text-[#191c1e] hover:bg-[#f3f4f6]">
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        {props.mdCopied ? 'Copied' : 'Copy Markdown'}
      </button>
      <button type="button" onClick={() => { props.exportMarkdown(); props.setShowExportMenu(false) }} className="flex w-full items-center gap-2 border-t border-black/10 px-4 py-2.5 text-left text-xs text-[#191c1e] hover:bg-[#f3f4f6]">
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        Download .md
      </button>
      <button type="button" onClick={() => { props.exportPDF(); props.setShowExportMenu(false) }} className="flex w-full items-center gap-2 border-t border-black/10 px-4 py-2.5 text-left text-xs text-[#191c1e] hover:bg-[#f3f4f6]">
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        Download PDF
      </button>
      <button type="button" onClick={() => { props.exportToSlack(); props.setShowExportMenu(false) }} disabled={props.exportingSlack} className="flex w-full items-center gap-2 border-t border-black/10 px-4 py-2.5 text-left text-xs text-[#191c1e] hover:bg-[#f3f4f6] disabled:opacity-50">
        <Send className="h-3.5 w-3.5" aria-hidden="true" />
        {props.exportingSlack ? 'Sending' : props.integrations.slack_webhook ? 'Send to Slack' : 'Connect Slack'}
      </button>
      <button type="button" onClick={() => { props.exportToNotion(); props.setShowExportMenu(false) }} disabled={props.exportingNotion} className="flex w-full items-center gap-2 border-t border-black/10 px-4 py-2.5 text-left text-xs text-[#191c1e] hover:bg-[#f3f4f6] disabled:opacity-50">
        <PanelRight className="h-3.5 w-3.5" aria-hidden="true" />
        {props.exportingNotion ? 'Exporting' : props.integrations.notion_token ? 'Export to Notion' : 'Connect Notion'}
      </button>
    </div>
  )
}

function WorkspacePanel({ props }) {
  const busyBot = props.botStatus && !['done', 'error'].includes(props.botStatus)

  return (
    <section className="flex min-h-[256px] flex-col border border-black bg-[#f3f4f6]" data-node-id="4590:257">
      <div className="flex items-center justify-between border-b border-black/15 px-4 py-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#4c4546]">Structural Element A</p>
          <h2 className="mt-1 text-base font-bold text-[#191c1e]">Meeting intake</h2>
        </div>
        <MetricTile label="Transcript" value={props.transcriptStats.words ? `${props.transcriptStats.words} words` : 'Empty'} />
      </div>

      <div className="grid grid-cols-4 border-b border-black/15">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            type="button"
            key={id}
            onClick={() => props.setInputTab(id)}
            className={`flex min-h-11 items-center justify-center gap-2 border-r border-black/10 px-2 text-xs font-semibold last:border-r-0 ${props.inputTab === id ? 'bg-black text-white' : 'text-[#4c4546] hover:bg-white'}`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
      </div>

      <div className="flex-1 p-4">
        {props.inputTab === 'join' && (
          <div className="space-y-3">
            {props.calendarConnected && props.user && (
              <Suspense fallback={null}>
                <UpcomingMeetings onJoin={(url) => props.setMeetingUrl(url)} />
              </Suspense>
            )}
            <input
              type="url"
              value={props.meetingUrl}
              onChange={(event) => props.setMeetingUrl(event.target.value)}
              disabled={busyBot}
              placeholder="https://meet.google.com/... or zoom.us/..."
              className="min-h-11 w-full rounded-lg border border-black bg-white px-3 text-sm text-[#191c1e] outline-none focus:ring-2 focus:ring-black/20"
            />
            {props.botStatus && (
              <div className="rounded-lg border border-black/15 bg-white px-3 py-2 text-xs text-[#4c4546]">
                {busyBot && <Loader2 className="mr-2 inline h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                {props.botStatus === 'joining' && 'Bot is joining the meeting'}
                {props.botStatus === 'recording' && 'Bot is recording'}
                {props.botStatus === 'processing' && 'Meeting ended, processing transcript'}
                {props.botStatus === 'done' && 'Meeting capture complete'}
                {props.botStatus === 'error' && props.botError}
              </div>
            )}
            {props.botStatus === 'error' && props.botError && <ErrorCard message={props.botError} onRetry={props.joinMeeting} />}
            <button
              type="button"
              onClick={busyBot ? props.cancelBot : props.joinMeeting}
              disabled={!props.meetingUrl.trim() && !busyBot}
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-black bg-black px-4 text-sm font-semibold text-white transition hover:bg-[#202326] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busyBot ? <Square className="h-4 w-4" aria-hidden="true" /> : <Bot className="h-4 w-4" aria-hidden="true" />}
              {busyBot ? 'Stop bot' : 'Join meeting'}
            </button>
          </div>
        )}

        {props.inputTab === 'paste' && (
          <div className="space-y-3">
            <textarea
              value={props.transcript}
              onChange={(event) => props.setTranscriptForTab(event.target.value, 'paste')}
              rows={9}
              placeholder="Paste transcript with speaker labels..."
              className="min-h-[190px] w-full resize-none rounded-lg border border-black bg-white px-3 py-3 font-mono text-xs leading-6 text-[#191c1e] outline-none focus:ring-2 focus:ring-black/20"
            />
            <AnalyzeButton props={props} />
          </div>
        )}

        {props.inputTab === 'record' && (
          <div className="space-y-3">
            <button
              type="button"
              onClick={props.recording ? props.stopRecording : props.startRecording}
              disabled={!props.micSupported}
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-black bg-white px-4 text-sm font-semibold text-[#191c1e] transition hover:bg-[#f8f9fb] disabled:opacity-45"
            >
              <Mic className="h-4 w-4" aria-hidden="true" />
              {props.recording ? 'Stop recording' : props.micSupported ? 'Start recording' : 'Recording unavailable'}
            </button>
            <textarea
              value={props.transcript}
              onChange={(event) => props.setTranscriptForTab(event.target.value, 'record')}
              rows={7}
              placeholder="Transcript appears here while recording..."
              className="min-h-[154px] w-full resize-none rounded-lg border border-black bg-white px-3 py-3 font-mono text-xs leading-6 text-[#191c1e] outline-none focus:ring-2 focus:ring-black/20"
            />
            <AnalyzeButton props={props} />
          </div>
        )}

        {props.inputTab === 'upload' && (
          <div className="space-y-3">
            <button
              type="button"
              onClick={() => props.fileInputRef.current?.click()}
              disabled={props.transcribing}
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-black bg-white px-4 text-sm font-semibold text-[#191c1e] transition hover:bg-[#f8f9fb] disabled:opacity-45"
            >
              {props.transcribing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <FileAudio className="h-4 w-4" aria-hidden="true" />}
              {props.transcribing ? 'Transcribing' : 'Choose audio file'}
            </button>
            <input ref={props.fileInputRef} type="file" accept="audio/*,.mp3,.wav,.m4a,.ogg,.webm" className="hidden" onChange={props.handleAudioUpload} />
            <textarea
              value={props.transcript}
              onChange={(event) => props.setTranscriptForTab(event.target.value, 'upload')}
              rows={7}
              placeholder="Transcript appears here after upload..."
              className="min-h-[154px] w-full resize-none rounded-lg border border-black bg-white px-3 py-3 font-mono text-xs leading-6 text-[#191c1e] outline-none focus:ring-2 focus:ring-black/20"
            />
            <AnalyzeButton props={props} />
          </div>
        )}
      </div>
    </section>
  )
}

function AnalyzeButton({ props }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-[#6b7280]">
        {props.transcriptStats.words ? `${props.transcriptStats.words} words / ${props.transcriptSpeakerCount || 0} speakers` : 'No transcript'}
      </span>
      <button
        type="button"
        onClick={props.loading ? props.cancelActiveAnalysis : props.handleAnalyzeClick}
        disabled={!props.transcript.trim() && !props.loading}
        className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-black bg-black px-4 text-sm font-semibold text-white transition hover:bg-[#202326] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {props.loading ? <Square className="h-4 w-4" aria-hidden="true" /> : <Sparkles className="h-4 w-4" aria-hidden="true" />}
        {props.loading ? 'Cancel' : 'Analyze'}
      </button>
    </div>
  )
}

function ResultsPanel({ props }) {
  return (
    <section className="flex min-h-[256px] flex-col border border-black bg-[#f3f4f6]" data-node-id="4590:260">
      <div className="flex items-center justify-between border-b border-black/15 px-4 py-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#4c4546]">Structural Element B</p>
          <h2 className="mt-1 text-base font-bold text-[#191c1e]">Agent outputs</h2>
        </div>
        <MetricTile label="Agents" value={`${props.result?.agents_run?.length || 7} ready`} tone="emerald" />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {props.loading ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-black bg-white p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-[#191c1e]">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Running PrismAI agents
              </div>
              <p className="mt-2 text-xs leading-5 text-[#6b7280]">Summary, decisions, action items, sentiment, email, calendar, and health score are streaming in.</p>
            </div>
            <SkeletonCard lines={2} />
            <SkeletonCard lines={3} />
          </div>
        ) : props.result ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-black bg-white p-3">
              <AgentTags agents={props.result.agents_run || []} />
              {props.analysisTime && <span className="text-xs text-[#6b7280]">{props.analysisTime}s / ~{Math.round(props.analysisTime * 1.8 + 20)} min saved</span>}
            </div>
            <Suspense fallback={<SkeletonCard lines={2} />}>
              <ProactiveSuggestions result={props.result} transcript={props.transcript} />
            </Suspense>
            <HealthScoreCard healthScore={props.result.health_score} />
            <SummaryCard summary={props.result.summary} />
            <ActionItemsCard actionItems={props.result.action_items} onToggle={props.toggleActionItem} />
            <DecisionsCard decisions={props.result.decisions} />
            <SentimentCard sentiment={props.result.sentiment} />
            <EmailCard email={props.result.follow_up_email} />
            <CalendarCard suggestion={props.result.calendar_suggestion} />
          </div>
        ) : (
          <EmptyPanel onDemo={props.startDemo} inputModeLabel={props.inputModeMeta.label} />
        )}
      </div>
    </section>
  )
}

function ReviewPanel({ props }) {
  return (
    <section className="flex min-h-[256px] flex-col border border-black bg-[#f3f4f6]" data-node-id="4590:263">
      <div className="flex items-center justify-between border-b border-black/15 px-4 py-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#4c4546]">Structural Element C</p>
          <h2 className="mt-1 text-base font-bold text-[#191c1e]">Review and history</h2>
        </div>
        <MetricTile label="History" value={`${props.history.length} saved`} tone="violet" />
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <div className="rounded-lg border border-black bg-white p-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-bold text-[#191c1e]">Actions</h3>
            <div className="relative">
              <button
                type="button"
                onClick={() => props.setShowExportMenu((value) => !value)}
                disabled={!props.result}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-black px-3 text-xs font-semibold text-[#191c1e] disabled:opacity-40"
              >
                <Download className="h-3.5 w-3.5" aria-hidden="true" />
                Export
              </button>
              <ExportMenu props={props} />
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button type="button" onClick={props.startDemo} className="min-h-10 rounded-lg border border-black/20 bg-[#f8f9fb] px-3 text-xs font-semibold text-[#191c1e] hover:bg-[#f3f4f6]">Demo</button>
            <button type="button" onClick={() => { sessionStorage.setItem('prism_new_meeting', '1'); props.clearWorkspaceState() }} className="min-h-10 rounded-lg border border-black/20 bg-[#f8f9fb] px-3 text-xs font-semibold text-[#191c1e] hover:bg-[#f3f4f6]">New</button>
            <button type="button" onClick={() => props.setShowIntegrations(true)} className="min-h-10 rounded-lg border border-black/20 bg-[#f8f9fb] px-3 text-xs font-semibold text-[#191c1e] hover:bg-[#f3f4f6]">Integrations</button>
            <button type="button" onClick={() => { window.location.href = '/' }} className="min-h-10 rounded-lg border border-black/20 bg-[#f8f9fb] px-3 text-xs font-semibold text-[#191c1e] hover:bg-[#f3f4f6]">Old view</button>
          </div>
          {props.shareToken && (
            <button
              type="button"
              onClick={() => {
                const url = `${window.location.origin}${window.location.pathname}#share/${props.shareToken}`
                navigator.clipboard.writeText(url).then(() => {
                  props.setShareCopied(true)
                  setTimeout(() => props.setShareCopied(false), 2000)
                })
              }}
              className="mt-2 min-h-10 w-full rounded-lg border border-black bg-black px-3 text-xs font-semibold text-white"
            >
              {props.shareCopied ? 'Share link copied' : 'Copy share link'}
            </button>
          )}
        </div>

        {props.history.length > 0 && (
          <div className="rounded-lg border border-black bg-white p-3">
            <div className="mb-2 flex items-center gap-2 text-sm font-bold text-[#191c1e]">
              <History className="h-4 w-4" aria-hidden="true" />
              Recent meetings
            </div>
            <div className="space-y-2">
              {props.history.slice(0, 5).map((entry) => (
                <button
                  type="button"
                  key={entry.id}
                  onClick={() => props.loadFromHistory(entry)}
                  className="w-full rounded-lg border border-black/10 bg-[#f8f9fb] px-3 py-2 text-left hover:bg-[#f3f4f6]"
                >
                  <p className="line-clamp-1 text-xs font-semibold text-[#191c1e]">{entry.title}</p>
                  <p className="mt-1 text-[10px] text-[#6b7280]">{new Date(entry.date).toLocaleDateString()}</p>
                </button>
              ))}
            </div>
          </div>
        )}

        {props.user && props.history.length > 1 && (
          <Suspense fallback={null}>
            <ScoreTrendChart history={props.history} onSelect={props.loadFromHistory} />
            <CrossMeetingInsights history={props.history} insights={props.crossMeetingInsights} onSelect={props.loadFromHistory} />
          </Suspense>
        )}

        <div className="rounded-lg border border-black bg-white p-3">
          <div className="mb-2 flex items-center gap-2 text-sm font-bold text-[#191c1e]">
            <Bot className="h-4 w-4" aria-hidden="true" />
            Chat
          </div>
          {props.result ? (
            <Suspense fallback={<SkeletonCard lines={2} />}>
              <ChatPanel
                key={props.sessionId}
                meetingId={props.meetingId}
                initialMessages={props.initialMessages}
                transcript={props.transcript}
                result={props.result}
                onResultUpdate={(updated) => props.setResult((result) => ({ ...result, ...updated }))}
                isSignedIn={Boolean(props.user)}
                compact
              />
            </Suspense>
          ) : (
            <p className="text-xs leading-5 text-[#6b7280]">Analyze a meeting to unlock follow-up questions.</p>
          )}
        </div>
      </div>
    </section>
  )
}

export default function DashboardMcpPage(props) {
  return (
    <div className="min-h-dvh bg-[#f8f9fb] font-['Inter_Variable',Inter,sans-serif] text-[#191c1e]">
      <header className="sticky top-0 z-30 flex min-h-[82px] items-center justify-between border-b-2 border-black bg-white px-5 sm:px-8">
        <button type="button" onClick={() => { sessionStorage.setItem('prism_new_meeting', '1'); props.clearWorkspaceState() }} className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center border-2 border-black text-[11px] font-bold">PA</span>
          <span className="text-lg font-black uppercase tracking-[0.16em]">PrismAI</span>
        </button>

        <div className="flex items-center gap-2">
          {props.authReady && props.user ? (
            <button type="button" onClick={props.signOut} className="hidden min-h-10 items-center gap-2 rounded-lg border border-black px-3 text-xs font-semibold sm:inline-flex">
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Sign out
            </button>
          ) : (
            <button type="button" onClick={props.signInWithGoogle} className="hidden min-h-10 items-center gap-2 rounded-lg border border-black px-3 text-xs font-semibold sm:inline-flex">
              <LogIn className="h-4 w-4" aria-hidden="true" />
              Sign in
            </button>
          )}
          <UserCircle className="h-5 w-5" aria-label="Profile" />
        </div>
      </header>

      {props.isDemoMode && (
        <div className="border-b border-black/20 bg-white px-5 py-3 sm:px-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#4c4546]">Demo mode active</p>
            <button type="button" onClick={props.exitDemoMode} className="min-h-10 rounded-lg border border-black px-3 text-xs font-semibold">Use my transcript</button>
          </div>
        </div>
      )}

      <main className="grid gap-5 px-5 pb-36 pt-8 lg:grid-cols-3 sm:px-8">
        <WorkspacePanel props={props} />
        <ResultsPanel props={props} />
        <ReviewPanel props={props} />
      </main>

      <nav className="fixed bottom-5 left-1/2 z-30 h-[120px] w-[180px] -translate-x-1/2" aria-label="Dashboard shortcuts" data-node-id="4590:266">
        <button type="button" onClick={() => props.setShowHistory((value) => !value)} className="absolute bottom-5 left-0 flex h-12 w-12 items-center justify-center rounded-full border border-black bg-white shadow-lg" aria-label="Toggle history">
          <History className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>
        <button type="button" onClick={() => { sessionStorage.setItem('prism_new_meeting', '1'); props.clearWorkspaceState() }} className="absolute bottom-10 left-1/2 flex h-20 w-20 -translate-x-1/2 items-center justify-center rounded-full border-2 border-black bg-black text-white shadow-2xl" aria-label="New meeting">
          <Plus className="h-6 w-6" aria-hidden="true" />
        </button>
        <button type="button" onClick={() => { window.location.href = '/' }} className="absolute bottom-5 right-0 flex h-12 w-12 items-center justify-center rounded-full border border-black bg-white shadow-lg" aria-label="Switch to current dashboard">
          <RotateCcw className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>
      </nav>

      <div className="fixed bottom-4 right-4 hidden rounded-lg border border-black bg-white px-3 py-2 text-xs font-semibold text-[#191c1e] lg:flex lg:items-center lg:gap-2">
        <BarChart3 className="h-4 w-4" aria-hidden="true" />
        Figma MCP dashboard draft
      </div>
    </div>
  )
}
