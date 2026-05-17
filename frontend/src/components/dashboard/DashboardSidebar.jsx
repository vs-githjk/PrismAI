import { useMemo } from 'react'
import {
  Bolt,
  Check,
  ChevronDown,
  DoorOpen,
  Home,
  PanelLeftClose,
  Plus,
  Search,
  Settings2,
  Share2,
  Trash2,
  UserCircle,
  X,
} from 'lucide-react'
import { deriveDisplayTitle } from '../../lib/insights'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'

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

function formatHistoryDate(date) {
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
  'group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors'

export default function DashboardSidebar(props) {
  const {
    collapsed,
    onToggleCollapse,
    onResizeHandlePointerDown,
    user,
    isTestAccount,
    isDemoMode,
    workspaces = [],
    activeWorkspaceId,
    switchWorkspace,
    creatingWorkspace,
    setCreatingWorkspace,
    newWorkspaceName,
    setNewWorkspaceName,
    createWorkspace,
    workspaceCreating,
    workspaceCreateError,
    setWorkspaceCreateError,
    shareWorkspace,
    shareWorkspaceId,
    toggleWsSettings,
    wsSettingsId,
    wsDetails,
    wsDetailsLoading,
    regenerateInvite,
    removeMember,
    deleteWorkspaceFromSettings,
    copyInviteLink,
    inviteCopied,
    closeWsSettings,
    history = [],
    filteredHistory = [],
    historySearch,
    historySearchOpen,
    toggleHistorySearch,
    onHistorySearchChange,
    activeView,
    onGoHome,
    onSelectMeeting,
    onDeleteMeeting,
    currentMeetingId,
    botActive,
    setShowIntegrations,
    signOut,
  } = props

  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId) || null
  const scopeLabel = activeWorkspace ? activeWorkspace.name : 'Personal'
  const scopeInitial = scopeLabel.charAt(0).toUpperCase()

  const groups = useMemo(() => groupMeetings(filteredHistory), [filteredHistory])
  const onHome = activeView === 'home'

  const accountName =
    user?.email?.split('@')[0] || (isDemoMode ? 'Demo session' : 'Guest')
  const accountSub = user?.email || (isTestAccount ? 'Test run' : 'Not signed in')

  // ---- Collapsed icon rail ----
  if (collapsed) {
    return (
      <aside className="dashboard-sidebar flex flex-col items-center gap-1.5 py-3" aria-label="Dashboard navigation">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-white/45 transition hover:bg-white/[0.06] hover:text-white/80"
          aria-label="Expand sidebar"
          title="Expand sidebar (⌘\\)"
        >
          <span className="grid h-7 w-7 place-items-center rounded-md bg-cyan-400/[0.14] text-[12px] font-bold text-cyan-200">
            {scopeInitial}
          </span>
        </button>
        <button
          type="button"
          onClick={onGoHome}
          className={`flex h-9 w-9 items-center justify-center rounded-lg transition ${
            onHome ? 'bg-cyan-400/[0.14] text-cyan-200' : 'text-white/45 hover:bg-white/[0.06] hover:text-white/80'
          }`}
          aria-label="Home"
          title="Home"
        >
          <Home className="h-4 w-4" />
        </button>
        <div className="mt-auto">
          <button
            type="button"
            onClick={signOut}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-white/45 transition hover:bg-white/[0.06] hover:text-white/80"
            aria-label="Account"
            title={accountSub}
          >
            <UserCircle className="h-5 w-5" />
          </button>
        </div>
      </aside>
    )
  }

  // ---- Full sidebar ----
  return (
    <aside className="dashboard-sidebar flex flex-col" aria-label="Dashboard navigation">
      {/* Workspace switcher */}
      <div className="px-2.5 pb-1 pt-3">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-white/[0.05]"
            >
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-cyan-400/[0.14] text-[11px] font-bold text-cyan-200">
                {scopeInitial}
              </span>
              <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-white/90">
                {scopeLabel}
              </span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-white/40" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            className="dashboard-body-font w-[var(--ws-menu-w,260px)] rounded-xl border-[#2f2f2f] bg-[#0b0b0b] p-1.5"
            style={{ '--ws-menu-w': '260px' }}
          >
            <DropdownMenuGroup>
              <DropdownMenuItem
                onSelect={() => switchWorkspace(null)}
                className="cursor-pointer gap-2 px-2.5 py-2 text-[12.5px] font-semibold text-white/84 focus:bg-cyan-300/[0.08]"
              >
                <span className="grid h-5 w-5 place-items-center rounded bg-white/[0.08] text-[10px] font-bold text-white/70">
                  P
                </span>
                <span className="flex-1">Personal</span>
                {!activeWorkspaceId && <Check className="h-3.5 w-3.5 text-cyan-300" />}
              </DropdownMenuItem>

              {workspaces.map((ws) => (
                <div
                  key={ws.id}
                  className="group flex items-center rounded-md focus-within:bg-cyan-300/[0.06] hover:bg-cyan-300/[0.06]"
                >
                  <button
                    type="button"
                    onClick={() => switchWorkspace(ws.id)}
                    className="flex min-w-0 flex-1 items-center gap-2 px-2.5 py-2 text-left text-[12.5px] font-semibold text-white/84"
                  >
                    <span className="grid h-5 w-5 shrink-0 place-items-center rounded bg-white/[0.08] text-[10px] font-bold text-white/70">
                      {ws.name.charAt(0).toUpperCase()}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{ws.name}</span>
                    {activeWorkspaceId === ws.id && (
                      <Check className="h-3.5 w-3.5 shrink-0 text-cyan-300" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => shareWorkspace(ws.id)}
                    title="Copy invite link"
                    aria-label={`Copy invite link for ${ws.name}`}
                    className="flex h-7 w-7 shrink-0 items-center justify-center text-white/35 transition hover:text-cyan-200"
                  >
                    {shareWorkspaceId === ws.id ? (
                      <Check className="h-3.5 w-3.5 text-cyan-300" />
                    ) : (
                      <Share2 className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleWsSettings(ws.id)}
                    title="Workspace settings"
                    aria-label={`Settings for ${ws.name}`}
                    className="mr-1 flex h-7 w-7 shrink-0 items-center justify-center text-white/35 transition hover:text-white/80"
                  >
                    <Settings2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </DropdownMenuGroup>

            <DropdownMenuSeparator />

            {creatingWorkspace ? (
              <div className="flex items-center gap-1.5 px-1.5 py-1.5">
                <input
                  autoFocus
                  value={newWorkspaceName}
                  onChange={(e) => {
                    setNewWorkspaceName(e.target.value)
                    setWorkspaceCreateError('')
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') createWorkspace()
                    if (e.key === 'Escape') {
                      setCreatingWorkspace(false)
                      setNewWorkspaceName('')
                      setWorkspaceCreateError('')
                    }
                  }}
                  placeholder="Workspace name…"
                  className="h-7 min-w-0 flex-1 rounded-md border border-cyan-400/40 bg-white/[0.07] px-2 text-[12px] text-white/90 outline-none placeholder:text-white/35 focus:border-cyan-400/70"
                />
                <button
                  type="button"
                  onClick={createWorkspace}
                  disabled={workspaceCreating}
                  className="shrink-0 rounded-md border border-cyan-400/50 bg-cyan-400/[0.15] px-2 py-1 text-[10px] font-bold text-cyan-300 transition hover:bg-cyan-400/[0.25] disabled:opacity-50"
                >
                  {workspaceCreating ? '…' : 'Create'}
                </button>
              </div>
            ) : (
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault()
                  setCreatingWorkspace(true)
                }}
                className="cursor-pointer gap-2 px-2.5 py-2 text-[12.5px] font-semibold text-cyan-300 focus:bg-cyan-300/[0.12]"
              >
                <Plus className="h-4 w-4" />
                New workspace
              </DropdownMenuItem>
            )}
            {workspaceCreateError && (
              <p className="px-2.5 pb-1 text-[10px] text-red-400/80">{workspaceCreateError}</p>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Pinned: Home */}
      <div className="px-2.5">
        <button
          type="button"
          onClick={onGoHome}
          className={`${navItemBase} ${
            onHome
              ? 'bg-cyan-400/[0.12] text-cyan-100'
              : 'text-white/72 hover:bg-white/[0.05] hover:text-white'
          }`}
        >
          <Home className="h-4 w-4 shrink-0" />
          Home
        </button>
      </div>

      {/* Meetings section */}
      <div className="mt-3 flex items-center justify-between px-4 pb-1">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-white/36">
          Meetings
        </p>
        <button
          type="button"
          onClick={toggleHistorySearch}
          aria-label="Search meetings"
          aria-expanded={historySearchOpen}
          className={`flex h-6 w-6 items-center justify-center rounded-md transition ${
            historySearchOpen
              ? 'text-cyan-200'
              : 'text-white/35 hover:bg-white/[0.06] hover:text-white/70'
          }`}
        >
          <Search className="h-3.5 w-3.5" />
        </button>
      </div>

      {historySearchOpen && (
        <div className="px-2.5 pb-1.5">
          <div className="flex h-7 items-center gap-2 rounded-md border border-white/[0.08] bg-white/[0.035] px-2 focus-within:border-cyan-400/45">
            <Search className="h-3 w-3 shrink-0 text-white/36" aria-hidden="true" />
            <input
              autoFocus
              value={historySearch || ''}
              onChange={onHistorySearchChange}
              placeholder="Search meetings..."
              className="h-full min-w-0 flex-1 bg-transparent text-[12px] font-medium text-white/80 outline-none placeholder:font-normal placeholder:text-white/32"
            />
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-2">
        {!user && !isDemoMode ? (
          <p className="px-2 py-6 text-center text-[12px] leading-5 text-white/42">
            Meeting history appears after you sign in.
          </p>
        ) : history.length === 0 ? (
          <p className="px-2 py-6 text-center text-[12px] leading-5 text-white/42">
            Saved meetings will appear here.
          </p>
        ) : groups.length === 0 ? (
          <p className="px-2 py-6 text-center text-[12px] leading-5 text-white/42">
            No matching meetings.
          </p>
        ) : (
          groups.map((group) => (
            <div key={group.label} className="mb-1">
              <p className="px-2 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-white/28">
                {group.label}
              </p>
              {group.items.map((entry) => {
                const isActive = entry.id === currentMeetingId && activeView !== 'home'
                const isLive = botActive && entry.id === currentMeetingId
                return (
                  <div
                    key={entry.id}
                    className={`group flex items-center rounded-lg pr-1 transition ${
                      isActive
                        ? 'bg-cyan-400/[0.12]'
                        : 'hover:bg-white/[0.05]'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelectMeeting(entry)}
                      className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left"
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
                          className={`block truncate text-[12.5px] font-medium leading-5 ${
                            isActive ? 'text-cyan-100' : 'text-white/80'
                          }`}
                        >
                          {deriveDisplayTitle(entry)}
                          {isLive && (
                            <span className="ml-1.5 text-[10px] font-semibold text-cyan-300">
                              · live
                            </span>
                          )}
                        </span>
                        <span className="block truncate text-[10px] leading-4 text-white/40">
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
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )
              })}
            </div>
          ))
        )}
      </div>

      {/* Footer: Discord-style account block */}
      <div className="border-t border-white/[0.06] p-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition hover:bg-white/[0.05]"
            >
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-cyan-400/[0.14] text-cyan-200">
                <UserCircle className="h-5 w-5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12.5px] font-semibold text-white/88">
                  {accountName}
                </span>
                <span className="block truncate text-[10.5px] text-white/42">
                  {accountSub}
                </span>
              </span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 rotate-180 text-white/35" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side="top"
            align="start"
            sideOffset={8}
            className="dashboard-body-font w-[220px] rounded-xl border-[#2f2f2f] bg-[#0b0b0b] p-1.5"
          >
            <DropdownMenuGroup>
              <DropdownMenuItem
                onSelect={() => setShowIntegrations(true)}
                className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-white/84 focus:bg-cyan-300/[0.08]"
              >
                <IntegrationsIcon className="h-4 w-4 shrink-0 text-white/62" />
                Integrations
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled
                className="gap-3 px-3 py-2 text-xs font-semibold text-white/40"
              >
                <Bolt className="h-4 w-4 shrink-0 text-white/30" aria-hidden="true" />
                Settings
                <span className="ml-auto text-[9.5px] font-medium text-white/28">Soon</span>
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
      </div>

      {/* Collapse toggle (sits on the resize handle area) */}
      <button
        type="button"
        onClick={onToggleCollapse}
        className="absolute right-2 top-3 z-10 flex h-7 w-7 items-center justify-center rounded-md text-white/30 transition hover:bg-white/[0.06] hover:text-white/70"
        aria-label="Collapse sidebar"
        title="Collapse sidebar (⌘\\)"
      >
        <PanelLeftClose className="h-4 w-4" />
      </button>

      {/* Drag-resize handle */}
      <div
        onPointerDown={onResizeHandlePointerDown}
        className="dashboard-sidebar-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
      />

      {/* Workspace settings modal */}
      <Dialog open={!!wsSettingsId} onOpenChange={(o) => { if (!o) closeWsSettings() }}>
        <DialogContent className="dashboard-body-font border-[#2f2f2f] bg-[#0f0f11] text-white sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold text-white">
              Workspace settings
            </DialogTitle>
          </DialogHeader>
          {wsDetailsLoading ? (
            <p className="text-[12px] text-white/40">Loading…</p>
          ) : wsDetails ? (
            <div className="space-y-4">
              <div>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-white/35">
                  Invite link
                </p>
                <div className="flex items-center gap-1.5">
                  <input
                    readOnly
                    value={`${window.location.origin}/dashboard#invite/${wsDetails.invite_token}`}
                    className="min-w-0 flex-1 rounded-lg border border-white/[0.08] bg-white/[0.04] px-2 py-1.5 text-[11px] text-white/55 outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => copyInviteLink(wsDetails.invite_token)}
                    className="shrink-0 rounded-lg border border-cyan-400/30 bg-cyan-400/[0.08] px-3 py-1.5 text-[11px] font-semibold text-cyan-300 transition hover:bg-cyan-400/[0.16]"
                  >
                    {inviteCopied ? 'Copied!' : 'Copy'}
                  </button>
                </div>
                {wsDetails.your_role === 'owner' && (
                  <button
                    type="button"
                    onClick={regenerateInvite}
                    className="mt-1.5 text-[10.5px] text-white/35 transition hover:text-white/65"
                  >
                    Regenerate link
                  </button>
                )}
              </div>

              <div>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-white/35">
                  Members ({wsDetails.members?.length ?? 0})
                </p>
                <div className="max-h-48 space-y-2 overflow-y-auto">
                  {wsDetails.members?.map((member) => (
                    <div key={member.user_id} className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-[12px] text-white/70">
                          {member.user_email || member.user_id.slice(0, 12) + '…'}
                          {member.user_id === user?.id && (
                            <span className="ml-1 text-white/30">(you)</span>
                          )}
                        </p>
                        <p className="text-[10px] capitalize text-white/30">{member.role}</p>
                      </div>
                      {wsDetails.your_role === 'owner' && member.user_id !== user?.id && (
                        <button
                          type="button"
                          onClick={() => removeMember(wsSettingsId, member.user_id)}
                          className="shrink-0 text-[10.5px] text-red-400/50 transition hover:text-red-400/80"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between border-t border-white/[0.06] pt-3">
                {wsDetails.your_role === 'owner' ? (
                  <button
                    type="button"
                    onClick={deleteWorkspaceFromSettings}
                    className="text-[11px] text-red-400/55 transition hover:text-red-400/85"
                  >
                    Delete workspace
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => removeMember(wsSettingsId, user?.id)}
                    className="text-[11px] text-red-400/55 transition hover:text-red-400/85"
                  >
                    Leave workspace
                  </button>
                )}
                <button
                  type="button"
                  onClick={closeWsSettings}
                  className="rounded-full border border-white/[0.12] bg-white/[0.06] px-3.5 py-1.5 text-[12px] font-semibold text-white/80 transition hover:bg-white/[0.10]"
                >
                  Done
                </button>
              </div>
            </div>
          ) : (
            <p className="text-[12px] text-red-400/60">Failed to load workspace details.</p>
          )}
        </DialogContent>
      </Dialog>
    </aside>
  )
}
