// Matches the floating chrome islands (.dashboard-island in index.css): a faint
// white translucent film over the dark page, heavy blur, bright top-edge catch.
export const glassCard = 'rounded-2xl border border-white/[0.09]'
export const cardGlowStyle = {
  background: 'linear-gradient(180deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.028) 100%)',
  backdropFilter: 'blur(26px) saturate(115%)',
  WebkitBackdropFilter: 'blur(26px) saturate(115%)',
  boxShadow:
    '0 16px 44px rgba(0,0,0,0.55), 0 1px 0 rgba(255,255,255,0.10) inset, 0 -1px 0 rgba(0,0,0,0.20) inset',
}
export const eyebrow = 'text-[10px] font-semibold uppercase tracking-[0.16em] text-white'
export const cardTitle = 'text-base font-semibold tracking-[-0.01em] text-white'
export const bodyText = 'text-sm leading-6 text-white/85'
export const subtleText = 'text-xs leading-5 text-white/80'
export const divider = 'border-white/[0.08]'
export const tableRow = 'border-t border-white/[0.07] px-3 py-2'
