#!/usr/bin/env python3
"""Which model does a given job — MODELS.md as code.

Role cards name a TIER, never a model. This module resolves (tier, data class)
to a concrete model, so re-pricing the whole company is one edit here rather
than eight prompt rewrites.

Two rules from MODELS.md are enforced rather than documented:

  The cost ladder — never let an expensive model do a cheap model's job, and
  never let a cheap model's output ship without a capable model reviewing it.

  Diversity at the gate — the reviewer runs on a different model family than
  the builder. Two instances of the same model share training and therefore
  share blind spots, and will agree on the same wrong thing.

Stdlib only. Prices are USD per million tokens, checked 2026-08; they move, so
`python company/ops/models.py --prices` prints them and the quarterly review in
STACK.md is the reminder to re-check.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

# Data classes, in the sense CHARTER.md means: does this touch a real,
# identifiable person? The default is `personal`, because the escalation is
# free and the leak is not.
PUBLIC = "public"
PERSONAL = "personal"


@dataclass(frozen=True)
class Model:
    id: str
    vendor: str
    usd_per_m_input: float
    usd_per_m_output: float
    first_party: bool  # may it see personal data? See CHARTER.md.
    # Subscription-metered work is not billed per token — it draws from a seat
    # you already pay for. The ledger counts RUNS for these, not dollars, so a
    # zero price here means "not metered", never "free".
    subscription: bool = False


# Anthropic pricing verified 2026-08. DeepSeek and local figures are
# order-of-magnitude: exact bulk-tier rates change often and the ledger only
# needs them accurate enough to trip a cap.
MODELS = {
    # Kept for the reviewer slot: authenticates with a claude.ai subscription
    # rather than an API key, so it needs no wallet. Nothing answers to it yet —
    # today the owner is the reviewer.
    "claude-code": Model("claude-code", "anthropic", 0.0, 0.0, True, subscription=True),
    "claude-opus-5": Model("claude-opus-5", "anthropic", 5.00, 25.00, True),
    "claude-sonnet-5": Model("claude-sonnet-5", "anthropic", 3.00, 15.00, True),
    "claude-haiku-4-5": Model("claude-haiku-4-5", "anthropic", 1.00, 5.00, True),
    "codex": Model("codex", "openai", 5.00, 25.00, False),
    # DeepSeek V4, 2026. Pro is statistically tied with frontier models on
    # SWE-bench Verified; Flash beats Pro on agentic benchmarks at roughly a
    # third of the output price. Prices below are order-of-magnitude — confirm
    # at signup. The controller only needs them accurate enough to trip a cap.
    "deepseek-v4-pro": Model("deepseek-v4-pro", "deepseek", 0.60, 2.20, False),
    "deepseek-v4-flash": Model("deepseek-v4-flash", "deepseek", 0.30, 0.75, False),
    "ollama/qwen": Model("ollama/qwen", "local", 0.0, 0.0, True),
}

# (tier, data class) → model id. Mirrors the resolution table in MODELS.md.
ROUTING = {
    # The engineer runs as an OpenHands agent on DeepSeek V4 Flash — see
    # .github/workflows/company-engineer.yml. Flash rather than Pro because an
    # agentic loop is what Flash is better at, and it is a third of the price;
    # cost is the binding constraint on this company, not capability. Either
    # way it is a THIRD PARTY, which is why the personal row is closed rather
    # than pointed somewhere.
    ("capable", PUBLIC): "deepseek-v4-flash",
    # No automated engineer may touch real records. This is not a gap waiting to
    # be filled with whatever is cheapest: until a first-party worker actually
    # exists and has been run, the owner is the engineer for these tickets. The
    # workflow gate refuses them before a prompt is composed; this refuses them
    # before a model is chosen. Two independent controls, on purpose.
    ("capable", PERSONAL): None,
    # The gate. The builder is DeepSeek, so the reviewer must not be — a second
    # instance of the same family shares its blind spots and will agree with it.
    # Nothing answers to this today, which means the owner is the reviewer, and
    # branch protection enforces that whether or not a worker ever appears.
    ("capable-alt", PUBLIC): "claude-code",
    ("capable-alt", PERSONAL): None,
    ("cheap-bulk", PUBLIC): "deepseek-v4-flash",
    ("cheap-bulk", PERSONAL): None,  # never routed — see resolve()
    ("reasoning-bulk", PUBLIC): "deepseek-v4-pro",
    ("reasoning-bulk", PERSONAL): None,
    ("local", PUBLIC): "ollama/qwen",
    ("local", PERSONAL): "ollama/qwen",
    # `mixed` is the SRE's tier: cheap polling, capable diagnosis. The runner
    # picks per step; this is the ceiling. Same vendor as the engineer because
    # it runs the same OpenHands path — and closed on personal data for the same
    # reason.
    ("mixed", PUBLIC): "deepseek-v4-flash",
    ("mixed", PERSONAL): None,
}

# Roles whose work is arithmetic, not judgement. Routing one to a model is a
# bug: a model deciding whether to stop spending money on models is a conflict
# of interest. See roles/07-controller.md.
NO_MODEL_ROLES = {"controller", "dispatcher"}


class RoutingError(Exception):
    """Raised instead of silently downgrading. A wrong route is worse than a
    stopped ticket — it is how personal data reaches the bulk tier."""


def resolve(tier: str, data_class: str = PERSONAL) -> Model:
    """Resolve a tier and data class to a concrete model.

    Unknown tiers and personal data on a bulk tier both raise. The bulk-tier
    case is the one that matters: it is the single point where CHARTER.md's
    data policy is enforced mechanically rather than by asking nicely.
    """
    if data_class not in (PUBLIC, PERSONAL):
        raise RoutingError(f"unknown data class {data_class!r}; use 'public' or 'personal'")

    key = (tier, data_class)
    if key not in ROUTING:
        raise RoutingError(f"unknown tier {tier!r} for {data_class} data")

    model_id = ROUTING[key]
    if model_id is None:
        raise RoutingError(
            f"tier {tier!r} may not touch personal data — "
            "escalate to the owner or reclassify the ticket (see CHARTER.md)"
        )
    return MODELS[model_id]


def cost(model: Model, input_tokens: int, output_tokens: int) -> float:
    """USD for one call. Plain arithmetic, deliberately."""
    return (
        input_tokens / 1_000_000 * model.usd_per_m_input
        + output_tokens / 1_000_000 * model.usd_per_m_output
    )


def different_family(a: Model, b: Model) -> bool:
    """The gate check: is the reviewer a different family than the builder?"""
    return a.vendor != b.vendor


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", action="store_true", help="print the price table")
    ap.add_argument("--tier")
    ap.add_argument("--data", default=PERSONAL, choices=[PUBLIC, PERSONAL])
    args = ap.parse_args()

    if args.prices or not args.tier:
        print(f"{'model':<22} {'vendor':<10} {'in $/M':>8} {'out $/M':>9}  personal?")
        for m in MODELS.values():
            print(f"{m.id:<22} {m.vendor:<10} {m.usd_per_m_input:>8.2f} "
                  f"{m.usd_per_m_output:>9.2f}  {'yes' if m.first_party else 'no'}")
        return 0

    try:
        m = resolve(args.tier, args.data)
    except RoutingError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"{args.tier} + {args.data} → {m.id} ({m.vendor})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
