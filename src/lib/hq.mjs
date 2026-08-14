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
