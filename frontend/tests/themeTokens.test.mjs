import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../src/index.css'), 'utf8')

function tokensIn(blockRe) {
  const block = css.match(blockRe)?.[0] ?? ''
  return new Set([...block.matchAll(/--db-[a-z-]+(?=\s*:)/g)].map((m) => m[0]))
}

// :root dashboard block ends at the .theme-light selector; .theme-light block ends at .dark
const darkTokens = tokensIn(/── Dashboard theme tokens[\s\S]*?(?=\.theme-light)/)
const lightTokens = tokensIn(/\.theme-light\s*\{[\s\S]*?\}/)

test('every dashboard token is defined for both themes', () => {
  assert.ok(darkTokens.size >= 26, `expected ≥26 dark tokens, got ${darkTokens.size}`)
  assert.deepEqual([...darkTokens].sort(), [...lightTokens].sort())
})

test('the matte card surface token exists', () => {
  assert.ok(darkTokens.has('--db-card'))
})
