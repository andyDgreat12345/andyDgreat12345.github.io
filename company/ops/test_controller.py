#!/usr/bin/env python3
"""Tests for model routing and the spend controller.

    python company/ops/test_controller.py

The routing tests matter most: they are the mechanical enforcement of the data
policy in CHARTER.md. A regression here doesn't produce a wrong number, it
sends someone's admissions essay to the bulk tier.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import controller
import models

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def entry(usd, days_ago=0, ticket=1, role="engineer", measured=True,
          model="claude-opus-5"):
    return {
        "at": (NOW - timedelta(days=days_ago)).isoformat(),
        "ticket": ticket, "role": role, "model": model,
        "input_tokens": 0, "output_tokens": 0, "usd": usd, "measured": measured,
    }


def sub_run(days_ago=0, ticket=1):
    """One engineer run on the subscription: zero dollars, one unit of a
    finite allowance."""
    return entry(0.0, days_ago=days_ago, ticket=ticket, model="claude-code")


# ---------- routing: the data policy, mechanically ----------

def test_bulk_tier_refuses_personal_data():
    """The single most important test here. CHARTER.md says personal data never
    reaches the bulk tier; this is what makes that true rather than aspirational."""
    try:
        models.resolve("cheap-bulk", models.PERSONAL)
    except models.RoutingError as exc:
        assert "personal data" in str(exc)
    else:
        raise AssertionError("bulk tier accepted personal data")


def test_bulk_tier_serves_public_data():
    assert models.resolve("cheap-bulk", models.PUBLIC).vendor == "deepseek"


def test_reviewer_is_a_different_family_on_public_work():
    """Diversity at the gate: two instances of one model share blind spots."""
    builder = models.resolve("capable", models.PUBLIC)
    reviewer = models.resolve("capable-alt", models.PUBLIC)
    assert models.different_family(builder, reviewer), (builder.id, reviewer.id)


def test_diversity_yields_to_data_policy():
    """On personal data the cross-family reviewer is worth less than not sending
    applicant essays to a second vendor — so the alt tier stays first-party."""
    reviewer = models.resolve("capable-alt", models.PERSONAL)
    assert reviewer.first_party, reviewer.id


def test_unknown_tier_raises_rather_than_downgrading():
    """Silently falling back to a cheaper model is how data policy gets bypassed."""
    for tier in ("", "capable ", "premium"):
        try:
            models.resolve(tier, models.PUBLIC)
        except models.RoutingError:
            pass
        else:
            raise AssertionError(f"accepted unknown tier {tier!r}")


def test_every_routed_model_exists_in_the_price_table():
    for (tier, _), model_id in models.ROUTING.items():
        if model_id is not None:
            assert model_id in models.MODELS, f"{tier} routes to unknown model {model_id}"


def test_cost_is_plain_arithmetic():
    m = models.MODELS["claude-opus-5"]  # $5 in / $25 out per million
    assert abs(models.cost(m, 1_000_000, 0) - 5.00) < 1e-9
    assert abs(models.cost(m, 0, 1_000_000) - 25.00) < 1e-9
    assert abs(models.cost(m, 200_000, 20_000) - (1.00 + 0.50)) < 1e-9


def test_local_tier_is_free():
    assert models.cost(models.resolve("local", models.PERSONAL), 10**7, 10**7) == 0.0


# ---------- the breaker ----------

def test_under_cap_is_ok():
    v = controller.assess([entry(1.00)], NOW, daily_cap=5.0, monthly_cap=100.0)
    assert v.state == "ok" and v.allows_capable and not v.should_pause


def test_warns_at_seventy_percent():
    v = controller.assess([entry(3.60)], NOW, daily_cap=5.0, monthly_cap=100.0)
    assert v.state == "warn" and v.allows_capable


def test_degrades_before_it_stops():
    """At 90% capable work is held but cheap and local continue — a company that
    can still triage is still alive."""
    v = controller.assess([entry(4.60)], NOW, daily_cap=5.0, monthly_cap=100.0)
    assert v.state == "degrade"
    assert not v.allows_capable
    assert not v.should_pause


def test_trips_at_the_cap():
    v = controller.assess([entry(5.00)], NOW, daily_cap=5.0, monthly_cap=100.0)
    assert v.state == "tripped" and v.should_pause


def test_monthly_cap_trips_independently_of_the_daily_one():
    """A slow burn never breaches a daily cap but still empties the month."""
    spread = [entry(3.00, days_ago=d) for d in range(1, 13)]
    v = controller.assess(spread, NOW, daily_cap=5.0, monthly_cap=30.0)
    assert v.should_pause, v
    assert "monthly" in v.reason


def test_yesterdays_spend_does_not_count_against_today():
    v = controller.assess([entry(4.99, days_ago=1)], NOW, daily_cap=5.0, monthly_cap=100.0)
    assert v.state == "ok" and v.spent_today == 0.0


def test_empty_ledger_is_ok_not_a_crash():
    v = controller.assess([], NOW, daily_cap=5.0, monthly_cap=100.0)
    assert v.state == "ok" and v.spent_today == 0.0


# ---------- the second meter: subscription runs ----------

def test_subscription_work_is_not_invisible_to_the_breaker():
    """The bug this meter exists for. The engineer runs on a subscription, so
    every run prices at $0.00 — under a dollars-only cap the company's main
    worker could run all night and the breaker would report 0% of cap."""
    all_day = [sub_run(ticket=i) for i in range(60)]
    v = controller.assess(all_day, NOW, daily_cap=5.0, monthly_cap=100.0, run_cap=40)
    assert v.spent_today == 0.0          # genuinely no dollars
    assert v.should_pause, v.reason      # and genuinely stopped anyway


def test_run_cap_degrades_before_it_trips():
    v = controller.assess([sub_run(ticket=i) for i in range(37)], NOW,
                          daily_cap=5.0, monthly_cap=100.0, run_cap=40)
    assert v.state == "degrade" and not v.allows_capable


def test_the_tightest_meter_decides():
    """Under budget but out of runs is still stopped, and the reason says which."""
    v = controller.assess([sub_run(ticket=i) for i in range(40)] + [entry(0.10)],
                          NOW, daily_cap=5.0, monthly_cap=100.0, run_cap=40)
    assert v.should_pause and "subscription-run" in v.reason, v.reason


def test_metered_models_do_not_count_against_the_run_cap():
    v = controller.assess([entry(0.01, ticket=i) for i in range(50)], NOW,
                          daily_cap=5.0, monthly_cap=100.0, run_cap=40)
    assert v.subscription_runs == 0 and v.state == "ok"


def test_an_unknown_model_is_not_assumed_to_be_free():
    """Guessing which meter an unknown model uses is how a meter goes quiet."""
    v = controller.assess([entry(0.0, ticket=i, model="who-knows") for i in range(50)],
                          NOW, daily_cap=5.0, monthly_cap=100.0, run_cap=40)
    assert v.subscription_runs == 0


def test_report_names_the_run_meter_and_its_knob():
    runs = [sub_run(ticket=i) for i in range(40)]
    body = controller.render(controller.assess(runs, NOW, daily_cap=5.0,
                                               monthly_cap=100.0, run_cap=40), runs)
    assert "Subscription runs: 40 of 40" in body
    assert "COMPANY_DAILY_RUN_CAP" in body


def test_yesterdays_runs_do_not_count_against_today():
    v = controller.assess([sub_run(days_ago=1, ticket=i) for i in range(50)], NOW,
                          daily_cap=5.0, monthly_cap=100.0, run_cap=40)
    assert v.subscription_runs == 0 and v.state == "ok"


# ---------- honesty about holes ----------

def test_unmeasured_runs_are_counted_not_ignored():
    """Unmeasured spend reported as zero is how a bill surprises someone."""
    v = controller.assess([entry(0.10), entry(0.0, measured=False)], NOW,
                          daily_cap=5.0, monthly_cap=100.0)
    assert v.unmeasured_runs == 1
    assert "without reporting usage" in controller.render(v, [entry(0.0, measured=False)])


def test_anomaly_is_relative_to_the_trailing_week():
    week = [entry(0.10, days_ago=d, ticket=d) for d in range(1, 8)]
    v = controller.assess(week + [entry(2.00, ticket=99)], NOW,
                          daily_cap=50.0, monthly_cap=500.0)
    assert [a["ticket"] for a in v.anomalies] == [99], v.anomalies


def test_a_quiet_week_produces_no_anomalies():
    """Too little history to have a median means no claims, not false ones."""
    v = controller.assess([entry(2.00)], NOW, daily_cap=50.0, monthly_cap=500.0)
    assert v.anomalies == []


def test_report_names_the_caps_and_the_action():
    v = controller.assess([entry(5.00)], NOW, daily_cap=5.0, monthly_cap=100.0)
    body = controller.render(v, [entry(5.00)])
    assert "TRIPPED" in body
    assert "COMPANY_PAUSED=1" in body
    assert "only the owner raises a cap" in body


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
