import { useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import LogoIcon from './LogoIcon'

// Static legal pages (Privacy Policy / Terms). Reached via the hash routes
// #privacy and #terms — consistent with the app's other hash sub-views (share/
// live/invite). Content is served from /legal/*.md so "flip to the final,
// lawyer-approved text" = replace the file in public/legal, no rebuild logic.
//
// NOTE: the current /legal/*.md are DRAFTS with placeholders. Do not treat these
// pages as published until counsel has reviewed and the [TODO] markers are gone.

const PAGES = {
  privacy: { slug: 'privacy-policy', title: 'Privacy Policy' },
  terms: { slug: 'terms-of-service', title: 'Terms of Service' },
}

export default function LegalPage({ page = 'privacy', onBack }) {
  const meta = PAGES[page] || PAGES.privacy
  const [md, setMd] = useState('')
  const [state, setState] = useState('loading') // loading | ready | error

  useEffect(() => {
    let alive = true
    setState('loading')
    fetch(`/legal/${meta.slug}.md`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.text()
      })
      .then((text) => {
        if (!alive) return
        setMd(text)
        setState('ready')
      })
      .catch(() => alive && setState('error'))
    return () => {
      alive = false
    }
  }, [meta.slug])

  const goBack = () => {
    if (onBack) return onBack()
    // Default: clear the hash and return wherever the user came from.
    if (window.history.length > 1) window.history.back()
    else window.location.hash = ''
  }

  return (
    <div className="legal-page">
      <header className="legal-page-nav">
        <div className="legal-page-nav-inner">
          <a href="/" className="legal-page-brand" aria-label="PrismAI home">
            <LogoIcon className="w-7 h-7" />
            <span>PrismAI</span>
          </a>
          <button type="button" className="legal-page-back" onClick={goBack}>
            <ArrowLeft aria-hidden="true" size={16} />
            Back
          </button>
        </div>
      </header>

      <main className="legal-page-body">
        {state === 'loading' && <p className="legal-page-status">Loading {meta.title}…</p>}
        {state === 'error' && (
          <p className="legal-page-status">
            Couldn’t load the {meta.title}. Please try again later.
          </p>
        )}
        {state === 'ready' && (
          <article className="legal-prose">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
          </article>
        )}
      </main>
    </div>
  )
}
