"""
Coordinator (Person B): proposes plans and aggregates anonymous votes.

Privacy by design:
- This file never imports Friend or private_agent. It cannot see names,
  exact budgets, social batteries or diary notes: they never reach it.
- It only gets `profiles` (anonymous, shuffled, only what users chose to share)
  and `voters` (sealed callables: plans in, Vote out).
- When a round fails it learns only WHICH plan ids were vetoed, never why or by whom.
- Activity prices / hours / noise are public venue data, so using them is fine.
"""

import logging
import os
import re
import sys
from collections import Counter
from functools import cache

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from models import BUDGET_TIERS, Plan, SharedProfile, Vote, Voter, load_activities

load_dotenv()
log = logging.getLogger(__name__)
MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
LLM_TIMEOUT_SECONDS = 60
# Local inference (Ollama): the prompt never leaves this machine.
client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama", timeout=LLM_TIMEOUT_SECONDS)

SHORTLIST_SIZE = 5
MAX_MESSAGE_LINES = 2
LEVEL = {"low": 0, "medium": 1, "high": 2}

# hint_score weights
WISH_MATCH_BONUS = 3
WITHIN_BUDGET_BONUS = 1
OVER_BUDGET_PENALTY = -3


@cache
def _catalog() -> tuple[Plan, ...]:
    """Public activity catalog, read from disk once per process."""
    return tuple(load_activities())


class Proposal(BaseModel):
    """The only thing we accept back from the LLM."""

    plan_ids: list[int]


def has_hints(profile: SharedProfile) -> bool:
    """True if this (anonymous) user shared at least one field."""
    return bool(profile.model_dump(exclude_defaults=True))


def hint_score(plan: Plan, profiles: list[SharedProfile]) -> int:
    """How well a public plan matches the shared hints (higher = better)."""
    score = 0
    for profile in profiles:
        if plan.activity in profile.wishes:
            score += WISH_MATCH_BONUS
        if profile.budget_tier:
            max_budget = BUDGET_TIERS[profile.budget_tier][1]
            score += WITHIN_BUDGET_BONUS if plan.price_min <= max_budget else OVER_BUDGET_PENALTY
        wants_calm = profile.energy == "low" or profile.mood == "tired"
        wants_lively = profile.energy == "high" or profile.mood == "festive"
        if wants_calm:  # low noise/crowd: +1 each, high: -1 each
            score += (1 - LEVEL[plan.noise]) + (1 - LEVEL[plan.crowd])
        if wants_lively:  # the opposite
            score += (LEVEL[plan.noise] - 1) + (LEVEL[plan.crowd] - 1)
    return score


def rank_by_hints(plans: list[Plan], profiles: list[SharedProfile]) -> list[Plan]:
    """Rule-based ranking (B1). Deterministic: ties broken by plan id."""
    return sorted(plans, key=lambda plan: (-hint_score(plan, profiles), plan.id))


def summarize_hints(profiles: list[SharedProfile]) -> str:
    """Aggregate the hints into COUNTS before they reach the LLM.

    Even though profiles are already anonymous, the LLM only sees totals
    ("energy: 1 low, 1 high"), so it can't reason about any single person.
    """
    nobody_count = sum(not has_hints(profile) for profile in profiles)
    lines = [f"{len(profiles)} people in the group; {nobody_count} shared nothing."]
    for field in ["budget_tier", "energy", "mood"]:
        counts = Counter(getattr(profile, field) for profile in profiles if getattr(profile, field))
        if counts:
            shared = ", ".join(f"{count} {value}" for value, count in sorted(counts.items()))
            lines.append(f"{field} ({sum(counts.values())} shared): {shared}")
    wishes = Counter(wish for profile in profiles for wish in profile.wishes)
    if wishes:
        lines.append(
            "wishes: " + ", ".join(f"{wish} x{count}" for wish, count in sorted(wishes.items()))
        )
    return "\n".join(lines)


def describe_plan(plan: Plan) -> str:
    """Public venue info only."""
    return (
        f"{plan.id}: {plan.name} | {plan.activity} | ${plan.price_min}-{plan.price_max} | "
        f"{plan.start_hour}:00 | noise {plan.noise} | crowd {plan.crowd}"
    )


def llm_shortlist(
    candidates: list[Plan], profiles: list[SharedProfile], rejected: list[Plan]
) -> list[int]:
    """Ask the LLM for SHORTLIST_SIZE plan ids. Raises on any failure (caller falls back)."""
    tiers = ", ".join(f"{tier} = ${low}-{high}" for tier, (low, high) in BUDGET_TIERS.items())
    prompt = (
        "Pick plans for a group evening.\n\n"
        "CANDIDATE PLANS (id: name | activity | price per person | start | noise | crowd):\n"
        + "\n".join(describe_plan(plan) for plan in candidates)
        + "\n\nANONYMOUS GROUP HINTS (aggregated counts, budget tiers: "
        + tiers
        + "):\n"
        + summarize_hints(profiles)
        + "\n\nALREADY REJECTED BY THE GROUP (do not propose again): "
        + (", ".join(plan.name for plan in rejected) or "none")
        + f"\n\nChoose exactly {SHORTLIST_SIZE} different plan ids from the candidates that fit "
        "the hints, but keep some variety for the people who shared nothing.\n"
        'Answer with JSON only: {"plan_ids": [id, id, id, id, id]}'
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful event planner. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return Proposal.model_validate_json(response.choices[0].message.content).plan_ids


def clean_shortlist(llm_ids: list[int], ranked: list[Plan]) -> list[Plan]:
    """Safety net: keep only real candidate ids, dedupe, then top up from the rule-based ranking."""
    by_id = {plan.id: plan for plan in ranked}
    shortlist: list[Plan] = []
    for plan_id in llm_ids:
        if plan_id in by_id and by_id[plan_id] not in shortlist:
            shortlist.append(by_id[plan_id])
    for plan in ranked:  # fill (never random) if the LLM gave fewer than 5 valid ids
        if len(shortlist) >= SHORTLIST_SIZE:
            break
        if plan not in shortlist:
            shortlist.append(plan)
    return shortlist[:SHORTLIST_SIZE]


def propose_plans(
    activities: list[Plan], profiles: list[SharedProfile], rejected_ids: set[int]
) -> list[Plan]:
    """Shortlist candidate plans: LLM first, rule-based ranking as a safety net."""
    remaining = [plan for plan in activities if plan.id not in rejected_ids]
    if not any(has_hints(profile) for profile in profiles):
        # Nobody shared anything: no basis to filter (and no LLM call), the private votes decide.
        return remaining
    ranked = rank_by_hints(remaining, profiles)
    if len(remaining) <= SHORTLIST_SIZE:
        return ranked  # nothing to choose: skip the LLM
    rejected = [plan for plan in activities if plan.id in rejected_ids]
    try:
        return clean_shortlist(llm_shortlist(remaining, profiles, rejected), ranked)
    except Exception as error:  # the demo must never crash
        log.warning("LLM shortlist failed (%s), using rule-based ranking", type(error).__name__)
        return ranked[:SHORTLIST_SIZE]


def pick_plan(plans: list[Plan], votes: list[Vote]) -> Plan | None:
    """Drop vetoed plans, then maximise the LOWEST score.

    min = nobody ends up at a plan they hate; the average would let one
    person be miserable as long as the others are happy.
    """
    acceptable = [
        index for index in range(len(plans)) if not any(vote.veto[index] for vote in votes)
    ]
    if not acceptable:
        return None
    best_index = max(acceptable, key=lambda index: min(vote.scores[index] for vote in votes))
    return plans[best_index]


def negotiate(
    profiles: list[SharedProfile], voters: list[Voter], max_rounds: int = 3
) -> tuple[Plan | None, list[Plan], list[Vote], int]:
    """Propose -> private votes -> aggregate, up to max_rounds.

    Returns (winner, last_round_plans, last_round_votes, rounds_used).
    max_rounds is capped low on purpose: each failed round tells the coordinator
    a little (which ids failed), so few rounds limits guessing budgets by bisection.
    """
    activities = list(_catalog())
    rejected_ids: set[int] = set()
    plans: list[Plan] = []
    votes: list[Vote] = []
    rounds_used = 0
    while rounds_used < max_rounds:
        candidates = propose_plans(activities, profiles, rejected_ids)
        if not candidates:  # catalog exhausted: stop early
            break
        rounds_used += 1
        plans = candidates
        votes = [voter(plans) for voter in voters]
        winner = pick_plan(plans, votes)
        if winner:
            return winner, plans, votes, rounds_used
        # Only reached if every plan was vetoed. We learn the ids, not the reasons.
        rejected_ids |= {plan.id for plan in plans}
    return None, plans, votes, rounds_used


class GroupMessage(BaseModel):
    """The only thing we accept back from the LLM for the group chat."""

    message: str


def fallback_message(plan: Plan) -> str:
    """Deterministic template used when the LLM is unavailable or untrustworthy."""
    return (
        f"Plan for tonight: {plan.name} at {plan.start_hour}:00, "
        f"${plan.price_min}-{plan.price_max} 🎉"
    )


def group_message(plan: Plan) -> str:
    """Short group-chat message built ONLY from the public plan (no votes, no profiles)."""
    prompt = (
        "Write a group chat message announcing tonight's plan.\n"
        f"Rules: at most {MAX_MESSAGE_LINES} short lines, 1 or 2 emojis, "
        "use ONLY these facts, invent nothing "
        "(no end time, no other prices, addresses or names, no hashtags, no 'reserve now').\n\n"
        f"Name: {plan.name}\nStart: {plan.start_hour}:00\n"
        f"Price per person: ${plan.price_min}-{plan.price_max}\nDescription: {plan.description}\n\n"
        'Answer with JSON only: {"message": "..."}'
    )
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        text = GroupMessage.model_validate_json(response.choices[0].message.content).message
        text = re.sub(r"\s*#\w+", "", text)  # small models love hashtags
        lines = [line.strip() for line in text.splitlines() if line.strip()][:MAX_MESSAGE_LINES]
        text = "\n".join(lines)
        # Cheap hallucination guard: every number must come from the plan (no invented end time).
        allowed_numbers = {"00"} | {
            str(n) for n in (plan.start_hour, plan.start_hour - 12, plan.price_min, plan.price_max)
        }
        allowed_numbers |= set(re.findall(r"\d+", plan.name + " " + plan.description))
        if not text or any(number not in allowed_numbers for number in re.findall(r"\d+", text)):
            return fallback_message(plan)
        return text
    except Exception as error:  # the demo must never crash
        log.warning("LLM message failed (%s), using template", type(error).__name__)
        return fallback_message(plan)


# ---------- Tests (fake profiles + fake sealed voters) ----------
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # emojis on Windows cp1252 consoles
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    def fake_voter(plans: list[Plan]) -> Vote:
        # Stands in for a private agent: vetoes anything over $20, scores deterministically.
        return Vote(
            veto=[plan.price_min > 20 for plan in plans],
            scores=[(plan.id * 7) % 11 for plan in plans],
        )

    def veto_everything(plans: list[Plan]) -> Vote:
        return Vote(veto=[True] * len(plans), scores=[0] * len(plans))

    def show(title: str, result: tuple[Plan | None, list[Plan], list[Vote], int]) -> None:
        winner, plans, _votes, rounds = result
        print(f"\n=== {title} ===")
        print(f"candidates ({len(plans)}): {[plan.name for plan in plans]}")
        print(f"winner: {winner.name if winner else None} | rounds used: {rounds}")

    catalog = load_activities()
    online_client = client
    offline_client = OpenAI(base_url="http://localhost:1/v1", api_key="x", timeout=2, max_retries=0)

    # (a) nobody shares -> full catalog
    nobody = [SharedProfile(), SharedProfile(), SharedProfile()]
    assert propose_plans(catalog, nobody, set()) == catalog
    show("(a) nobody shares", negotiate(nobody, [fake_voter] * 3))

    # (b) one user shares karaoke + festive -> karaoke ranked first
    one_shares = [
        SharedProfile(),
        SharedProfile(wishes=["karaoke"], mood="festive"),
        SharedProfile(),
    ]
    ranked = rank_by_hints(catalog, one_shares)[:SHORTLIST_SIZE]
    print("\n=== (b) one profile: wishes=['karaoke'], mood='festive' ===")
    print("rule-based ranking (fallback):")
    for plan in ranked:
        print(f"  score {hint_score(plan, one_shares):+d}  {plan.name} ({plan.activity})")
    assert ranked[0].activity == "karaoke" and len(ranked) == 5
    print("\nhint summary sent to the LLM:\n" + summarize_hints(one_shares))
    shortlist = propose_plans(catalog, one_shares, set())
    print("LLM shortlist:", [plan.name for plan in shortlist])
    assert len(shortlist) == 5 and len({plan.id for plan in shortlist}) == 5
    show("(b) negotiate", negotiate(one_shares, [fake_voter] * 3))

    # (b') richer anonymous hints
    mixed = [
        SharedProfile(energy="low", mood="tired", wishes=["cinema"]),
        SharedProfile(budget_tier="low", energy="high", wishes=["karaoke"]),
        SharedProfile(),
    ]
    summary = summarize_hints(mixed)
    print("\n=== (b') mixed hints ===\nhint summary sent to the LLM:\n" + summary)
    for private_word in ["Lea", "Sam", "Maya", "budget=", "battery", "day"]:
        assert private_word not in summary, private_word
    print("LLM shortlist:", [plan.name for plan in propose_plans(catalog, mixed, set())])

    # Safety net: bad / duplicate / missing ids are cleaned and topped up (not random)
    cleaned = clean_shortlist([99, 3, 3, -1], rank_by_hints(catalog, mixed))
    print("\nclean_shortlist([99, 3, 3, -1]) ->", [plan.id for plan in cleaned])
    assert cleaned[0].id == 3 and len(cleaned) == 5 and len({plan.id for plan in cleaned}) == 5

    # LLM unreachable -> rule-based ranking, no crash
    client = offline_client
    offline = propose_plans(catalog, one_shares, set())
    assert offline == ranked
    print("LLM offline ->", [plan.name for plan in offline])
    client = online_client

    # (c) everything vetoed -> None, never more than 3 rounds
    result = negotiate(one_shares, [veto_everything] * 3)
    show("(c) everything vetoed (with hints: 5 plans per round)", result)
    assert result[0] is None and result[3] <= 3
    result = negotiate(nobody, [veto_everything] * 3)
    show("(c') everything vetoed (nobody shares: full catalog in round 1)", result)
    assert result[0] is None

    # pick_plan uses the minimum, not the average
    two = catalog[:2]
    votes = [Vote(veto=[False, False], scores=[10, 6]), Vote(veto=[False, False], scores=[2, 5])]
    # average: plan 0 = 6.0, plan 1 = 5.5 -> average would pick plan 0 (someone at 2/10)
    # min:     plan 0 = 2,   plan 1 = 5   -> we pick plan 1 (nobody below 5/10)
    assert pick_plan(two, votes) == two[1]
    print(
        "min vs average: picked",
        pick_plan(two, votes).name,
        "(average would pick",
        two[0].name + ")",
    )
    # B3: group message (LLM, then template if offline)
    karaoke = next(plan for plan in catalog if plan.activity == "karaoke")
    print("\n=== B3 group message ===")
    for _ in range(3):
        message = group_message(karaoke)
        print(("[template] " if message == fallback_message(karaoke) else "[llm] ") + message)
        assert 0 < len(message.splitlines()) <= MAX_MESSAGE_LINES and "#" not in message
    client = offline_client
    print("offline ->", group_message(karaoke))
    assert group_message(karaoke) == fallback_message(karaoke)
    client = online_client

    print("\nAll B1 + B2 + B3 assertions passed.")
