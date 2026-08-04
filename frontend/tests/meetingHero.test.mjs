// The hero's five states are calendar arithmetic — exactly the kind of logic
// that reads fine and is wrong at the boundaries. Clock injected throughout.

import test from 'node:test'
import assert from 'node:assert/strict'

import { deriveHeroState, countdownLabel, eventDurationMinutes, SOON_MINUTES } from '../src/lib/meetingHero.js'

const NOW = new Date('2026-08-04T12:00:00Z')
const at = (mins) => new Date(NOW.getTime() + mins * 60000).toISOString()
const ev = (mins, title = 'Sync') => ({ title, start: at(mins), end: at(mins + 45) })

test('bot live wins over everything', () => {
  const s = deriveHeroState({ events: [ev(5)], botLive: true, now: NOW })
  assert.equal(s.mode, 'live')
})

test('no events -> none', () => {
  assert.equal(deriveHeroState({ events: [], now: NOW }).mode, 'none')
})

test('boundary: exactly SOON_MINUTES is soon, one past it is next', () => {
  assert.equal(deriveHeroState({ events: [ev(SOON_MINUTES)], now: NOW }).mode, 'soon')
  assert.equal(deriveHeroState({ events: [ev(SOON_MINUTES + 1)], now: NOW }).mode, 'next')
})

test('a started meeting (within the hour) is "now"; older ones drop out', () => {
  assert.equal(deriveHeroState({ events: [ev(-12)], now: NOW }).mode, 'now')
  assert.equal(deriveHeroState({ events: [ev(-61)], now: NOW }).mode, 'none')
})

test('nearest is featured; the next two ride along; a fourth is dropped', () => {
  const s = deriveHeroState({ events: [ev(200, 'D'), ev(18, 'A'), ev(90, 'B'), ev(120, 'C')], now: NOW })
  assert.equal(s.mode, 'soon')
  assert.equal(s.event.title, 'A')
  assert.deepEqual(s.others.map((e) => e.title), ['B', 'C'])
})

test('events without a parseable start never crash the hero', () => {
  const s = deriveHeroState({ events: [{ title: 'bad', start: 'nope' }, ev(45)], now: NOW })
  assert.equal(s.mode, 'next')
  assert.equal(s.event.title, 'Sync')
})

test('countdown labels', () => {
  assert.equal(countdownLabel(18), 'in 18 min')
  assert.equal(countdownLabel(185), 'in 3h 05m')
  assert.equal(countdownLabel(120), 'in 2h')
  assert.equal(countdownLabel(-12), 'started 12 min ago')
  assert.equal(countdownLabel(0), 'started just now')
})

test('duration comes from real start/end, never invented', () => {
  assert.equal(eventDurationMinutes(ev(10)), 45)
  assert.equal(eventDurationMinutes({ start: at(10) }), null)
})
