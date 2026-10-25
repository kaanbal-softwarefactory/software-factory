import { test } from 'node:test'
import assert from 'node:assert/strict'
import { updateSummary, canReapplyLatest, upgradeBlocked } from '../src/utils/coreUpdates.js'
const head = 'b'.repeat(40)
const base = { current: { known: true }, tracking: 'commits', update_available: false, upstream: { available: true, head_sha: head, ahead_by: 0, commits: [] } }

test('docs-only commit remains visible without inventing an engine update', () => {
  const data = { ...base, upstream: { ...base.upstream, ahead_by: 1, commits: [{ sha: head }], touches_engine: false } }
  assert.equal(updateSummary(data).kind, 'repository')
  assert.equal(canReapplyLatest(data), true)
})
test('failed upstream lookup never claims up to date or offers an unverified ref', () => {
  const data = { ...base, upstream: { available: false, reason: 'GitHub respondió HTTP 403' } }
  assert.equal(updateSummary(data).kind, 'unknown')
  assert.match(updateSummary(data).detail, /403/)
  assert.equal(canReapplyLatest(data), false)
})
test('engine update, current version, unknown provenance and divergent history are distinct', () => {
  assert.equal(updateSummary({ ...base, update_available: true }).kind, 'available')
  assert.equal(updateSummary(base).kind, 'current')
  assert.equal(updateSummary({ ...base, current: { known: false } }).kind, 'unknown')
  assert.equal(updateSummary({ ...base, upstream: { ...base.upstream, reason: 'historia divergente' } }).kind, 'unknown')
})
test('a failed subsequent check disables applying the previous head', () => {
  assert.equal(canReapplyLatest(null), false)
  assert.equal(canReapplyLatest({ ...base, upstream: { ...base.upstream, head_sha: 'main' } }), false)
})
test('manual reapply cannot bypass local drift when no engine update is suggested', () => {
  assert.equal(upgradeBlocked({ ...base, blocked_by_drift: false, drift: { any_custom: true } }), true)
  assert.equal(upgradeBlocked({ ...base, drift: { any_custom: false } }), false)
})
test('missing stable release is unknown, never a green up-to-date claim', () => {
  assert.equal(updateSummary({ tracking: 'releases', current: { known: true }, latest: null }).kind, 'unknown')
})
