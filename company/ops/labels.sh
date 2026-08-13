#!/usr/bin/env bash
# Create the company's label vocabulary on a repo. Idempotent — safe to re-run,
# and safe to run against all four repos so the dispatcher speaks one language
# everywhere.
#
#   ./company/ops/labels.sh andyDgreat12345/andyDgreat12345.github.io
#
# Needs the `gh` CLI, authenticated. This is a laptop task, done once per repo.

set -euo pipefail
REPO="${1:?usage: labels.sh owner/repo}"

label() {  # name, colour, description
  gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force >/dev/null
  echo "  $1"
}

echo "Labelling $REPO"

# Departments — which product line owns the ticket.
label "dept:site"        "1f6feb" "Personal site / front office"
label "dept:casewriter"  "1f6feb" "AI case writer tool"
label "dept:market"      "1f6feb" "Chinese stocks prediction model"
label "dept:admissions"  "1f6feb" "College acceptance model"
label "dept:hq"          "1f6feb" "The company itself"

# Size — size:l requires the owner's approval before an engineer starts.
label "size:s"           "c5def5" "Under an agent-hour"
label "size:m"           "c5def5" "A few agent-hours"
label "size:l"           "c5def5" "Needs owner approval on the spec first"

# Risk — drives who may merge, and whether auto-merge is allowed at all.
label "risk:low"         "0e8a16" "Reversible, no user impact; auto-merge eligible"
label "risk:med"         "fbca04" "User-visible or awkward to undo"
label "risk:high"        "d93f0b" "Money, credentials, personal data, or public"

# Stages — exactly one on a ticket at a time; the dispatcher routes on these.
label "status:inbox"      "ededed" "Filed, not yet triaged"
label "status:needs-spec" "ededed" "Analyst: write acceptance criteria"
label "status:ready"      "ededed" "Engineer: build it"
label "status:building"   "ededed" "Claimed by an engineer"
label "status:verify"     "ededed" "SRE: prove it runs"
label "status:ship"       "ededed" "Owner: merge and deploy"
label "status:done"       "ededed" "Shipped and reported"
label "status:blocked"    "b60205" "Cannot proceed; reason in a comment"

# The escalation flag. The dispatcher will not touch anything wearing this.
label "needs:human"      "5319e7" "Owner's call — agents must not act"

echo "Done. Now create a Project board with one column per status label."
