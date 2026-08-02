// Date bucketing is calendar arithmetic with boundary cases, which is exactly the
// kind of logic that reads fine and is wrong. The bug these lock down: a rolling
// "< 30 days" window was labelled "This month", so on Aug 2 a Jul 17 meeting was
// filed under "This month" and everything older collapsed into one "Earlier" pile.

import test from 'node:test'
import assert from 'node:assert/strict'

import { meetingBucket } from '../src/lib/dateGroups.js'

// Sunday, 2 August 2026 — the date the reported screenshot was taken.
const NOW = new Date(2026, 7, 2, 14, 30)
const label = (y, m, d) => meetingBucket(new Date(y, m, d, 12, 0), NOW).label

test('the reported case: Jul 17 is LAST month, not this month', () => {
  assert.equal(label(2026, 6, 17), 'Last month')
})

test('the reported case: June meetings are "Last 6 months", not one big "Earlier"', () => {
  assert.equal(label(2026, 5, 13), 'Last 6 months')
  assert.equal(label(2026, 5, 8), 'Last 6 months')
  assert.equal(label(2026, 5, 7), 'Last 6 months')
})

test('today and yesterday', () => {
  assert.equal(label(2026, 7, 2), 'Today')
  assert.equal(label(2026, 7, 1), 'Yesterday')
})

test('time of day never changes the bucket', () => {
  assert.equal(meetingBucket(new Date(2026, 7, 2, 0, 1), NOW).label, 'Today')
  assert.equal(meetingBucket(new Date(2026, 7, 2, 23, 59), NOW).label, 'Today')
})

test('this month covers earlier days of the current calendar month', () => {
  // NOW is Sunday Aug 2, so the calendar week starts Aug 2 — Jul 31 is NOT this
  // week, and being in July it is last month.
  const midAug = new Date(2026, 7, 20, 12)
  assert.equal(meetingBucket(new Date(2026, 7, 5, 12), midAug).label, 'This month')
})

test('days a few back stay in "This week" even across a month boundary', () => {
  // NOW is Sunday 2 Aug; the ISO week runs Mon 27 Jul – Sun 2 Aug. Friday 31 Jul is
  // two days ago and must not read as "Last month".
  assert.equal(label(2026, 6, 31), 'This week')
  assert.equal(label(2026, 6, 30), 'This week')
  assert.equal(label(2026, 6, 27), 'This week')
  // ...but the day before that week started is last month, correctly.
  assert.equal(label(2026, 6, 26), 'Last month')
})

test('this week wins over last month across a month boundary', () => {
  // Wed Aug 5 2026 -> week starts Sun Aug 2. Take a Thursday inside a week that
  // began in the previous month: Thu Jul 30, with "now" = Sat Aug 1 (week from Jul 26).
  const satAug1 = new Date(2026, 7, 1, 12)
  assert.equal(meetingBucket(new Date(2026, 6, 30, 12), satAug1).label, 'This week')
})

test('last month crosses the year boundary in January', () => {
  const jan15 = new Date(2026, 0, 15, 12)
  assert.equal(meetingBucket(new Date(2025, 11, 20, 12), jan15).label, 'Last month')
})

test('six-month window covers the four months before last month', () => {
  // NOW = Aug: this=Aug, last=Jul, so the window reaches back to Mar 1.
  assert.equal(label(2026, 2, 1), 'Last 6 months')   // Mar 1, first day in window
  assert.equal(label(2026, 1, 28), 'This year')      // Feb, just outside it
})

test('older than this year is "Older"', () => {
  assert.equal(label(2025, 10, 4), 'Older')
  assert.equal(label(2024, 3, 4), 'Older')
})

test('buckets are strictly ordered oldest-last', () => {
  const dates = [
    [2026, 7, 2],  // today
    [2026, 7, 1],  // yesterday
    [2026, 6, 17], // last month
    [2026, 5, 13], // last 6 months
    [2026, 1, 28], // this year
    [2025, 10, 4], // older
  ]
  const ranks = dates.map(([y, m, d]) => meetingBucket(new Date(y, m, d, 12), NOW).rank)
  for (let i = 1; i < ranks.length; i += 1) {
    assert.ok(ranks[i] > ranks[i - 1], `rank must increase as dates get older (index ${i})`)
  }
})

test('every bucket has a distinct human label', () => {
  const seen = new Set()
  for (const [y, m, d] of [[2026, 7, 2], [2026, 7, 1], [2026, 6, 17], [2026, 5, 13], [2026, 1, 28], [2025, 10, 4]]) {
    const l = meetingBucket(new Date(y, m, d, 12), NOW).label
    assert.ok(!seen.has(l), `duplicate label ${l}`)
    seen.add(l)
  }
})

test('unparseable and missing dates get "No date", never a real bucket', () => {
  for (const bad of [null, undefined, '', 'not a date', NaN]) {
    assert.equal(meetingBucket(bad, NOW).label, 'No date')
  }
})

test('future-dated meetings fall in the current week, not a past bucket', () => {
  assert.equal(label(2026, 7, 6), 'This week')
})
