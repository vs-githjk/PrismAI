import { Plus } from 'lucide-react'
import LogoIcon from '../LogoIcon'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu'
import { UI_SCREEN_KEY } from '../../lib/sessionKeys'

/**
 * Topbar: prism logo (→ landing) · New meeting · centered Current/Cross
 * intelligence switch. The switch is disabled (grayed) whenever no meeting
 * is in focus — see docs/adr/0001.
 */
export default function DashboardTopbar({
  newMeetingOpen,
  setNewMeetingOpen,
  onOpenNewMeeting,
  newMeetingPanel,
  meetingInFocus,
  view, // 'current' | 'cross'
  onSelectView,
}) {
  const goLanding = () => {
    sessionStorage.setItem(UI_SCREEN_KEY, 'landing')
    window.location.href = '/'
  }

  const segBase =
    'min-w-[88px] rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors'
  const segActive = 'bg-cyan-400/[0.14] text-cyan-200 shadow-[0_0_0_1px_rgba(34,211,238,0.28)]'
  const segIdle = 'text-white/55 hover:text-white/80'

  return (
    <header className="dashboard-topbar sticky top-0 z-30 flex items-center gap-4 px-3">
      {/* Left: logo + New meeting */}
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <button
          type="button"
          onClick={goLanding}
          className="logo-btn flex items-center gap-2"
          aria-label="Back to landing page"
        >
          <LogoIcon className="h-8 w-8" />
          <span
            className="prism-logo-text text-[1.3rem] font-light tracking-wider"
            data-text="prism"
          >
            prism
          </span>
        </button>

        <DropdownMenu
          open={newMeetingOpen}
          onOpenChange={(open) => {
            setNewMeetingOpen(open)
            if (open) onOpenNewMeeting?.()
          }}
        >
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="inline-flex h-9 items-center gap-1.5 rounded-full border border-cyan-400/30 bg-cyan-400/[0.10] px-3.5 text-[13px] font-semibold text-cyan-200 transition hover:border-cyan-400/50 hover:bg-cyan-400/[0.16] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/25"
              aria-label="New meeting"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              New meeting
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side="bottom"
            align="start"
            sideOffset={10}
            modal={false}
            className="dashboard-body-font w-[340px] rounded-2xl border border-white/[0.10] bg-[#0f0f11] p-0 shadow-2xl"
            onCloseAutoFocus={(e) => e.preventDefault()}
          >
            {newMeetingPanel}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Center: Current / Cross intelligence switch */}
      <div
        className="flex shrink-0 items-center rounded-full border border-white/[0.08] bg-white/[0.03] p-0.5"
        role="tablist"
        aria-label="Meeting intelligence view"
        aria-disabled={!meetingInFocus}
        title={meetingInFocus ? undefined : 'Open a meeting to view its intelligence'}
      >
        <button
          type="button"
          role="tab"
          aria-selected={meetingInFocus && view === 'current'}
          disabled={!meetingInFocus}
          onClick={() => onSelectView?.('current')}
          className={`${segBase} ${
            !meetingInFocus
              ? 'cursor-not-allowed text-white/22'
              : view === 'current'
                ? segActive
                : segIdle
          }`}
        >
          Current meeting
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={meetingInFocus && view === 'cross'}
          disabled={!meetingInFocus}
          onClick={() => onSelectView?.('cross')}
          className={`${segBase} ${
            !meetingInFocus
              ? 'cursor-not-allowed text-white/22'
              : view === 'cross'
                ? segActive
                : segIdle
          }`}
        >
          Cross-meeting
        </button>
      </div>

      {/* Right: balance spacer (profile lives in the sidebar footer) */}
      <div className="min-w-0 flex-1" aria-hidden="true" />
    </header>
  )
}
