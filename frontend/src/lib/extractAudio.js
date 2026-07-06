// Client-side audio extraction / compression for the Upload tab.
//
// Whisper's API is hard-capped at 25MB. A raw video (or a long audio file) blows
// past that, so before uploading we extract the audio track and downsample it to
// mono ~48kbps Opus — 25MB of that is ~70+ minutes, enough for a single meeting —
// and upload only the small result. This keeps the (free-tier, 512MB) backend out
// of the ffmpeg business entirely and sidesteps the proxy body-size limit that made
// large uploads silently hang.
//
// Uses the single-threaded ffmpeg core (no SharedArrayBuffer), so it works on
// Vercel without COOP/COEP headers.

const WHISPER_MAX_BYTES = 25 * 1024 * 1024
// ffmpeg.wasm loads the whole input into browser memory (32-bit wasm), so extraction
// realistically tops out ~2GB before OOM. A typical 1hr recording (720p/1080p) is well
// under this; larger files (e.g. multi-hour or 4K) need server-side extraction. We reject
// above this ceiling immediately rather than hang on "Loading converter…".
const MAX_INPUT_BYTES = 2 * 1024 * 1024 * 1024

// Loaded lazily on first use so the ~30MB wasm isn't in the initial bundle.
let _ffmpegPromise = null

function withTimeout(promise, ms, message) {
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(message)), ms)
  })
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer))
}

async function getFFmpeg(onLog) {
  if (_ffmpegPromise) return _ffmpegPromise
  _ffmpegPromise = (async () => {
    const { FFmpeg } = await import('@ffmpeg/ffmpeg')
    const { toBlobURL } = await import('@ffmpeg/util')
    // @ffmpeg/ffmpeg 0.12 spawns its worker as type:"module", so the worker loads
    // the core via dynamic import() — which requires the ESM core build (default
    // export). The UMD core has no default export and fails ("failed to import
    // ffmpeg-core.js"). So we must use the /esm/ core here.
    const coreBase = 'https://unpkg.com/@ffmpeg/core@0.12.6/dist/esm'
    const ffmpeg = new FFmpeg()
    if (onLog) ffmpeg.on('log', ({ message }) => onLog(message))
    let coreURL, wasmURL
    try {
      ;[coreURL, wasmURL] = await Promise.all([
        toBlobURL(`${coreBase}/ffmpeg-core.js`, 'text/javascript'),
        toBlobURL(`${coreBase}/ffmpeg-core.wasm`, 'application/wasm'),
      ])
    } catch (e) {
      throw new Error(`Couldn't download the audio converter (${e?.message || e}). Check your connection.`)
    }
    // Bound the load so a stalled CDN fetch / worker spawn surfaces an error.
    await withTimeout(ffmpeg.load({ coreURL, wasmURL }), 60000,
      'Converter took too long to load — check your connection and try again.')
    return ffmpeg
  })().catch((err) => {
    // Let the next attempt retry from scratch instead of caching a failed load.
    _ffmpegPromise = null
    throw err
  })
  return _ffmpegPromise
}

const AUDIO_EXT = /\.(mp3|wav|m4a|ogg|oga|opus|flac|aac|wma|aiff?)$/i

export function isProbablyAudio(file) {
  if (!file) return false
  if (file.type && file.type.startsWith('audio/')) return true
  return AUDIO_EXT.test(file.name || '')
}

/**
 * Prepare a File for /transcribe.
 * - Small audio (<25MB): returned untouched (no wasm load).
 * - Everything else (video, or oversized audio): audio extracted + compressed to
 *   mono Opus; throws if the result is still over the cap.
 *
 * @param {File} file
 * @param {(stage: {phase: 'loading'|'converting'|'done', progress?: number}) => void} [onProgress]
 * @returns {Promise<File>} an audio File ready to upload
 */
export async function prepareAudioForTranscription(file, onProgress) {
  if (isProbablyAudio(file) && file.size <= WHISPER_MAX_BYTES) {
    return file
  }

  if (file.size > MAX_INPUT_BYTES) {
    const gb = (file.size / 1024 / 1024 / 1024).toFixed(1)
    throw new Error(
      `This file is ${gb}GB — too large to process in the browser (limit ~2GB). ` +
      `Export or compress the audio first, or use the meeting bot to record it live.`,
    )
  }

  onProgress?.({ phase: 'loading' })
  const { fetchFile } = await import('@ffmpeg/util')
  const ffmpeg = await getFFmpeg()

  const inName = 'input' + (file.name?.match(/\.[a-z0-9]+$/i)?.[0] || '')
  const outName = 'output.mp3'

  // Capture ffmpeg's own log so a codec/format failure surfaces a real reason
  // instead of a silent throw.
  const logLines = []
  const logHandler = ({ message }) => { logLines.push(message) }
  ffmpeg.on('log', logHandler)
  if (onProgress) {
    ffmpeg.on('progress', ({ progress }) => {
      if (progress >= 0 && progress <= 1) {
        onProgress({ phase: 'converting', progress })
      }
    })
  }

  let data
  try {
    await ffmpeg.writeFile(inName, await fetchFile(file))
    // -vn drop video; mono; 16kHz (Whisper downsamples to 16k anyway); 48k MP3.
    // libmp3lame is included in the standard @ffmpeg/core build.
    const code = await withTimeout(
      ffmpeg.exec(['-i', inName, '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'libmp3lame', '-b:a', '48k', outName]),
      600000, 'Audio extraction timed out.',
    )
    data = await ffmpeg.readFile(outName)
    if (code !== 0 || !data || data.length === 0) {
      const tail = logLines.slice(-4).join(' | ') || `exit ${code}`
      throw new Error(`Couldn't extract audio from this file (${tail}).`)
    }
  } finally {
    ffmpeg.off('log', logHandler)
    try { await ffmpeg.deleteFile(inName) } catch { /* noop */ }
    try { await ffmpeg.deleteFile(outName) } catch { /* noop */ }
  }

  const blob = new Blob([data.buffer], { type: 'audio/mpeg' })
  if (blob.size > WHISPER_MAX_BYTES) {
    const mins = Math.round(blob.size / WHISPER_MAX_BYTES * 70)
    throw new Error(
      `This recording is too long to transcribe in one pass (~${mins} min of audio). ` +
      `Trim it under ~70 minutes and try again, or use the meeting bot to record.`,
    )
  }

  onProgress?.({ phase: 'done' })
  const base = (file.name || 'recording').replace(/\.[a-z0-9]+$/i, '')
  return new File([blob], `${base}.mp3`, { type: 'audio/mpeg' })
}

export { WHISPER_MAX_BYTES }
