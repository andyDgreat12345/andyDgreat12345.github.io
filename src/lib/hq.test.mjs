// Tests for the /hq board grouping.  Run:  npm test
//
// These exist because the page itself cannot be exercised here without network
// access to the GitHub API, and an untested rendering path is a criterion
// nobody will ever check again.

import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import { groupByStage, prefixed, splitNeedsHuman, STAGE_LABEL, STAGE_ORDER } from './hq.mjs';

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
