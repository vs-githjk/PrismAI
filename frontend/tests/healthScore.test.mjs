// The "nothing to grade" analysis stores score:null and a null breakdown. These
// lock down the Number(null)===0 trap: a null must surface as null (rendered as
// a dash / hidden panel), never as a confident 0.

import test from 'node:test'
import assert from 'node:assert/strict'

import { overallHealth } from '../src/lib/healthScore.js'

test('null score and null breakdown -> null, not 0', () => {
  assert.equal(overallHealth({ score: null, breakdown: { clarity: null, action_orientation: null, engagement: null } }), null)
})

test('missing health entirely -> null', () => {
  assert.equal(overallHealth(null), null)
  assert.equal(overallHealth({}), null)
})

test('partial null breakdown falls back to the holistic score', () => {
  assert.equal(overallHealth({ score: 40, breakdown: { clarity: 50, action_orientation: null, engagement: 30 } }), 40)
})

test('real breakdown still averages', () => {
  assert.equal(overallHealth({ score: 99, breakdown: { clarity: 60, action_orientation: 30, engagement: 30 } }), 40)
})

test('a genuine zero is still a zero', () => {
  assert.equal(overallHealth({ score: 0, breakdown: null }), 0)
})
