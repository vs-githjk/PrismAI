// The Task hub's priority sort (byUrgency): live due urgency first (overdue →
// due soon), then recency of the source meeting. Stale deadlines and ownership
// deliberately do NOT rank — ownership is a filter, stale is history.

import test from 'node:test'
import assert from 'node:assert/strict'

import { byUrgency, collectOpenActions, scopeFilter } from '../src/lib/actionItems.js'

const daysFromNow = (n) => {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}
const row = ({ due_date = '', date = daysFromNow(-30) } = {}) => ({
  item: { task: 't', owner: 'x', due_date },
  entry: { id: 1, date },
})

test('a recent overdue outranks a task from a newer meeting', () => {
  const overdue = row({ due_date: daysFromNow(-2), date: daysFromNow(-10) })
  const freshUndated = row({ date: daysFromNow(0) })
  assert.ok(byUrgency(overdue, freshUndated) < 0)
})

test('due soon outranks undated; among undated, newer meeting wins', () => {
  const soon = row({ due_date: daysFromNow(1), date: daysFromNow(-20) })
  const newUndated = row({ date: daysFromNow(-1) })
  const oldUndated = row({ date: daysFromNow(-40) })
  assert.ok(byUrgency(soon, newUndated) < 0)
  assert.ok(byUrgency(newUndated, oldUndated) < 0)
})

test('a stale deadline does not rank as live urgency', () => {
  const stale = row({ due_date: daysFromNow(-40), date: daysFromNow(-45) })
  const newUndated = row({ date: daysFromNow(0) })
  assert.ok(byUrgency(newUndated, stale) < 0)
})

test('collectOpenActions tags ownership for the hub filters', () => {
  const history = [{
    id: 1,
    date: '2026-07-01',
    result: {
      action_items: [
        { task: 'mine', owner: 'Abhinav Dasari' },
        { task: 'nobody', owner: 'Unassigned' },
        { task: 'theirs', owner: 'Przem' },
        { task: 'done', owner: 'Abhinav Dasari', completed: true },
      ],
    },
  }]
  const user = { user_metadata: { full_name: 'Abhinav Dasari' }, email: 'abhinav.d@x.com' }
  const all = collectOpenActions(history, user)
  assert.equal(all.length, 3)
  assert.deepEqual(scopeFilter(all, 'mine').map((r) => r.item.task), ['mine'])
  assert.deepEqual(scopeFilter(all, 'unassigned').map((r) => r.item.task), ['nobody'])
})
