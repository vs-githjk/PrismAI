// Headless capture of the Prism shader background into a seamless looping mp4.
//
// Usage:
//   1. Start the Vite dev server in another shell:  npm run dev
//   2. In a separate shell:  node scripts/capture-prism.mjs
//
// Output: public/prism-loop.mp4 (and a .webm sibling if libvpx-vp9 is available)
//
// Loop math:
//   The Prism shader wobble matrix has period 2π in (iTime * timeScale).
//   Shipping config sets timeScale=0.3 → wall-clock period 2π/0.3 ≈ 20.944s.
//   We sample exactly N = round(period * fps) frames at evenly-spaced t values
//   t_i = i * (period / N). Frame N would equal Frame 0, so we skip it — the
//   resulting video loops without a seam.

import { chromium } from 'playwright'
import { spawn } from 'node:child_process'
import { mkdir, access } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '..')

const WIDTH = 1920
const HEIGHT = 1080
const FPS = 60
const TIME_SCALE = 0.3
const PERIOD = (2 * Math.PI) / TIME_SCALE
const FRAMES = Math.round(PERIOD * FPS)
const URL_BASE = process.env.PRISM_CAPTURE_URL || 'http://localhost:5173'
const URL = `${URL_BASE}/#prism-capture`

const OUT_DIR = resolve(ROOT, 'public')
const OUT_MP4 = resolve(OUT_DIR, 'prism-loop.mp4')

async function ensureDevServer() {
  try {
    const res = await fetch(URL_BASE, { method: 'HEAD' })
    if (!res.ok && res.status !== 404) throw new Error(`status ${res.status}`)
  } catch (err) {
    console.error(`\n[capture] Vite dev server not reachable at ${URL_BASE}.`)
    console.error(`[capture] Start it in another shell:  npm run dev\n`)
    process.exit(1)
  }
}

function spawnFfmpeg() {
  const args = [
    '-y',
    '-f', 'image2pipe',
    '-framerate', String(FPS),
    '-i', 'pipe:0',
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-crf', '18',
    '-preset', 'slow',
    '-movflags', '+faststart',
    OUT_MP4,
  ]
  const child = spawn('ffmpeg', args, { stdio: ['pipe', 'inherit', 'inherit'] })
  child.on('error', (err) => {
    console.error('[capture] ffmpeg failed to start:', err.message)
    process.exit(1)
  })
  return child
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true })
  await ensureDevServer()

  console.log(`[capture] period=${PERIOD.toFixed(4)}s  frames=${FRAMES}  fps=${FPS}  size=${WIDTH}x${HEIGHT}`)

  const browser = await chromium.launch({
    headless: true,
    args: [
      '--use-gl=angle',
      '--enable-webgl',
      '--ignore-gpu-blocklist',
      '--disable-gpu-vsync',
    ],
  })
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: 1,
  })
  const page = await context.newPage()

  page.on('pageerror', (err) => console.error('[page-error]', err.message))
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.error('[console]', msg.text())
  })

  await page.goto(URL, { waitUntil: 'networkidle' })
  await page.waitForFunction(() => window.__prismReady === true, { timeout: 30_000 })

  // Warm the shader so JIT / GPU upload cost doesn't skew the first frame.
  await page.evaluate(() => {
    for (let i = 0; i < 4; i++) window.__prismRenderAt(0)
  })

  const ff = spawnFfmpeg()
  const writeFrame = (buf) =>
    new Promise((resolve, reject) => {
      if (ff.stdin.write(buf)) resolve()
      else ff.stdin.once('drain', resolve)
      ff.stdin.once('error', reject)
    })

  const dt = PERIOD / FRAMES
  const t0 = Date.now()
  for (let i = 0; i < FRAMES; i++) {
    const t = i * dt
    await page.evaluate((time) => {
      window.__prismRenderAt(time)
      return new Promise((r) => requestAnimationFrame(() => r()))
    }, t)
    const png = await page.screenshot({
      type: 'png',
      clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT },
      omitBackground: false,
    })
    await writeFrame(png)
    if (i % 30 === 0 || i === FRAMES - 1) {
      const elapsed = (Date.now() - t0) / 1000
      const fps = (i + 1) / elapsed
      const eta = (FRAMES - 1 - i) / Math.max(0.1, fps)
      process.stdout.write(`\r[capture] frame ${i + 1}/${FRAMES}  ${fps.toFixed(1)} fps  eta ${eta.toFixed(0)}s   `)
    }
  }
  process.stdout.write('\n')

  ff.stdin.end()
  await new Promise((resolve) => ff.on('close', resolve))
  await browser.close()

  try {
    await access(OUT_MP4)
    console.log(`[capture] wrote ${OUT_MP4}`)
  } catch {
    console.error('[capture] ffmpeg did not produce output')
    process.exit(1)
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
