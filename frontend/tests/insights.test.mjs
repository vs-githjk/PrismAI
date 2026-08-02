// Unit tests for the metrics behind the Trend KPI band.
//
// These exist because every one of the bugs they cover shipped past visual
// review: a wrong number renders perfectly. "Delta vs prior" was subtracting the
// OLDEST meeting instead of the previous one (so a rising score reported a
// decline), "30-day average" had no 30-day window, and scoreBand(null) fell
// through Number(null) === 0 to a confident red "Needs work".
//
// Run: node --test tests/   (no test framework — Node's built-in runner)

import test from 'node:test'
import assert from 'node:assert/strict'

import { deriveInsights, scoreBand, healthColor, HEALTH_BANDS } from '../src/lib/insights.js'

const daysAgo = (n) => new Date(Date.now() - n * 24 * 60 * 60 * 1000).toISOString()

/** A history entry with a breakdown that averages to `score`. */
const meeting = (score, date) => ({
  id: `m-${score}-${date}`,
  date,
  result: {
    summary: 'x',
    health_score: { breakdown: { clarity: score, action_orientation: score, engagement: score } },
  },
})

test('scoreDelta compares the latest meeting to the one immediately before it', () => {
  // Newest 84, previous 73, oldest 88 — the exact shape that reported -4.
  const history = [meeting(84, daysAgo(1)), meeting(73, daysAgo(2)), meeting(88, daysAgo(3))]
  const { latestScore, previousScore, scoreDelta } = deriveInsights(history)
  assert.equal(latestScore, 84)
  assert.equal(previousScore, 73)
  assert.equal(scoreDelta, 11, 'should be +11 (84-73), not -4 (84-88)')
})

test('scoreDelta is order-independent of the input array', () => {
  const oldestFirst = [meeting(88, daysAgo(3)), meeting(73, daysAgo(2)), meeting(84, daysAgo(1))]
  assert.equal(deriveInsights(oldestFirst).scoreDelta, 11)
})

test('scoreDelta is null (not 0) with a single scored meeting', () => {
  const { scoreDelta, previousScore } = deriveInsights([meeting(84, daysAgo(1))])
  assert.equal(previousScore, null)
  assert.equal(scoreDelta, null, '0 would claim "no change" where there is no comparison')
})

test('scoreDelta can be negative when the score genuinely fell', () => {
  const history = [meeting(60, daysAgo(1)), meeting(90, daysAgo(2))]
  assert.equal(deriveInsights(history).scoreDelta, -30)
})

test('avgScore only averages the last 30 days', () => {
  // 90 and 80 are inside the window; the 20 is 45 days old and must not count.
  const history = [meeting(90, daysAgo(1)), meeting(80, daysAgo(10)), meeting(20, daysAgo(45))]
  const { avgScore, avgScoreCount } = deriveInsights(history)
  assert.equal(avgScore, 85, 'mean of 90 and 80, excluding the 45-day-old meeting')
  assert.equal(avgScoreCount, 2, 'sample size is exported so the label can be honest')
})

test('avgScore is null when nothing falls inside the window', () => {
  const { avgScore, avgScoreCount } = deriveInsights([meeting(70, daysAgo(90))])
  assert.equal(avgScore, null)
  assert.equal(avgScoreCount, 0)
})

test('unscored meetings are excluded from the score metrics, not treated as zero', () => {
  const unscored = { id: 'u', date: daysAgo(1), result: { summary: 'no health score' } }
  const history = [unscored, meeting(80, daysAgo(2)), meeting(70, daysAgo(3))]
  const { latestScore, scoreDelta, avgScore } = deriveInsights(history)
  assert.equal(latestScore, 80, 'latest SCORED meeting, not the unscored newest row')
  assert.equal(scoreDelta, 10)
  assert.equal(avgScore, 75, 'a missing score must not drag the mean toward 0')
})

test('scoreBand(null) reports "No score", never a red verdict', () => {
  for (const missing of [null, undefined, '']) {
    const band = scoreBand(missing)
    assert.equal(band.label, 'No score', `${String(missing)} must not be graded`)
    assert.equal(band.tone, 'slate')
    assert.notEqual(band.color, HEALTH_BANDS.at(-1).color, 'must not reuse the "Needs work" colour')
  }
})

test('scoreBand has five bands at 80/60/40/20 and matches healthColor', () => {
  assert.equal(scoreBand(100).label, 'Healthy')
  assert.equal(scoreBand(80).label, 'Healthy')
  assert.equal(scoreBand(79).label, 'Good')
  assert.equal(scoreBand(60).label, 'Good')
  assert.equal(scoreBand(59).label, 'Fair')
  assert.equal(scoreBand(40).label, 'Fair')
  assert.equal(scoreBand(39).label, 'Weak')
  assert.equal(scoreBand(20).label, 'Weak')
  assert.equal(scoreBand(19).label, 'Needs work')
  assert.equal(scoreBand(0).label, 'Needs work')
  for (const s of [0, 19, 20, 39, 40, 59, 60, 79, 80, 100]) {
    assert.equal(healthColor(s), scoreBand(s).color, 'healthColor must not drift from scoreBand')
  }
})

test('real low scores get DIFFERENT colours, not one wall of red', () => {
  // The actual distribution in this account: median 20, max 50. A 3-band scale
  // painted all of these identically, which is what made the UI unreadable.
  const sample = [0, 12, 13, 18, 20, 20, 20, 40, 50]
  const colours = new Set(sample.map(healthColor))
  assert.ok(colours.size >= 3, `expected >=3 distinct colours across ${sample.join(',')}, got ${colours.size}`)
})

test('colour stays directional — worse scores never look better', () => {
  const order = HEALTH_BANDS.map((b) => b.color) // best -> worst
  const indexOf = (s) => order.indexOf(healthColor(s))
  for (const [worse, better] of [[10, 30], [30, 50], [50, 70], [70, 90]]) {
    assert.ok(indexOf(worse) > indexOf(better), `${worse} must not rank above ${better}`)
  }
})

test('cyan is never a score colour — it is reserved for interactive state', () => {
  for (let s = 0; s <= 100; s += 1) {
    const c = healthColor(s).toLowerCase()
    assert.ok(c !== '#22d3ee' && c !== '#67e8f9', `score ${s} must not use the brand cyan`)
  }
})

test('completionRate is null when there are no action items, not 0%', () => {
  const bare = { id: 'b', date: daysAgo(1), result: { summary: 'x', action_items: [] } }
  assert.equal(deriveInsights([bare]).completionRate, null)
})

test('completionRate counts ticked items', () => {
  const entry = {
    id: 'c', date: daysAgo(1),
    result: {
      summary: 'x',
      action_items: [{ task: 'a', completed: true }, { task: 'b' }, { task: 'c', completed: true }, { task: 'd' }],
    },
  }
  assert.equal(deriveInsights([entry]).completionRate.rate, 50)
})
