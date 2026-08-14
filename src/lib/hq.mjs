// Board grouping for the /hq dashboard.
//
// Split out of hq.astro so it can be tested without a network or a build. Same
// reasoning as company/ops/board.py on the Python side: the logic that decides
// what the board *means* is the part worth testing, so it should not be tangled
// up with fetching or rendering.
//
// Plain .mjs rather than .ts so `node --test` can run it with no build step and
// no new dependency.

/** Display order. Anything not listed still renders, appended after these. */
export const STAGE_ORDER = [
  'status:inbox',
  'status:needs-spec',
  'status:ready',
  'status:building',
  'status:verify',
  'status:ship',
  'status:blocked',
];

export const STAGE_LABEL = {
  'status:inbox': 'Inbox',
  'status:needs-spec': 'Spec',
  'status:ready': 'Ready to build',
  'status:building': 'Building',
  'status:verify': 'Verify',
  'status:ship': 'Ready to ship',
  'status:blocked': 'Blocked',
  unfiled: 'Unfiled',
};

export const STAGE_OWNER = {
  'status:inbox': 'dispatcher',
  'status:needs-spec': 'analyst',
  'status:ready': 'engineer',
  'status:building': 'engineer',
  'status:verify': 'sre',
  'status:ship': 'you',
  'status:blocked': '—',
  unfiled: 'nobody',
};

export const labelNames = (issue) => (issue.labels ?? []).map((l) => l.name);

const newestFirst = (a, b) => String(b.created_at).localeCompare(String(a.created_at));

export const prefixed = (issue, prefix) =>
  labelNames(issue).find((n) => n.startsWith(prefix))?.slice(prefix.length) ?? '';

// How long a worker may hold a ticket before the claim is a dead lease.
// Restated from company/ops/assign.py (LEASE_MINUTES), which is the source of
// truth — the site is JS and cannot import Python, so the two must be kept in
// step by hand, exactly like the stage lists above restate the router's.
export const LEASE_MINUTES = 90;

/** The role holding this ticket, or '' when nobody is. */
export const claimOf = (issue) => prefixed(issue, 'claim:');

/**
 * When the current claim was applied, as an ISO string.
 * Read from the issue's label events, not `updated_at`, for the same reason
 * company/ops/dispatch.py's claim_since() does: `updated_at` also moves on
 * comments, so a worker that comments busily and finishes nothing would keep
 * renewing its own lease forever.
 *
 * `events` is the issue's /events payload. A claim whose label predates the
 * events window has no stamp; fall back to the issue's creation time so the
 * age errs toward expiry, never toward "held forever" — the dispatcher makes
 * the same call.
 */
export function claimSince(issue, events = []) {
  const label = `claim:${claimOf(issue)}`;
  const stamps = (events ?? [])
    .filter((e) => e?.event === 'labeled' && e?.label?.name === label)
    .map((e) => e.created_at)
    .sort();
  return stamps.length ? stamps[stamps.length - 1] : issue.created_at;
}

/**
 * Has the claim outlived its lease? Runs in the browser, not at build time:
 * the page is built at deploy and served for a heartbeat or two after, so the
 * judgment must be made against the reader's clock, not the builder's.
 */
export const claimExpired = (sinceIso, nowIso = new Date().toISOString()) =>
  Date.parse(nowIso) - Date.parse(sinceIso) > LEASE_MINUTES * 60000;

/**
 * Split the board into what needs the owner and everything else.
 * `needs:human` is the only call to action on the page, so it is separated
 * before any other grouping happens.
 */
export function splitNeedsHuman(issues) {
  const open = (issues ?? []).filter((i) => !i.pull_request); // a PR is not a ticket
  return {
    needsHuman: open.filter((i) => labelNames(i).includes('needs:human')).sort(newestFirst),
    rest: open.filter((i) => !labelNames(i).includes('needs:human')),
  };
}

/**
 * Group tickets by stage, newest first within each.
 *
 * Two deliberate behaviours, both so the page cannot hide a problem:
 *  - An unrecognised `status:` label still gets a group, appended at the end.
 *  - A ticket carrying no stage at all lands in `unfiled` rather than being
 *    dropped. A ticket the board cannot see is exactly what this page exists
 *    to surface.
 */
export function groupByStage(issues) {
  const seen = new Set();
  const groups = [];

  // First matching stage wins, and a ticket already placed is skipped. A ticket
  // CAN legitimately wear two stage labels: company/temporal/activities.py adds
  // labels before removing them, so a crash between the two calls leaves a
  // ticket briefly in both. Without this guard the dashboard would show it twice
  // and inflate every count. Matches the router in company/ops/board.py, which
  // also takes the first stage it finds.
  const take = (stage) => {
    const items = issues
      .filter((i) => !seen.has(i.number) && labelNames(i).includes(stage))
      .sort(newestFirst);
    items.forEach((i) => seen.add(i.number));
    if (items.length) groups.push({ stage, items });
  };

  STAGE_ORDER.forEach(take);

  const extras = [
    ...new Set(
      issues.flatMap((i) =>
        labelNames(i).filter((n) => n.startsWith('status:') && !STAGE_ORDER.includes(n)),
      ),
    ),
  ].sort();
  extras.forEach(take);

  const unfiled = issues.filter((i) => !seen.has(i.number)).sort(newestFirst);
  if (unfiled.length) groups.push({ stage: 'unfiled', items: unfiled });

  return groups;
}
