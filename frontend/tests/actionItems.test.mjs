// byPriority is THE task order (CONTEXT.md "Task priority"): live due urgency
// (overdue → due soon), then ownership tiers among equals (yours → unowned →
// teammates'), then source-meeting recency. Stale deadlines never rank.

import test from 'node:test'
import assert from 'node:assert/strict'

import { byPriority, collectOpenActions, scopeFilter } from '../src/lib/actionItems.js'

const daysFromNow = (n) => {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}
const row = ({ due_date = '', date = daysFromNow(-30), isMine = false, unassigned = false } = {}) => ({
  item: { task: 't', owner: 'x', due_date },
  entry: { id: 1, date },
  isMine,
  unassigned,
})

test("a teammate's recent overdue outranks YOUR fresh undated task (urgency beats ownership)", () => {
  const theirOverdue = row({ due_date: daysFromNow(-2), date: daysFromNow(-10) })
  const mineFresh = row({ date: daysFromNow(0), isMine: true })
  assert.ok(byPriority(theirOverdue, mineFresh) < 0)
})

test('among equally urgent: yours → unowned → teammates', () => {
  const mine = row({ isMine: true })
  const unowned = row({ unassigned: true })
  const theirs = row({})
  assert.ok(byPriority(mine, unowned) < 0)
  assert.ok(byPriority(unowned, theirs) < 0)
})

test('within a tier, newer meeting wins', () => {
  const newMine = row({ isMine: true, date: daysFromNow(-1) })
  const oldMine = row({ isMine: true, date: daysFromNow(-40) })
  assert.ok(byPriority(newMine, oldMine) < 0)
})

test('a stale deadline does not rank as live urgency', () => {
  const stale = row({ due_date: daysFromNow(-40), date: daysFromNow(-45) })
  const newUndated = row({ date: daysFromNow(0) })
  assert.ok(byPriority(newUndated, stale) < 0)
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
