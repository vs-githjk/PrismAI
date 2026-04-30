export default function SignupDialog({ onClose }) {
  return (
    <div className="signup-overlay" onClick={onClose}>
      <div
        className="signup-dialog"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="signup-title"
      >
        <button type="button" className="signup-close" onClick={onClose} aria-label="Close dialog">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <line x1="2" y1="2" x2="14" y2="14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="14" y1="2" x2="2" y2="14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </button>

        <p className="signup-kicker">Early access</p>
        <h2 id="signup-title" className="signup-title">Get in early.</h2>
        <p className="signup-body">
          PrismAI is in private beta. Drop your email and we'll reach out when your spot opens up.
        </p>

        <input
          type="email"
          placeholder="you@company.com"
          className="signup-email-input landing-input"
          autoFocus
        />
        <button type="button" className="signup-submit landing-button-primary">Join waitlist</button>
      </div>
    </div>
  )
}
