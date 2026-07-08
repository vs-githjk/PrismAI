// Single source of truth for the content-analysis meeting types.
// Mirrors backend agents/meeting_classifier.VALID_TYPES + content_analyst.RUBRICS.
// Keep in sync if the backend vocabulary changes.

export const MEETING_TYPES = [
  { value: 'standard',          label: 'Standard meeting',    short: 'Meeting',   accent: '#67e8f9' },
  { value: 'pitch',             label: 'Pitch / Presentation', short: 'Pitch',    accent: '#a78bfa' },
  { value: 'interview_content', label: 'Content interview',   short: 'Interview', accent: '#f472b6' },
  { value: 'interview_job',     label: 'Job interview',       short: 'Candidate', accent: '#fbbf24' },
]

// 'auto' is an input-time choice only (server detects) — never a resolved value.
export const AUTO_OPTION = { value: 'auto', label: 'Auto-detect', short: 'Auto', accent: '#94a3b8' }

// Options for the New-Meeting input picker (Auto first, default).
export const INPUT_TYPE_OPTIONS = [AUTO_OPTION, ...MEETING_TYPES]

const SPECIAL = new Set(['pitch', 'interview_content', 'interview_job'])

// A "special" type gets the deep-dive card + its own headline score (health ring
// is the wrong lens for it). Standard / auto / unknown → false.
export function isSpecialType(type) {
  return SPECIAL.has(type)
}

export function typeMeta(value) {
  return (
    MEETING_TYPES.find((t) => t.value === value) ||
    (value === 'auto' ? AUTO_OPTION : MEETING_TYPES[0])
  )
}

// The resolved type for a saved result, tolerant of old rows (no field) and of the
// card carrying the authoritative type. Prefers content_analysis.type.
export function resolvedType(result) {
  if (!result) return 'standard'
  const ca = result.content_analysis
  if (ca && isSpecialType(ca.type)) return ca.type
  return result.meeting_type || 'standard'
}

// Whether this result should render the deep-dive card / score swap.
export function hasContentAnalysis(result) {
  const ca = result?.content_analysis
  return !!(ca && isSpecialType(ca.type) && Array.isArray(ca.rubric) && ca.rubric.length)
}
