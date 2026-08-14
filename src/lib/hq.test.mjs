// Tests for the /hq board grouping.  Run:  npm test
//
// These exist because the page itself cannot be exercised here without network
// access to the GitHub API, and an untested rendering path is a criterion
// nobody will ever check again.

import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import {
  claimExpired,
  claimOf,
  claimSince,
  groupByStage,
  prefixed,
  splitNeedsHuman,
  STAGE_LABEL,
  STAGE_ORDER,
} from './hq.mjs';

const issue = (number, names, created_at = `2026-08-${String(number).padStart(2, '0')}T00:00:00Z`) => ({
  number,
  title: `ticket ${number}`,
  created_at,
  labels: names.map((name) => ({ name })),
});

test('needs:human is separated from everything else', () => {
  const { needsHuman, rest } = splitNeedsHuman([
    issue(1, ['dept:site', 'status:ready']),
    issue(2, ['dept:hq', 'status:ready', 'needs:human']),
  ]);
  assert.deepEqual(needsHuman.map((i) => i.number), [2]);
  assert.deepEqual(rest.map((i) => i.number), [1]);
});

test('pull requests are not tickets', () => {
  const { needsHuman, rest } = splitNeedsHuman([
    issue(1, ['dept:site', 'status:ready']),
    { ...issue(2, ['status:ready']), pull_request: { url: 'x' } },
  ]);
  assert.deepEqual([...needsHuman, ...rest].map((i) => i.number), [1]);
});

test('groups follow the declared stage order, not label order', () => {
  const groups = groupByStage([
    issue(1, ['status:verify']),
    issue(2, ['status:inbox']),
    issue(3, ['status:ready']),
  ]);
  assert.deepEqual(groups.map((g) => g.stage), ['status:inbox', 'status:ready', 'status:verify']);
});

test('newest first within a stage', () => {
  const groups = groupByStage([
    issue(1, ['status:ready'], '2026-01-01T00:00:00Z'),
    issue(2, ['status:ready'], '2026-06-01T00:00:00Z'),
    issue(3, ['status:ready'], '2026-03-01T00:00:00Z'),
  ]);
  assert.deepEqual(groups[0].items.map((i) => i.number), [2, 3, 1]);
});

test('empty stages produce no group', () => {
  const groups = groupByStage([issue(1, ['status:ready'])]);
  assert.deepEqual(groups.map((g) => g.stage), ['status:ready']);
});

test('an empty board is a valid state, not a crash', () => {
  assert.deepEqual(groupByStage([]), []);
  assert.deepEqual(splitNeedsHuman([]), { needsHuman: [], rest: [] });
  assert.deepEqual(splitNeedsHuman(undefined), { needsHuman: [], rest: [] });
});

test('a ticket with no stage lands in unfiled rather than vanishing', () => {
  // The page exists to surface exactly this: work the board cannot see.
  const groups = groupByStage([issue(1, ['dept:site'])]);
  assert.deepEqual(groups.map((g) => g.stage), ['unfiled']);
  assert.deepEqual(groups[0].items.map((i) => i.number), [1]);
});

test('an unrecognised stage still renders, appended after the known ones', () => {
  const groups = groupByStage([issue(1, ['status:ready']), issue(2, ['status:invented'])]);
  assert.deepEqual(groups.map((g) => g.stage), ['status:ready', 'status:invented']);
});

test('a ticket is never counted in two groups', () => {
  const groups = groupByStage([issue(1, ['status:ready', 'status:verify'])]);
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  assert.equal(total, 1, 'ticket appeared in more than one stage');
});

test('dept and risk are read off the labels', () => {
  const i = issue(1, ['dept:market', 'risk:high', 'status:ready']);
  assert.equal(prefixed(i, 'dept:'), 'market');
  assert.equal(prefixed(i, 'risk:'), 'high');
  assert.equal(prefixed(issue(2, ['status:ready']), 'dept:'), '');
});

test('every ordered stage has a human-readable label', () => {
  // Otherwise a stage renders as a raw label string and looks like a bug.
  for (const stage of STAGE_ORDER) {
    assert.ok(STAGE_LABEL[stage], `no display label for ${stage}`);
  }
});

test('the claim role is read off the labels', () => {
  assert.equal(claimOf(issue(1, ['claim:engineer', 'status:building'])), 'engineer');
});

test('a ticket with no claim has no claim to show', () => {
  // The page renders the badge only when claimOf() is non-empty, so a no-claim
  // ticket must yield '' — not a placeholder the render path has to filter.
  assert.equal(claimOf(issue(2, ['status:ready'])), '');
  assert.equal(claimOf(issue(3, ['dept:site', 'risk:low'])), '');
});

test('claim age starts from the last labeled event, not updated_at', () => {
  // Same source as company/ops/dispatch.py claim_since(): `updated_at` also
  // moves on comments, so a worker that comments busily and finishes nothing
  // would keep renewing its own lease forever.
  const i = issue(4, ['claim:engineer', 'status:building']);
  const events = [
    { event: 'labeled', label: { name: 'claim:engineer' }, created_at: '2026-08-01T10:00:00Z' },
    { event: 'labeled', label: { name: 'status:building' }, created_at: '2026-08-01T10:05:00Z' },
    { event: 'unlabeled', label: { name: 'claim:engineer' }, created_at: '2026-08-01T10:30:00Z' },
    { event: 'labeled', label: { name: 'claim:engineer' }, created_at: '2026-08-01T11:00:00Z' },
  ];
  assert.equal(claimSince(i, events), '2026-08-01T11:00:00Z');
});

test('a claim with no label event ages from issue creation, toward expiry', () => {
  // An unreadable lease must fail toward release, never toward immortality —
  // the same call the dispatcher makes.
  const i = issue(5, ['claim:engineer'], '2026-08-01T09:00:00Z');
  assert.equal(claimSince(i, []), i.created_at);
});

test('a claim past its 90-minute lease is expired', () => {
  // 90 comes from LEASE_MINUTES in company/ops/assign.py, restated in hq.mjs.
  const start = '2026-08-01T00:00:00Z';
  assert.equal(claimExpired(start, '2026-08-01T01:29:00Z'), false, '89 minutes is still live');
  assert.equal(claimExpired(start, '2026-08-01T01:30:00Z'), false, 'exactly 90 minutes is not yet past');
  assert.equal(claimExpired(start, '2026-08-01T01:31:00Z'), true, '91 minutes is dead');
});
