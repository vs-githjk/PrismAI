import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  DoorOpen,
  Home,
  Lock,
  LogIn,
  Plus,
  TrendingUp,
  Trash2,
  UserCircle,
} from 'lucide-react'
import { deriveDisplayTitle } from '../../lib/insights'
import { formatHistoryDate, IntegrationsIcon } from './chrome'
import PersonaChip from '../PersonaChip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu'

// Group meetings into Today / This week / Earlier, newest first.
function groupMeetings(entries) {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const weekAgo = startOfToday - 6 * 24 * 60 * 60 * 1000
  const buckets = { Today: [], 'This week': [], Earlier: [] }
  for (const entry of entries) {
    const t = new Date(entry?.date).getTime()
    if (!Number.isNaN(t) && t >= startOfToday) buckets.Today.push(entry)
    else if (!Number.isNaN(t) && t >= weekAgo) buckets['This week'].push(entry)
    else buckets.Earlier.push(entry)
  }
  return ['Today', 'This week', 'Earlier']
    .map((label) => ({ label, items: buckets[label] }))
    .filter((g) => g.items.length > 0)
}

const navItemBase =
  'group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-[14.5px] font-medium transition-colors'

// Sub-label for the pinned live row, by polled live status.
const LIVE_LABELS = {
  joining: 'Joining…',
  recording: 'Live now',
  processing: 'Analysing…',
  error: 'Connection error',
}

export default function DashboardSidebar(props) {
  const {
    user,
    isTestAccount,
    isDemoMode,
    // Personal persona picker lives in the account dropdown (workspace
    // settings — including the workspace default persona — moved to WorkspaceIsland).
    personaPreset,
    personaCustomPrompt,
    onSavePersonalPersona,
    history = [],
    filteredHistory = [],
    activeView,
    onGoHome,
    onOpenTrend,
    onOpenKnowledge,
    onSelectMeeting,
    onDeleteMeeting,
    currentMeetingId,
    botActive,
    // Live session (token-driven live sub-view). When active, a single row is
    // pinned to the very top of the meetings list with a blinking red dot. It
    // collapses (disappears) once the meeting ends + analysis is done — the saved
    // meeting then shows as a normal history row.
    hasLiveSession = false,
    liveStatus = null,
    liveActive = false,
    onSelectLive,
    setShowIntegrations,
    signOut,
    newMeetingOpen,
    setNewMeetingOpen,
    onOpenNewMeeting,
    newMeetingPanel,
    // Unauthenticated shell: a signed-out viewer (e.g. someone who opened a
    // live/share link) sees the chrome with every feature locked. Clicking a
    // locked feature calls onLockedFeature, which opens the sign-in gate.
    signedOut = false,
    onLockedFeature,
  } = props

  const groups = useMemo(() => groupMeetings(filteredHistory), [filteredHistory])
  const onHome = activeView === 'home'
  const onTrend = activeView === 'intelligence'
  const onKnowledge = activeView === 'knowledge'

  // Collapsible date groups (Today / This week / Earlier).
  const [collapsedGroups, setCollapsedGroups] = useState(() => new Set())
  const toggleGroup = (label) =>
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      next.has(label) ? next.delete(label) : next.add(label)
      return next
    })

  // Keep the focused meeting visible when it changes.
  const activeRowRef = useRef(null)
  useEffect(() => {
    activeRowRef.current?.scrollIntoView({ block: 'nearest' })
  }, [currentMeetingId, activeView])

  const accountName =
    user?.email?.split('@')[0] || (isDemoMode ? 'Demo session' : 'Guest')
  const accountSub = user?.email || (isTestAccount ? 'Test run' : 'Not signed in')

  return (
    <aside className="dashboard-sidebar dashboard-island flex flex-col" aria-label="Dashboard navigation">
      {/* Pinned: Home + Trend + Knowledge. When signed out, each is locked and
          clicking opens the sign-in gate instead of navigating. */}
      <div className="space-y-1 px-3 pt-4">
        {[
          { key: 'home', label: 'Home', Icon: Home, active: onHome, onClick: onGoHome },
          { key: 'trend', label: 'Trend', Icon: TrendingUp, active: onTrend, onClick: onOpenTrend },
          { key: 'knowledge', label: 'Knowledge', Icon: BookOpen, active: onKnowledge, onClick: onOpenKnowledge },
        ].map(({ key, label, Icon, active, onClick }) => (
          <button
            key={key}
            type="button"
            onClick={signedOut ? () => onLockedFeature?.(label) : onClick}
            aria-disabled={signedOut || undefined}
            className={`${navItemBase} ${
              active && !signedOut
                ? 'bg-cyan-400/[0.10] text-cyan-50 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.20)]'
                : signedOut
                  ? 'text-white/40 hover:bg-white/[0.04] hover:text-white/60'
                  : 'text-white/70 hover:bg-white/[0.06] hover:text-white hover:shadow-[inset_0_0_0_1px_rgba(255,255,255,0.06)]'
            }`}
          >
            <Icon className="h-[18px] w-[18px] shrink-0" />
            {label}
            {signedOut && <Lock className="ml-auto h-3.5 w-3.5 shrink-0 text-white/25" aria-hidden="true" />}
          </button>
        ))}
      </div>

      {/* Meetings section — New meeting button sits beside the heading */}
      <div className="mt-4 flex items-center justify-between px-5 pb-1.5">
        <p className="text-[11.5px] font-semibold uppercase tracking-[0.14em] text-white/40">
          Meetings
        </p>
        {signedOut ? (
          <button
            type="button"
            aria-label="New meeting"
            title="Sign in to start a meeting"
            onClick={() => onLockedFeature?.('New meeting')}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-white/30 transition hover:bg-white/[0.06] hover:text-white/50"
          >
            <Plus className="h-[18px] w-[18px]" aria-hidden="true" />
          </button>
        ) : (
          <DropdownMenu
            open={newMeetingOpen}
            onOpenChange={(open) => {
              setNewMeetingOpen?.(open)
              if (open) onOpenNewMeeting?.()
            }}
          >
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="New meeting"
                title="New meeting"
                className="flex h-7 w-7 items-center justify-center rounded-lg text-cyan-200/80 transition hover:bg-cyan-400/[0.14] hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/25"
              >
                <Plus className="h-[18px] w-[18px]" aria-hidden="true" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              side="bottom"
              align="start"
              sideOffset={10}
              collisionPadding={12}
              modal={false}
              className="dashboard-island dashboard-body-font max-h-[calc(100dvh_-_25rem)] w-[340px] overflow-auto p-0"
              onCloseAutoFocus={(e) => e.preventDefault()}
            >
              {newMeetingPanel}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2">
        {/* Pinned live session — sits above all history while the meeting is in
            progress / analysing. Disappears once done (the saved meeting then
            shows as an ordinary history row below). */}
        {hasLiveSession && liveStatus !== 'done' && (
          <button
            type="button"
            onClick={() => onSelectLive?.()}
            aria-current={liveActive ? 'page' : undefined}
            className={`mb-2 flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition ${
              liveActive
                ? 'bg-rose-400/[0.10] shadow-[inset_0_0_0_1px_rgba(244,63,94,0.22)]'
                : 'hover:bg-white/[0.06] shadow-[inset_0_0_0_1px_rgba(244,63,94,0.12)]'
            }`}
          >
            <span className="status-island-livedot relative h-2 w-2 shrink-0 rounded-full bg-rose-500" aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className={`block truncate text-[14px] font-semibold leading-5 ${liveActive ? 'text-rose-100' : 'text-white/85'}`}>
                Live meeting
              </span>
              <span className="block truncate text-[11.5px] leading-4 text-rose-300/80">
                {LIVE_LABELS[liveStatus] || 'Connecting…'}
              </span>
            </span>
          </button>
        )}
        {!user && !isDemoMode ? (
          <p className="px-2 py-6 text-center text-[13px] leading-5 text-white/42">
            Meeting history appears after you sign in.
          </p>
        ) : history.length === 0 ? (
          <p className="px-2 py-6 text-center text-[13px] leading-5 text-white/42">
            Saved meetings will appear here.
          </p>
        ) : groups.length === 0 ? (
          <p className="px-2 py-6 text-center text-[13px] leading-5 text-white/42">
            No matching meetings.
          </p>
        ) : (
          groups.map((group) => {
            const collapsed = collapsedGroups.has(group.label)
            return (
            <div key={group.label} className="mb-1.5">
              <button
                type="button"
                onClick={() => toggleGroup(group.label)}
                aria-expanded={!collapsed}
                className="group/hdr flex w-full items-center gap-1 rounded-md px-2 pb-1 pt-2.5 text-left transition hover:bg-white/[0.03]"
              >
                <ChevronRight
                  className={`h-3 w-3 shrink-0 text-white/30 transition-transform group-hover/hdr:text-white/55 ${collapsed ? '' : 'rotate-90'}`}
                  aria-hidden="true"
                />
                <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-white/30 group-hover/hdr:text-white/45">
                  {group.label}
                </span>
                <span className="ml-1 text-[10px] font-medium text-white/20">{group.items.length}</span>
              </button>
              {!collapsed && group.items.map((entry) => {
                const isActive = entry.id === currentMeetingId && activeView === 'meeting'
                const isLive = botActive && entry.id === currentMeetingId
                return (
                  <div
                    key={entry.id}
                    ref={isActive ? activeRowRef : null}
                    className={`group flex items-center rounded-lg pr-1 transition ${
                      isActive
                        ? 'bg-cyan-400/[0.10] shadow-[inset_0_0_0_1px_rgba(34,211,238,0.18)]'
                        : 'hover:bg-white/[0.06]'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelectMeeting(entry)}
                      aria-current={isActive ? 'page' : undefined}
                      className="flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2.5 py-2 text-left"
                    >
                      {isLive ? (
                        <span
                          className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-cyan-400"
                          aria-hidden="true"
                        />
                      ) : (
                        <span
                          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                            isActive ? 'bg-cyan-300' : 'bg-white/20'
                          }`}
                          aria-hidden="true"
                        />
                      )}
                      <span className="min-w-0 flex-1">
                        <span
                          className={`block truncate text-[14px] font-medium leading-5 ${
                            isActive ? 'text-cyan-100' : 'text-white/80'
                          }`}
                        >
                          {deriveDisplayTitle(entry)}
                          {isLive && (
                            <span className="ml-1.5 text-[10.5px] font-semibold text-cyan-300">
                              · live
                            </span>
                          )}
                        </span>
                        <span className="block truncate text-[11.5px] leading-4 text-white/40">
                          {formatHistoryDate(entry.date)}
                        </span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => onDeleteMeeting(entry)}
                      aria-label={`Delete ${deriveDisplayTitle(entry)}`}
                      className="flex h-7 w-7 shrink-0 items-center justify-center text-white/25 opacity-0 transition hover:text-red-300 focus-visible:opacity-100 group-hover:opacity-100"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                )
              })}
            </div>
            )
          })
        )}
      </div>

      {/* Footer: account block — replaced by a Sign in CTA when signed out. */}
      <div className="border-t border-white/[0.06] p-2.5">
        {signedOut ? (
          <button
            type="button"
            onClick={() => onLockedFeature?.('Account')}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-cyan-400/30 bg-cyan-400/[0.10] px-2.5 py-2.5 text-[13px] font-semibold text-cyan-200 transition hover:border-cyan-400/50 hover:bg-cyan-400/[0.16]"
          >
            <LogIn className="h-4 w-4 shrink-0" aria-hidden="true" />
            Sign in
          </button>
        ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition hover:bg-white/[0.05]"
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-cyan-400/[0.14] text-cyan-200">
                <UserCircle className="h-6 w-6" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-semibold text-white/88">
                  {accountName}
                </span>
                <span className="block truncate text-[12px] text-white/42">
                  {accountSub}
                </span>
              </span>
              <ChevronDown className="h-4 w-4 shrink-0 rotate-180 text-white/35" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side="top"
            align="start"
            sideOffset={8}
            className="dashboard-popup dashboard-body-font w-[220px] rounded-xl p-1.5"
          >
            <DropdownMenuGroup>
              <DropdownMenuItem
                onSelect={() => setShowIntegrations(true)}
                className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-white/84 focus:bg-cyan-300/[0.08]"
              >
                <IntegrationsIcon className="h-4 w-4 shrink-0 text-white/62" />
                Integrations
              </DropdownMenuItem>
              <div className="px-0 py-0">
                <PersonaChip
                  personaPreset={personaPreset || 'default'}
                  personaCustomPrompt={personaCustomPrompt || ''}
                  workspaceDefault={null}
                  onSave={({ preset, customPrompt }) => onSavePersonalPersona?.(preset, customPrompt)}
                  variant="menuItem"
                />
              </div>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={signOut}
              variant="destructive"
              className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-red-400 focus:bg-red-400/[0.12] focus:text-red-300"
            >
              <DoorOpen className="h-4 w-4 shrink-0" aria-hidden="true" />
              {isTestAccount ? 'Exit test run' : 'Sign out'}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        )}
      </div>
    </aside>
  )
}
