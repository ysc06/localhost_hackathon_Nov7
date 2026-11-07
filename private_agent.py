"""
Person A: one private agent per friend.

Reads the friend's PRIVATE data + the PUBLIC plans, returns only a Vote.
Nothing else ever leaves this file: no reasons, no names, no notes.
"""
import asyncio
import json
import os

import cognee
from dotenv import load_dotenv
from openai import OpenAI

from models import Friend, Plan, Vote

load_dotenv()

# Local Llama via Ollama by default (private data never leaves the laptop).
client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    api_key=os.getenv("LLM_API_KEY", "ollama"),
)
MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")

LEVEL = {"low": 0, "medium": 1, "high": 2}


# ---------- 0. Private cognee memory: one isolated dataset per friend ----------
def _dataset(friend_name: str) -> str:
    return f"{friend_name}_private"


def store_private(friend_name: str, text: str) -> None:
    """Add a private note to this friend's OWN dataset and build its memory."""
    async def _run():
        await cognee.add(text, dataset_name=_dataset(friend_name))
        await cognee.cognify(datasets=[_dataset(friend_name)])
    asyncio.run(_run())


def recall_private(friend_name: str, query: str) -> str:
    """Search ONLY this friend's dataset. Returns '' if no memory or cognee fails."""
    async def _run():
        return await cognee.search(query_text=query, datasets=[_dataset(friend_name)],
                                   query_type=cognee.SearchType.CHUNKS)
    try:
        results = asyncio.run(_run())
        return "\n".join(c["text"] for r in results for c in r["search_result"])
    except Exception:
        return ""


# ---------- 1. Hard veto, in code (never trust the LLM with this) ----------
def is_vetoed(friend: Friend, plan: Plan) -> bool:
    return plan.price_min > friend.budget or plan.start_hour < friend.free_after


# ---------- 2. LLM scores (taste + mood) ----------
MOOD = {
    1: "completely exhausted. Loud, crowded places are torture tonight; only calm, quiet plans are OK",
    2: "tired. Prefers calm, quiet plans; loud crowded places are a bad idea",
    3: "okay. Medium energy, a balanced plan is best",
    4: "in a good mood and up for being social",
    5: "full of energy and wants to party. Loud, crowded, lively places are perfect; quiet plans feel boring",
}


def llm_scores(friend: Friend, plans: list[Plan], memory: str = "") -> list[int]:
    plan_lines = "\n".join(
        f"- id {p.id}: {p.name} | NOISE: {p.noise.upper()} | CROWD: {p.crowd.upper()} | "
        f"{p.activity}, ${p.price_min}-{p.price_max}. {p.description}"
        for p in plans
    )
    prompt = f"""You are {friend.name}'s private assistant. Score how much {friend.name} would enjoy each plan tonight, from 0 (hates it) to 10 (loves it).

Most important: tonight {friend.name} is {MOOD[friend.social_battery]}.
Match NOISE and CROWD to this energy level first, then consider:
- Tastes: {friend.tastes}
- How the day went: {friend.day_note}
- Private memories: {memory or "none"}

Plans:
{plan_lines}

Reply with JSON only, one score per plan id, like: {{"scores": {{"{plans[0].id}": 5, ...}}}}"""

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = json.loads(resp.choices[0].message.content)["scores"]
    # Validate: one score per plan, ints clamped to 0-10. Missing id -> error.
    return [max(0, min(10, int(raw[str(p.id)]))) for p in plans]


# ---------- 3. Fallback if the LLM is down or answers badly ----------
def rule_scores(friend: Friend, plans: list[Plan]) -> list[int]:
    # Battery 1 likes quiet (level 0), battery 5 likes loud (level 2).
    want = (friend.social_battery - 1) / 2  # 0..2
    return [
        round(10 - 2.5 * (abs(LEVEL[p.noise] - want) + abs(LEVEL[p.crowd] - want)))
        for p in plans
    ]


# ---------- Public entry point (the contract) ----------
def private_vote(friend: Friend, plans: list[Plan]) -> Vote:
    veto = [is_vetoed(friend, p) for p in plans]
    memory = recall_private(friend.name, f"How does {friend.name} feel and what does {friend.name} enjoy?")
    try:
        scores = llm_scores(friend, plans, memory)
    except Exception:
        scores = rule_scores(friend, plans)
    return Vote(veto=veto, scores=scores)


def isolation_test() -> None:
    """✅ A3: searching Lea's dataset never returns Sam's data."""
    store_private("Lea", "Lea is exhausted after a brutal week of deadlines. Lea hates loud bars.")
    store_private("Sam", "Sam secretly owes rent money and is broke this month. Sam loves museums.")
    leak = recall_private("Lea", "Who owes rent money?")
    print("Lea's dataset, asked about Sam's secret ->", repr(leak))
    print("✅ isolated" if "Sam" not in leak else "❌ LEAK")


if __name__ == "__main__":
    import sys
    from models import load_activities

    if "--memory" in sys.argv:  # uv run python private_agent.py --memory
        isolation_test()
        sys.exit()

    acts = {a.id: a for a in load_activities()}
    # 5 hardcoded plans: quiet -> loud
    plans = [acts[i] for i in (4, 3, 1, 2, 5)]  # walk, cinema, board games, karaoke, rooftop
    print("Plans:", [p.name for p in plans], "\n")

    base = dict(name="Test", budget=100, free_after=17,
                tastes="likes a bit of everything", day_note="Normal day.")
    for battery in (5, 1):
        f = Friend(social_battery=battery, **base)
        print(f"Battery {battery}:", private_vote(f, plans))

    print("\nVeto check (budget $15, free after 19h):")
    print(private_vote(Friend(social_battery=3, **{**base, "budget": 15, "free_after": 19}), plans))
