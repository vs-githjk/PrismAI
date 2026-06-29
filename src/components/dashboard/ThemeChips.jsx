import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

export default function ThemeChips({ insights }) {
  const themes = insights.recurringThemes || []
  const max = Math.max(...themes.map((theme) => theme.count), 1)

  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Themes</p>
        <h2 className={cardTitle}>Recurring language</h2>
      </div>

      {themes.length ? (
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {themes.map((theme, index) => {
            const size = 0.75 + (theme.count / max) * 0.3
            return (
              <span
                key={theme.theme}
                className="flex items-center justify-between gap-2 rounded-md border border-cyan-200/16 bg-cyan-300/7 px-2.5 py-1.5 font-medium text-cyan-50"
                style={{ fontSize: `${size.toFixed(2)}rem`, animationDelay: `${index * 80}ms` }}
              >
                <span className="truncate">{theme.theme}</span>
                <span className="text-[10px] text-white/42">{theme.count}</span>
              </span>
            )
          })}
        </div>
      ) : (
        <p className={subtleText}>Themes appear once a few meetings have been analyzed.</p>
      )}
    </section>
  )
}
