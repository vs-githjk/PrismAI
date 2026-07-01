// Dependency-free guard: every --db-* token must be defined in BOTH the :root
// default block and the .theme-light override block, and --db-text must differ
// (proves the cascade flips). Run: node scripts/check-theme-tokens.mjs
import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')

const TOKENS = [
  '--db-chrome-bg', '--db-page-bg', '--db-glass-top', '--db-glass-bottom',
  '--db-shadow', '--db-text', '--db-text-soft', '--db-text-muted',
  '--db-text-faint', '--db-fill', '--db-fill-strong', '--db-border',
  '--db-border-strong', '--db-accent', '--db-accent-text', '--db-accent-fill',
]

// Grab the contents of the first `<selector> { ... }` whose body contains --db-text.
function block(selector) {
  const re = new RegExp(selector.replace(/[.*]/g, '\\$&') + '\\s*\\{([^}]*--db-text:[^}]*)\\}', 's')
  const m = css.match(re)
  return m ? m[1] : null
}
function valueOf(body, token) {
  const m = body && body.match(new RegExp(token + '\\s*:\\s*([^;]+);'))
  return m ? m[1].trim() : null
}

const root = block(':root')
const light = block('.theme-light')
const errors = []

if (!root) errors.push(':root block defining --db-text not found')
if (!light) errors.push('.theme-light block defining --db-text not found')

for (const t of TOKENS) {
  if (root && !valueOf(root, t)) errors.push(`:root missing ${t}`)
  if (light && !valueOf(light, t)) errors.push(`.theme-light missing ${t}`)
}
if (root && light && valueOf(root, '--db-text') === valueOf(light, '--db-text')) {
  errors.push('--db-text is identical in :root and .theme-light (theme does not flip)')
}

if (errors.length) {
  console.error('FAIL:\n' + errors.map((e) => '  - ' + e).join('\n'))
  process.exit(1)
}
console.log(`PASS: all ${TOKENS.length} tokens defined in both blocks and --db-text flips`)
