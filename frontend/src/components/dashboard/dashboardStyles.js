// Matches the floating chrome islands (.dashboard-island in index.css): theme
// tokens drive both light + dark. See index.css :root / .theme-light.
export const glassCard = 'rounded-2xl border border-[color:var(--db-border)]'
export const cardGlowStyle = {
  background: 'linear-gradient(180deg, var(--db-glass-top) 0%, var(--db-glass-bottom) 100%)',
  backdropFilter: 'blur(26px) saturate(115%)',
  WebkitBackdropFilter: 'blur(26px) saturate(115%)',
  boxShadow: 'var(--db-shadow)',
}
export const eyebrow = 'text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--db-text)]'
export const cardTitle = 'text-base font-semibold tracking-[-0.01em] text-[color:var(--db-text)]'
export const bodyText = 'text-sm leading-6 text-[color:var(--db-text-soft)]'
export const subtleText = 'text-xs leading-5 text-[color:var(--db-text-soft)]'
export const divider = 'border-[color:var(--db-border)]'
export const tableRow = 'border-t border-[color:var(--db-border)] px-3 py-2'
