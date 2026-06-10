import { useState } from 'react'
import { Check, ChevronDown, Plus, Settings2, Share2, X } from 'lucide-react'
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

/**
 * Top-left chrome island: the workspace switcher. Resting state shows the
 * active scope name + a dropdown chevron; the menu carries Personal, the
 * workspace rows (with inline share/settings), and the create-workspace
 * affordance. The workspace settings modal lives here too.
 */
export default function WorkspaceIsland(props) {
  const {
    user,
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
    shareErrorId,
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
  } = props

  const [wsMenuOpen, setWsMenuOpen] = useState(false)
  const closeWsMenu = () => setWsMenuOpen(false)

  const activeWorkspace = workspaces.find((w) => w.id === activeWorkspaceId) || null
  const scopeLabel = activeWorkspace ? activeWorkspace.name : 'Personal'

  return (
    <div className="dashboard-island dashboard-workspace-island flex items-center" aria-label="Workspace">
      <DropdownMenu open={wsMenuOpen} onOpenChange={setWsMenuOpen}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="flex h-full w-full min-w-0 items-center justify-between gap-2.5 rounded-[inherit] px-6 transition hover:bg-white/[0.05]"
          >
            <span className="min-w-0 truncate text-[18px] font-semibold text-white/92">
              {scopeLabel}
            </span>
            <ChevronDown className="h-4 w-4 shrink-0 text-white/45" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          className="dashboard-island dashboard-body-font w-[260px] p-1.5"
        >
          <DropdownMenuGroup>
            <DropdownMenuItem
              onSelect={() => { closeWsMenu(); switchWorkspace(null) }}
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
                  onClick={() => { closeWsMenu(); switchWorkspace(ws.id) }}
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
                  title={shareErrorId === ws.id ? 'Copy failed — try again' : 'Copy invite link'}
                  aria-label={`Copy invite link for ${ws.name}`}
                  className="flex h-7 w-7 shrink-0 items-center justify-center text-white/35 transition hover:text-cyan-200 disabled:opacity-50"
                >
                  {shareErrorId === ws.id ? (
                    <X className="h-3.5 w-3.5 text-red-400" />
                  ) : shareWorkspaceId === ws.id ? (
                    <Check className="h-3.5 w-3.5 text-cyan-300" />
                  ) : (
                    <Share2 className="h-3.5 w-3.5" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => { closeWsMenu(); toggleWsSettings(ws.id) }}
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
            // Radix Menu runs a typeahead + arrow-key handler on its content;
            // stopping propagation here keeps keystrokes in the input.
            <div
              className="flex items-center gap-1.5 px-1.5 py-1.5"
              onKeyDown={(e) => e.stopPropagation()}
              onPointerDown={(e) => e.stopPropagation()}
            >
              <input
                autoFocus
                value={newWorkspaceName}
                onChange={(e) => {
                  setNewWorkspaceName(e.target.value)
                  setWorkspaceCreateError('')
                }}
                onKeyDown={(e) => {
                  e.stopPropagation()
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
    </div>
  )
}
