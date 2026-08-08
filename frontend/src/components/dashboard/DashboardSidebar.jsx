import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  DoorOpen,
  Home,
  ListTodo,
  Lock,
  LogIn,
  Plus,
  TrendingUp,
  Trash2,
  UserCircle,
  UserRoundCheck,
  CalendarDays,
  Monitor,
  Sun,
  Moon,
} from 'lucide-react'
import { deriveDisplayTitle } from '../../lib/insights'
import { meetingBucket } from '../../lib/dateGroups'
import { formatHistoryDate, IntegrationsIcon } from './chrome'
import { eyebrow } from './dashboardStyles'
import PersonaChip from '../PersonaChip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu'

// Group meetings by the shared calendar ladder (Today · Yesterday · This week ·
// This month · Last month · Last 6 months · This year · Older), newest first —
// the same buckets the Action items page uses. The old local 3-bucket version
// collapsed a whole account's history into one giant "EARLIER 32" pile.
function groupMeetings(entries) {
  const byBucket = new Map()
  for (const entry of entries) {
    const b = meetingBucket(entry?.date)
    if (!byBucket.has(b.key)) byBucket.set(b.key, { ...b, items: [] })
    byBucket.get(b.key).items.push(entry)
  }
  return [...byBucket.values()].sort((a, b) => a.rank - b.rank)
}

const navItemBase =
  'group relative flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-[13px] font-medium transition-colors'

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
    theme,
    onToggleTheme,
    history = [],
    filteredHistory = [],
    activeView,
    onGoHome,
    onOpenActions,
    actionsCount = 0,
    onOpenTrend,
    onOpenKnowledge,
    onOpenStandin,
    standinBadge = 0,
    collapsed = false,
    onOpenCalendar,
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
    onSetupWorkspace,
    signOut,
    newMeetingOpen,
    setNewMeetingOpen,
    onOpenNewMeeting,
    newMeetingPanel,
    newMeetingCollisionPadding,
    // Unauthenticated shell: a signed-out viewer (e.g. someone who opened a
    // live/share link) sees the chrome with every feature locked. Clicking a
    // locked feature calls onLockedFeature, which opens the sign-in gate.
    signedOut = false,
    onLockedFeature,
  } = props

  const groups = useMemo(() => groupMeetings(filteredHistory), [filteredHistory])
  const onHome = activeView === 'home'
  const onActions = activeView === 'actions'
  const onTrend = activeView === 'intelligence'
  const onKnowledge = activeView === 'knowledge'
  const onStandin = activeView === 'standin'
  const onCalendar = activeView === 'calendar'

  // Collapsible date groups (the shared calendar ladder), keyed by label.
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
  // Profile photo from the signed-in provider (Google OAuth → user_metadata).
  const avatarUrl = user?.user_metadata?.avatar_url || user?.user_metadata?.picture || ''
  const [avatarOk, setAvatarOk] = useState(true)

  return (
    <aside id="dashboard-sidebar-nav" className="dashboard-sidebar dashboard-island flex flex-col" aria-label="Dashboard navigation">
      {/* Pinned: Home + Actions + Trend + Calendar + Knowledge + Stand-in. When
          signed out, each is locked and clicking opens the sign-in gate instead
          of navigating. */}
      <div className="space-y-1 px-3 pt-4">
        {[
          { key: 'home', label: 'Home', Icon: Home, active: onHome, onClick: onGoHome },
          { key: 'actions', label: 'Actions', Icon: ListTodo, active: onActions, onClick: onOpenActions, badge: actionsCount, badgeLabel: `${actionsCount} open action item${actionsCount === 1 ? '' : 's'}` },
          { key: 'trend', label: 'Trend', Icon: TrendingUp, active: onTrend, onClick: onOpenTrend },
          { key: 'calendar', label: 'Calendar', Icon: CalendarDays, active: onCalendar, onClick: onOpenCalendar },
          { key: 'knowledge', label: 'Knowledge', Icon: BookOpen, active: onKnowledge, onClick: onOpenKnowledge },
          { key: 'standin', label: 'Stand-in', Icon: UserRoundCheck, active: onStandin, onClick: onOpenStandin, badge: standinBadge },
        ].map(({ key, label, Icon, active, onClick, badge, badgeLabel }) => (
          <button
            key={key}
            type="button"
            onClick={signedOut ? () => onLockedFeature?.(label) : onClick}
            aria-disabled={signedOut || undefined}
            title={collapsed ? label : undefined}
            aria-label={collapsed ? label : undefined}
            className={`${navItemBase} ${collapsed ? 'justify-center px-0' : ''} ${
              active && !signedOut
                ? 'bg-[var(--db-fill-strong)] text-[color:var(--db-text)]'
                : signedOut
                  ? 'text-[color:var(--db-text-faint)] hover:bg-[var(--db-fill)] hover:text-[color:var(--db-text-muted)]'
                  : 'text-[color:var(--db-text-soft)] hover:bg-[var(--db-fill)] hover:text-[color:var(--db-text)]'
            }`}
          >
            {active && !signedOut && (
              <span
                className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-[var(--db-accent)]"
                aria-hidden="true"
              />
            )}
            <Icon className="h-4 w-4 shrink-0 text-[color:var(--db-text-muted)]" />
            {!collapsed && label}
            {/* Unread count — so a waiting stand-in brief is visible from any view,
                not only after navigating to the page that holds it. Collapsed, it
                rides the icon as a corner dot-count. Neutral (never cyan) — a
                count pill is not a selection state. */}
            {!signedOut && badge > 0 && (
              collapsed ? (
                <span className="absolute right-1.5 top-1.5 grid h-[16px] min-w-[16px] place-items-center rounded-full bg-[var(--db-fill-strong)] px-1 text-[9.5px] font-semibold text-[color:var(--db-text-muted)]"
                  aria-label={badgeLabel || `${badge} unread`}>
                  {badge}
                </span>
              ) : (
                <span className="ml-auto grid h-[18px] min-w-[18px] shrink-0 place-items-center rounded-full bg-[var(--db-fill-strong)] px-1.5 text-[10.5px] font-semibold text-[color:var(--db-text-muted)]"
                  aria-label={badgeLabel || `${badge} unread`}>
                  {badge}
                </span>
              )
            )}
            {signedOut && !collapsed && <Lock className="ml-auto h-3.5 w-3.5 shrink-0 text-[color:var(--db-text-faint)]" aria-hidden="true" />}
          </button>
        ))}
      </div>

      {/* Meetings section — New meeting button sits beside the heading. Collapsed,
          the heading and the meeting list go (titles are unreadable at 76px) and
          only the New-meeting control remains, centred. */}
      <div className={`mt-4 flex items-center border-t border-[color:var(--db-border)] px-5 pb-1.5 pt-3 ${collapsed ? 'justify-center px-0' : 'justify-between'}`}>
        {!collapsed && (
          <p className={eyebrow} style={{ color: 'var(--db-text-faint)' }}>
            Meetings
          </p>
        )}
        {signedOut ? (
          <button
            type="button"
            aria-label="New meeting"
            title="Sign in to start a meeting"
            onClick={() => onLockedFeature?.('New meeting')}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-[color:var(--db-text-faint)] transition hover:bg-[var(--db-fill)] hover:text-[color:var(--db-text-muted)]"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
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
                className="flex h-7 w-7 items-center justify-center rounded-lg text-[color:var(--db-accent-text)] transition hover:bg-[var(--db-accent-fill)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--db-accent)]"
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              side="bottom"
              align="start"
              sideOffset={10}
              collisionPadding={newMeetingCollisionPadding ?? 64}
              modal={false}
              className="dashboard-island dashboard-body-font w-[min(340px,calc(100vw-1.25rem))] p-0"
              // Inline style, not a Tailwind class: the base DropdownMenuContent class has
              // overflow-hidden, and `max-h-[var(...)]` arbitrary values get dropped by
              // tailwind-merge — so the height cap never applied and the popover ran off
              // screen. Inline style beats both. The Radix var gives the real space below
              // the (mid-page) trigger; 80vh is a fallback if it's ever unset.
              style={{ maxHeight: 'var(--radix-popper-available-height, 80vh)', overflowY: 'auto' }}
              onCloseAutoFocus={(e) => e.preventDefault()}
            >
              {newMeetingPanel}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {/* `hidden` removes the aside's only flex-1 child, so the account footer
          below needs mt-auto to stay pinned to the bottom of the collapsed rail
          (without it, it jumped up under the nav icons leaving ~400px of void). */}
      <div className={`min-h-0 flex-1 overflow-y-auto px-3 pb-2 ${collapsed ? 'hidden' : ''}`}>
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
                : 'hover:bg-[var(--db-fill)] shadow-[inset_0_0_0_1px_rgba(244,63,94,0.12)]'
            }`}
          >
            <span className="status-island-livedot relative h-2 w-2 shrink-0 rounded-full bg-rose-500" aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className={`block truncate text-[14px] font-semibold leading-5 ${liveActive ? 'text-rose-100' : 'text-[color:var(--db-text)]'}`}>
                Live meeting
              </span>
              <span className="block truncate text-[11.5px] leading-4 text-rose-300/80">
                {LIVE_LABELS[liveStatus] || 'Connecting…'}
              </span>
            </span>
          </button>
        )}
        {!user && !isDemoMode ? (
          <p className="px-2 py-6 text-center text-[13px] leading-5 text-[color:var(--db-text-faint)]">
            Meeting history appears after you sign in.
          </p>
        ) : history.length === 0 ? (
          <p className="px-2 py-6 text-center text-[13px] leading-5 text-[color:var(--db-text-faint)]">
            Saved meetings will appear here.
          </p>
        ) : groups.length === 0 ? (
          <p className="px-2 py-6 text-center text-[13px] leading-5 text-[color:var(--db-text-faint)]">
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
                className="group/hdr flex w-full items-center gap-1 rounded-md px-2 pb-1 pt-2.5 text-left transition hover:bg-[var(--db-fill)]"
              >
                <ChevronRight
                  className={`h-3 w-3 shrink-0 text-[color:var(--db-text-faint)] transition-transform group-hover/hdr:text-[color:var(--db-text-muted)] ${collapsed ? '' : 'rotate-90'}`}
                  aria-hidden="true"
                />
                <span className={eyebrow} style={{ color: 'var(--db-text-faint)' }}>
                  {group.label}
                </span>
                <span className="ml-1 text-[10px] font-medium text-[color:var(--db-text-faint)]">{group.items.length}</span>
              </button>
              {!collapsed && group.items.map((entry) => {
                const isActive = entry.id === currentMeetingId && activeView === 'meeting'
                const isLive = botActive && entry.id === currentMeetingId
                return (
                  <div
                    key={entry.id}
                    ref={isActive ? activeRowRef : null}
                    className={`group relative flex items-center rounded-lg pr-1 transition ${
                      isActive
                        ? 'bg-[var(--db-fill-strong)]'
                        : 'hover:bg-[var(--db-fill)]'
                    }`}
                  >
                    {isActive && (
                      <span
                        className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-[var(--db-accent)]"
                        aria-hidden="true"
                      />
                    )}
                    <button
                      type="button"
                      onClick={() => onSelectMeeting(entry)}
                      aria-current={isActive ? 'page' : undefined}
                      className="flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2.5 py-2 text-left"
                    >
                      {isLive ? (
                        <span
                          className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--db-accent)]"
                          aria-hidden="true"
                        />
                      ) : (
                        <span
                          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                            isActive ? 'bg-[var(--db-accent)]' : 'bg-[var(--db-fill-strong)]'
                          }`}
                          aria-hidden="true"
                        />
                      )}
                      <span className="min-w-0 flex-1">
                        <span
                          className={`block truncate text-[13px] font-medium leading-5 ${
                            isActive ? 'text-[color:var(--db-text)]' : 'text-[color:var(--db-text-soft)]'
                          }`}
                        >
                          {deriveDisplayTitle(entry)}
                          {isLive && (
                            <span className="ml-1.5 text-[10.5px] font-semibold text-[color:var(--db-accent-text)]">
                              · live
                            </span>
                          )}
                        </span>
                        <span className="block truncate text-[11.5px] leading-4 text-[color:var(--db-text-faint)]">
                          {formatHistoryDate(entry.date)}
                        </span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => onDeleteMeeting(entry)}
                      aria-label={`Delete ${deriveDisplayTitle(entry)}`}
                      className="flex h-7 w-7 shrink-0 items-center justify-center text-[color:var(--db-text-faint)] opacity-0 transition hover:text-red-300 focus-visible:opacity-100 group-hover:opacity-100"
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

      {/* Footer: account block — replaced by a Sign in CTA when signed out.
          mt-auto pins it to the bottom in BOTH states (harmless when the meeting
          list is present, since the list already absorbs the free space). */}
      <div className="mt-auto border-t border-[color:var(--db-border)] p-2">
        {signedOut ? (
          <button
            type="button"
            onClick={() => onLockedFeature?.('Account')}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-cyan-400/30 bg-cyan-400/[0.10] px-2.5 py-2 text-[13px] font-semibold text-cyan-200 transition hover:border-cyan-400/50 hover:bg-cyan-400/[0.16]"
          >
            <LogIn className="h-4 w-4 shrink-0" aria-hidden="true" />
            Sign in
          </button>
        ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              title={collapsed ? accountName : undefined}
              aria-label={collapsed ? `Account: ${accountName}` : undefined}
              className={`flex w-full items-center rounded-lg py-1.5 text-left transition hover:bg-[var(--db-fill)] ${collapsed ? 'justify-center px-0' : 'gap-3 px-2.5'}`}
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-full bg-cyan-400/[0.14] text-cyan-200">
                {avatarUrl && avatarOk ? (
                  <img
                    src={avatarUrl}
                    alt=""
                    referrerPolicy="no-referrer"
                    onError={() => setAvatarOk(false)}
                    className="h-full w-full rounded-full object-cover"
                  />
                ) : (
                  <UserCircle className="h-6 w-6" />
                )}
              </span>
              {!collapsed && (
                <>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold text-[color:var(--db-text)]">
                      {accountName}
                    </span>
                    <span className="block truncate text-[12px] text-[color:var(--db-text-faint)]">
                      {accountSub}
                    </span>
                  </span>
                  <ChevronDown className="h-4 w-4 shrink-0 rotate-180 text-[color:var(--db-text-faint)]" />
                </>
              )}
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
                className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-[color:var(--db-text-soft)] focus:bg-cyan-300/[0.08]"
              >
                <IntegrationsIcon className="h-4 w-4 shrink-0 text-[color:var(--db-text-muted)]" />
                Integrations
              </DropdownMenuItem>
              {/* AI workspace setup — requires a real signed-in user (backend is
                  auth-gated); hidden for demo/test sessions. */}
              {user && onSetupWorkspace && (
                <DropdownMenuItem
                  onSelect={() => onSetupWorkspace()}
                  className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-[color:var(--db-text-soft)] focus:bg-cyan-300/[0.08]"
                >
                  <Monitor className="h-4 w-4 shrink-0 text-[color:var(--db-text-muted)]" />
                  Set up my AI workspace
                </DropdownMenuItem>
              )}
              <div className="px-0 py-0">
                <PersonaChip
                  personaPreset={personaPreset || 'default'}
                  personaCustomPrompt={personaCustomPrompt || ''}
                  workspaceDefault={null}
                  onSave={({ preset, customPrompt }) => onSavePersonalPersona?.(preset, customPrompt)}
                  variant="menuItem"
                />
              </div>
              <DropdownMenuItem
                onSelect={() => onToggleTheme?.()}
                className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-[color:var(--db-text-soft)] focus:bg-cyan-300/[0.08]"
              >
                {theme === 'light'
                  ? <Moon className="h-4 w-4 shrink-0 text-[color:var(--db-text-muted)]" />
                  : <Sun className="h-4 w-4 shrink-0 text-[color:var(--db-text-muted)]" />}
                {theme === 'light' ? 'Dark theme' : 'Light theme'}
              </DropdownMenuItem>
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
