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
from models import BUDGET_TIERS, Plan, SharedProfile, Vote, Voter, load_activities

SHORTLIST_SIZE = 5
LEVEL = {"low": 0, "medium": 1, "high": 2}


def has_hints(profile: SharedProfile) -> bool:
    """True if this (anonymous) user shared at least one field."""
    return bool(profile.model_dump(exclude_defaults=True))


def hint_score(plan: Plan, profiles: list[SharedProfile]) -> int:
    """How well a public plan matches the shared hints (higher = better)."""
    score = 0
    for profile in profiles:
        if plan.activity in profile.wishes:
            score += 3
        if profile.budget_tier:
            max_budget = BUDGET_TIERS[profile.budget_tier][1]
            score += 1 if plan.price_min <= max_budget else -3
        wants_calm = profile.energy == "low" or profile.mood == "tired"
        wants_lively = profile.energy == "high" or profile.mood == "festive"
        if wants_calm:  # low noise/crowd: +1 each, high: -1 each
            score += (1 - LEVEL[plan.noise]) + (1 - LEVEL[plan.crowd])
        if wants_lively:  # the opposite
            score += (LEVEL[plan.noise] - 1) + (LEVEL[plan.crowd] - 1)
    return score


def propose_plans(activities: list[Plan], profiles: list[SharedProfile],
                  rejected_ids: set[int]) -> list[Plan]:
    """Shortlist candidate plans. Deterministic: same input, same output."""
    remaining = [plan for plan in activities if plan.id not in rejected_ids]
    if not any(has_hints(profile) for profile in profiles):
        # Nobody shared anything: no basis to filter, the private votes decide everything.
        return remaining
    ranked = sorted(remaining, key=lambda plan: (-hint_score(plan, profiles), plan.id))
    return ranked[:SHORTLIST_SIZE]


def pick_plan(plans: list[Plan], votes: list[Vote]) -> Plan | None:
    """Drop vetoed plans, then maximise the LOWEST score.

    min = nobody ends up at a plan they hate; the average would let one
    person be miserable as long as the others are happy.
    """
    acceptable = [index for index in range(len(plans))
                  if not any(vote.veto[index] for vote in votes)]
    if not acceptable:
        return None
    best_index = max(acceptable, key=lambda index: min(vote.scores[index] for vote in votes))
    return plans[best_index]


def negotiate(profiles: list[SharedProfile], voters: list[Voter], max_rounds: int = 3
              ) -> tuple[Plan | None, list[Plan], list[Vote], int]:
    """Propose -> private votes -> aggregate, up to max_rounds.

    Returns (winner, last_round_plans, last_round_votes, rounds_used).
    max_rounds is capped low on purpose: each failed round tells the coordinator
    a little (which ids failed), so few rounds limits guessing budgets by bisection.
    """
    activities = load_activities()
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


def group_message(plan: Plan) -> str:
    """Temporary version (replaced by the LLM one in B3)."""
    return f"Plan for tonight: {plan.name} at {plan.start_hour}:00, ${plan.price_min}-{plan.price_max} 🎉"


# ---------- Tests (fake profiles + fake sealed voters) ----------
if __name__ == "__main__":
    def fake_voter(plans: list[Plan]) -> Vote:
        # Stands in for a private agent: vetoes anything over $20, scores deterministically.
        return Vote(veto=[plan.price_min > 20 for plan in plans],
                    scores=[(plan.id * 7) % 11 for plan in plans])

    def veto_everything(plans: list[Plan]) -> Vote:
        return Vote(veto=[True] * len(plans), scores=[0] * len(plans))

    def show(title, result):
        winner, plans, votes, rounds = result
        print(f"\n=== {title} ===")
        print(f"candidates ({len(plans)}): {[plan.name for plan in plans]}")
        print(f"winner: {winner.name if winner else None} | rounds used: {rounds}")

    catalog = load_activities()

    # (a) nobody shares -> full catalog
    nobody = [SharedProfile(), SharedProfile(), SharedProfile()]
    assert propose_plans(catalog, nobody, set()) == catalog
    show("(a) nobody shares", negotiate(nobody, [fake_voter] * 3))

    # (b) one user shares karaoke + festive -> karaoke ranked first
    one_shares = [SharedProfile(), SharedProfile(wishes=["karaoke"], mood="festive"), SharedProfile()]
    ranked = propose_plans(catalog, one_shares, set())
    print("\n=== (b) one profile: wishes=['karaoke'], mood='festive' ===")
    for plan in ranked:
        print(f"  score {hint_score(plan, one_shares):+d}  {plan.name} ({plan.activity})")
    assert ranked[0].activity == "karaoke" and len(ranked) == 5
    show("(b) negotiate", negotiate(one_shares, [fake_voter] * 3))

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
    print("min vs average: picked", pick_plan(two, votes).name, "(average would pick", two[0].name + ")")
    print("\nAll B1 assertions passed.")
