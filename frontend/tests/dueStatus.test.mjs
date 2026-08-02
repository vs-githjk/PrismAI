// Due dates anchor to the MEETING date and go quiet when stale. The bug these
// lock down: "tomorrow" from a June 13 meeting re-resolved against *today* on
// every load — a perpetual DUE TOMORROW badge that never became overdue.

import test from 'node:test'
import assert from 'node:assert/strict'

import { dueInfo, dueLabel, compareDue } from '../src/lib/dueStatus.js'

const iso = (d) => d.toISOString().slice(0, 10)
const daysFromNow = (n) => {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return iso(d)
}

test('the reported case: "tomorrow" from a weeks-old meeting is STALE, not due tomorrow', () => {
  const info = dueInfo({ due: 'tomorrow' }, daysFromNow(-49))
  assert.equal(info.status, 'stale')
  assert.equal(info.date, daysFromNow(-48))
  assert.match(dueLabel(info), /^Was due /)
})

test('"tomorrow" from a fresh analysis (no reference) is genuinely due tomorrow', () => {
  const info = dueInfo({ due: 'tomorrow' })
  assert.equal(info.status, 'soon')
  assert.equal(dueLabel(info), 'Due tomorrow')
})

test('recently missed deadlines still alarm as overdue', () => {
  const info = dueInfo({ due_date: daysFromNow(-3) })
  assert.equal(info.status, 'overdue')
  assert.equal(dueLabel(info), 'Overdue 3d')
})

test('the stale boundary sits at 14 days past due', () => {
  assert.equal(dueInfo({ due_date: daysFromNow(-14) }).status, 'overdue')
  assert.equal(dueInfo({ due_date: daysFromNow(-15) }).status, 'stale')
})

test('backend-resolved due_date wins over the phrase regardless of reference', () => {
  const info = dueInfo({ due: 'tomorrow', due_date: daysFromNow(10) }, daysFromNow(-40))
  assert.equal(info.status, 'later')
})

test('TBD and unparseable phrases stay dateless', () => {
  assert.equal(dueInfo({ due: 'TBD' }, daysFromNow(-30)).status, null)
  assert.equal(dueInfo({ due: 'whenever we feel like it' }).status, null)
})

test('an invalid reference date falls back to today instead of crashing', () => {
  assert.equal(dueInfo({ due: 'tomorrow' }, 'not a date').status, 'soon')
})

test('sort order: overdue, soon, later, stale, undated', () => {
  const overdue = dueInfo({ due_date: daysFromNow(-2) })
  const soon = dueInfo({ due_date: daysFromNow(1) })
  const later = dueInfo({ due_date: daysFromNow(20) })
  const stale = dueInfo({ due_date: daysFromNow(-40) })
  const none = dueInfo({ due: 'TBD' })
  const sorted = [none, stale, later, soon, overdue].sort(compareDue)
  assert.deepEqual(sorted.map((d) => d.status), ['overdue', 'soon', 'later', 'stale', null])
})
