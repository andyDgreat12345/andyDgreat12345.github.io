#!/usr/bin/env python3
"""The controller: counts what was spent, and stops the company when it goes over.

Deliberately has no model. A model deciding whether to stop spending money on
models is a conflict of interest and a failure mode — see roles/07-controller.md.
Everything here is arithmetic over an append-only ledger.

    # record one worker run
    python company/ops/controller.py record --ticket 12 --role engineer \
        --tier capable --data public --in 45000 --out 3000

    # daily report / breaker check
    python company/ops/controller.py report

Ledger lives at company/ops/ledger.jsonl by default, one JSON object per line,
append-only. In production point COMPANY_LEDGER at a path on the state branch so
it survives the runner — see ORG.md on where state lives.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import MODELS, RoutingError, cost, resolve  # noqa: E402

LEDGER = os.environ.get("COMPANY_LEDGER") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ledger.jsonl"
)

# Caps in USD. Overridable by env so the owner can raise them without a code
# change — but only the owner: no role may raise a cap (roles/07-controller.md).
DAILY_CAP = float(os.environ.get("COMPANY_DAILY_CAP", "5.00"))
MONTHLY_CAP = float(os.environ.get("COMPANY_MONTHLY_CAP", "100.00"))

WARN_AT = 0.70   # comment on the shift report
DEGRADE_AT = 0.90  # refuse new capable-tier work; cheap and local continue
TRIP_AT = 1.00   # set COMPANY_PAUSED=1 and escalate

# An anomaly is relative, not absolute: a ticket costing many times the running
# median is worth a look even when the day's total is fine.
ANOMALY_MULTIPLE = 5.0


@dataclass
class Entry:
    """One worker run. Written once, never edited — deleting ledger history is
    outside every role's boundary."""

    at: str
    ticket: int
    role: str
    model: str
    input_tokens: int
    output_tokens: int
    usd: float
    measured: bool = True  # False = the worker finished without reporting usage


@dataclass
class Verdict:
    spent_today: float
    spent_month: float
    daily_cap: float
    monthly_cap: float
    state: str  # ok | warn | degrade | tripped
    reason: str
    unmeasured_runs: int = 0
    anomalies: list = field(default_factory=list)

    @property
    def allows_capable(self) -> bool:
        """The 90% rule: capable-tier work stops first, cheap and local carry on.
        Degrading beats halting — a company that can still triage is still alive."""
        return self.state in ("ok", "warn")

    @property
    def should_pause(self) -> bool:
        return self.state == "tripped"


def _read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _append(path: str, entry: Entry) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(asdict(entry)) + "\n")


def record(ticket: int, role: str, tier: str, data_class: str,
           input_tokens: int, output_tokens: int, path: str = LEDGER,
           now: datetime | None = None) -> Entry:
    """Append one run to the ledger. Raises rather than guessing if the tier and
    data class do not resolve — an unroutable run is a bug, not a zero-cost run."""
    model = resolve(tier, data_class)
    entry = Entry(
        at=(now or datetime.now(timezone.utc)).isoformat(),
        ticket=ticket,
        role=role,
        model=model.id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usd=round(cost(model, input_tokens, output_tokens), 6),
    )
    _append(path, entry)
    return entry


def record_unmeasured(ticket: int, role: str, model_id: str,
                      path: str = LEDGER, now: datetime | None = None) -> Entry:
    """A worker finished without reporting token usage.

    Recorded as a hole in the ledger rather than as zero. Unmeasured spend
    reported as zero is exactly how a bill surprises someone — see the boundary
    in roles/07-controller.md.
    """
    entry = Entry(
        at=(now or datetime.now(timezone.utc)).isoformat(),
        ticket=ticket, role=role, model=model_id,
        input_tokens=0, output_tokens=0, usd=0.0, measured=False,
    )
    _append(path, entry)
    return entry


def assess(entries: list[dict], now: datetime,
           daily_cap: float = DAILY_CAP, monthly_cap: float = MONTHLY_CAP) -> Verdict:
    """Decide the spend state. Pure — no clock, no file, no network."""
    today = now.date()
    month_start = today.replace(day=1)

    def when(e: dict) -> date:
        return datetime.fromisoformat(e["at"]).date()

    todays = [e for e in entries if when(e) == today]
    months = [e for e in entries if when(e) >= month_start]

    spent_today = sum(e["usd"] for e in todays)
    spent_month = sum(e["usd"] for e in months)
    unmeasured = sum(1 for e in todays if not e.get("measured", True))

    # Anomalies are judged against the trailing week, so a single expensive day
    # does not become the new normal by raising its own baseline.
    week = [e["usd"] for e in entries
            if when(e) >= today - timedelta(days=7) and e.get("measured", True)]
    anomalies = []
    if len(week) >= 5:
        ordered = sorted(week)
        median = ordered[len(ordered) // 2]
        if median > 0:
            anomalies = [
                {"ticket": e["ticket"], "usd": e["usd"], "role": e["role"]}
                for e in todays
                if e["usd"] > median * ANOMALY_MULTIPLE
            ]

    daily_frac = spent_today / daily_cap if daily_cap else 0.0
    monthly_frac = spent_month / monthly_cap if monthly_cap else 0.0
    frac = max(daily_frac, monthly_frac)
    which = "daily" if daily_frac >= monthly_frac else "monthly"

    if frac >= TRIP_AT:
        state, reason = "tripped", f"{which} cap reached (${spent_today:.2f} today)"
    elif frac >= DEGRADE_AT:
        state, reason = "degrade", f"{frac:.0%} of the {which} cap — capable tier held"
    elif frac >= WARN_AT:
        state, reason = "warn", f"{frac:.0%} of the {which} cap"
    else:
        state, reason = "ok", f"{frac:.0%} of the {which} cap"

    return Verdict(
        spent_today=round(spent_today, 4),
        spent_month=round(spent_month, 4),
        daily_cap=daily_cap, monthly_cap=monthly_cap,
        state=state, reason=reason,
        unmeasured_runs=unmeasured, anomalies=anomalies,
    )


def render(v: Verdict, entries_today: list[dict]) -> str:
    icon = {"ok": "ok", "warn": "WARNING", "degrade": "DEGRADED", "tripped": "TRIPPED"}[v.state]
    lines = [
        f"**Spend — {icon}.** {v.reason}",
        "",
        f"- Today: ${v.spent_today:.2f} of ${v.daily_cap:.2f}",
        f"- Month: ${v.spent_month:.2f} of ${v.monthly_cap:.2f}",
        f"- Runs today: {len(entries_today)}",
    ]

    by_role: dict[str, float] = {}
    for e in entries_today:
        by_role[e["role"]] = by_role.get(e["role"], 0.0) + e["usd"]
    if by_role:
        lines += ["", "| role | spent |", "|---|---|"]
        lines += [f"| {r} | ${c:.2f} |" for r, c in sorted(by_role.items(), key=lambda kv: -kv[1])]

    if v.unmeasured_runs:
        lines += ["", f"**{v.unmeasured_runs} run(s) finished without reporting usage.** "
                      "That is a hole in the ledger, not zero spend — fix the worker."]
    if v.anomalies:
        lines += ["", f"**{len(v.anomalies)} anomalous ticket(s)** "
                      f"(over {ANOMALY_MULTIPLE:g}x the weekly median):"]
        lines += [f"- #{a['ticket']} ({a['role']}) ${a['usd']:.2f}" for a in v.anomalies]

    if v.state == "tripped":
        lines += ["", "Set `COMPANY_PAUSED=1`. Only the owner resumes a paused company, "
                      "and only the owner raises a cap."]
    elif v.state == "degrade":
        lines += ["", "New capable-tier work is refused; cheap and local tiers continue."]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("record")
    rec.add_argument("--ticket", type=int, required=True)
    rec.add_argument("--role", required=True)
    rec.add_argument("--tier", required=True)
    rec.add_argument("--data", default="personal", choices=["public", "personal"])
    rec.add_argument("--in", dest="input_tokens", type=int, default=0)
    rec.add_argument("--out", dest="output_tokens", type=int, default=0)
    rec.add_argument("--unmeasured", action="store_true",
                     help="worker reported no usage — record the hole")
    rec.add_argument("--model", help="model id, required with --unmeasured")

    sub.add_parser("report")

    args = ap.parse_args()

    if args.cmd == "record":
        try:
            if args.unmeasured:
                if not args.model or args.model not in MODELS:
                    print("--unmeasured needs a known --model", file=sys.stderr)
                    return 2
                e = record_unmeasured(args.ticket, args.role, args.model)
            else:
                e = record(args.ticket, args.role, args.tier, args.data,
                           args.input_tokens, args.output_tokens)
        except RoutingError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 1
        print(f"#{e.ticket} {e.role} {e.model} ${e.usd:.4f}"
              f"{'  (UNMEASURED)' if not e.measured else ''}")
        return 0

    entries = _read(LEDGER)
    now = datetime.now(timezone.utc)
    verdict = assess(entries, now)
    todays = [e for e in entries
              if datetime.fromisoformat(e["at"]).date() == now.date()]
    print(render(verdict, todays))
    # Exit code is the machine-readable half: 2 means the workflow should trip
    # the switch. A report that only prints is a report nothing can act on.
    return 2 if verdict.should_pause else 0


if __name__ == "__main__":
    raise SystemExit(main())
