import { useEffect, useRef, useState } from 'react'
import {
  Bolt,
  DoorOpen,
  History,
  LogIn,
  Plus,
  RotateCcw,
  UserCircle,
} from 'lucide-react'
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

const secondaryButtonClass = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-white/[0.16] bg-[#151515] px-4 text-sm font-semibold text-white/86 transition hover:border-white/[0.24] hover:bg-[#1d1d1d] hover:text-white'
const eyebrowClass = 'text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-200/90'

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

export default function DashboardMcpPage(props) {
  const [profileMenuOpen, setProfileMenuOpen] = useState(false)
  const [profileMenuPinned, setProfileMenuPinned] = useState(false)
  const profileCloseTimer = useRef(null)
  const profileAreaRef = useRef(null)
  const profileContentRef = useRef(null)
  const profileTriggerHovered = useRef(false)
  const profileContentHovered = useRef(false)

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

  return (
    <div className="landing-page dashboard-mcp-page min-h-dvh overflow-x-hidden font-['Rubik',sans-serif] text-[color:var(--landing-text)]">
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
          <button
            type="button"
            onClick={() => {
              sessionStorage.setItem('prism_ui_screen', 'landing')
              window.location.href = '/'
            }}
            className="logo-btn flex items-center gap-2"
            aria-label="Back to landing page"
          >
            <LogoIcon className="h-11 w-11" />
            <span className="prism-logo-text text-2xl font-light tracking-wider" data-text="prism">prism</span>
          </button>

          <div className="flex items-center gap-2">
            {props.authReady && !props.user && (
              <button type="button" onClick={props.signInWithTestAccount || props.signInWithGoogle} className="dashboard-signin-button landing-button-primary hidden items-center gap-1.5 px-3 text-[11px] font-semibold sm:inline-flex" style={{ minHeight: 36 }}>
                <LogIn className="h-3.5 w-3.5" aria-hidden="true" />
                Sign in
              </button>
            )}
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
                      className="flex h-9 w-9 items-center justify-center rounded-full border border-[#3f3f46] bg-[#27272a] text-[#f2f2f2] shadow-[0_10px_28px_rgba(0,0,0,0.3)] transition hover:bg-[#323238] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan-300/18 data-[state=open]:bg-[#323238]"
                      aria-label="Open profile menu"
                    >
                      <UserCircle className="h-5.5 w-5.5" aria-hidden="true" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    ref={profileContentRef}
                    align="end"
                    className="w-52 rounded-xl border-[#2f2f2f] bg-[#0b0b0b] p-1.5"
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
                        Setttings
                      </DropdownMenuItem>
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onSelect={props.signOut} variant="destructive" className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-red-400 focus:bg-red-400/[0.12] focus:text-red-300">
                      <DoorOpen className="h-4 w-4 shrink-0" aria-hidden="true" />
                      Sign out
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ) : (
              <button
                type="button"
                className="flex h-9 w-9 items-center justify-center rounded-full border border-[#3f3f46] bg-[#27272a] text-[#f2f2f2] shadow-[0_10px_28px_rgba(0,0,0,0.3)] transition hover:bg-[#323238] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan-300/18"
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

      <main className="relative z-10 mx-auto max-w-[92rem] px-5 pb-28 pt-5 sm:px-8">
        <StatsCanvas
          history={props.history}
          result={props.result}
          crossMeetingInsights={props.crossMeetingInsights}
          loadFromHistory={props.loadFromHistory}
          loadSample={props.loadDashboardSample || props.startDemo}
        />
      </main>

      <nav className="fixed bottom-5 left-1/2 z-30 h-[96px] w-[154px] -translate-x-1/2" aria-label="Dashboard shortcuts" data-node-id="4590:266">
        <button type="button" onClick={() => props.setShowHistory((value) => !value)} className="absolute bottom-4 left-1 flex h-10 w-10 items-center justify-center rounded-full border border-white/[0.16] bg-[#101010]/95 text-white/72 shadow-xl transition hover:border-cyan-200/40 hover:bg-[#151515] hover:text-cyan-50" aria-label="Toggle history">
          <History className="h-4 w-4" aria-hidden="true" />
        </button>
        <button type="button" onClick={() => { sessionStorage.setItem('prism_new_meeting', '1'); props.clearWorkspaceState() }} className="absolute bottom-7 left-1/2 flex h-16 w-16 -translate-x-1/2 items-center justify-center rounded-full border border-cyan-100/42 bg-cyan-300/18 text-cyan-50 shadow-xl shadow-cyan-950/35 transition hover:bg-cyan-300/26" aria-label="New meeting">
          <Plus className="h-5 w-5" aria-hidden="true" />
        </button>
        <button type="button" onClick={() => { window.location.href = '/' }} className="absolute bottom-4 right-1 flex h-10 w-10 items-center justify-center rounded-full border border-white/[0.16] bg-[#101010]/95 text-white/72 shadow-xl transition hover:border-cyan-200/40 hover:bg-[#151515] hover:text-cyan-50" aria-label="Switch to classic dashboard">
          <RotateCcw className="h-4 w-4" aria-hidden="true" />
        </button>
      </nav>

      <div className="fixed bottom-4 right-4 z-30 hidden rounded-full border border-cyan-200/35 bg-cyan-300/16 px-3 py-2 text-xs font-semibold text-cyan-50 shadow-2xl backdrop-blur-xl lg:block">
        Dashboard MCP
      </div>
    </div>
  )
}
