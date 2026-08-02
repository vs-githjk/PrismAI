// Home's preview order: yours → unassigned → teammates', urgency within each tier.
// A pure-urgency sort made the personal dashboard lead with other people's work.

import test from 'node:test'
import assert from 'node:assert/strict'

import { byMineFirst, byUrgency, collectOpenActions } from '../src/lib/actionItems.js'

const entry = (id, date) => ({ id, date })
// due_date is the backend-resolved ISO field dueInfo actually reads. Recent
// (computed) dates — a hardcoded past year would be STALE, which by design does
// not rank as live urgency.
const recentOverdue = () => {
  const d = new Date()
  d.setDate(d.getDate() - 2)
  return d.toISOString().slice(0, 10)
}
const row = ({ isMine = false, unassigned = false, due_date = '', date = '2026-07-01' } = {}) => ({
  item: { task: 't', owner: 'x', due_date },
  entry: entry(1, date),
  isMine,
  unassigned,
})

test('yours outrank everyone, even non-urgent vs overdue teammate', () => {
  const mineNoDue = row({ isMine: true })
  const teammateOverdue = row({ due_date: recentOverdue() })
  assert.ok(byMineFirst(mineNoDue, teammateOverdue) < 0)
})

test('unassigned outrank teammates but not yours', () => {
  const mine = row({ isMine: true })
  const unassigned = row({ unassigned: true })
  const teammate = row({})
  assert.ok(byMineFirst(unassigned, teammate) < 0)
  assert.ok(byMineFirst(mine, unassigned) < 0)
})

test('within a tier, urgency still decides', () => {
  const mineOverdue = row({ isMine: true, due_date: recentOverdue() })
  const mineNoDue = row({ isMine: true })
  assert.ok(byMineFirst(mineOverdue, mineNoDue) < 0)
  assert.equal(byMineFirst(mineOverdue, mineNoDue), byUrgency(mineOverdue, mineNoDue))
})

test('collectOpenActions tags ownership used by the sort', () => {
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
  const rows = collectOpenActions(history, user).sort(byMineFirst)
  assert.deepEqual(rows.map((r) => r.item.task), ['mine', 'nobody', 'theirs'])
  assert.equal(rows[0].isMine, true)
  assert.equal(rows[1].unassigned, true)
})
