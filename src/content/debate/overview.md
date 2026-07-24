---
title: "A self-improving AI system for debate prep"
summary: "An agent system that researches a resolution, writes both sides, debates itself under real judges, and rewrites its own prep from what it learns — round after round."
order: 1
date: 2026-07-19
kind: method
tags: ["overview", "public-forum", "agents"]
---

Public Forum debate turns over a new resolution roughly every month. For each one a
competitor has to research both sides, cut evidence, write cases, anticipate the
opponent, and decide what to run in front of which judge. I built a system that does the
mechanical depth of that work — and, more interestingly, one that **gets better every
time it runs.**

## What it does

Give it a resolution and it runs a full pipeline:

1. **Analysis** — maps the definitions, the ground each side gets, and the research
   questions that could break either way.
2. **Research + evidence** — fetches real sources and cuts cards to a strict standard:
   verbatim quotes, author qualifications, no paraphrase or clipping. A card that can't
   be produced on an evidence challenge doesn't exist.
3. **Cases** — writes both sides in a standardized form: every contention is
   *topic → uniqueness → link → stacked warrants → weighed impacts*, and every claim has
   to finish the sentence "…because ___."
4. **Simulated rounds** — two teams, each with a different debate philosophy, prep in
   isolation (neither can see the other's files) and debate a full round: constructives,
   crossfires, rebuttals, summaries, final foci.
5. **Judging** — a three-judge panel scores it the way real panels split: a lay parent,
   a technical "flow" judge, and an evidence judge who reads the cards.
6. **Reflection** — after the round, the system studies the judge feedback and rewrites
   its own prep files, with a note on *why* each change was made.

## The idea that makes it work

Most "AI debate" tools generate a case and stop. The point of this one is the loop: each
round is an experiment, and what it learns is **promoted back into the canonical prep**,
so the next round starts from a stronger case and tests it against a better-prepped
opponent. Arguments that survive escalating attack are kept; arguments that quietly die
under pressure are cut *before* a real opponent finds the hole.

In the first two test rounds on a war-powers resolution, the system caught a landmine in
its own evidence — a flagship card whose own author could be quoted *against* the side
citing it — and flagged it before it could ever cost a real round. That is the whole
value: finding the weakness in the practice room, not the elimination round.

## Why I'm sharing the method and not the prep

The system's *method* — how it writes cases, cuts cards, structures speeches, and learns
— is public, and these writeups walk through it. The *live prep* for a current topic
stays private, because publishing this month's case is just handing it to the people
you're about to debate. So: read how it works, not what it's running this week.
