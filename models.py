"""
Shared contract between Person A and Person B.
FROZEN after Step 0: don't change anything here without telling your teammate.
"""
import json
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field, field_validator


# ---------- PUBLIC: anyone can see this ----------
class Plan(BaseModel):
    id: int
    name: str
    activity: str  # cinema, restaurant, bar, karaoke, museum, walk, games, concert...
    price_min: int  # USD per person
    price_max: int
    start_hour: int  # 24h format, e.g. 19
    noise: Literal["low", "medium", "high"]
    crowd: Literal["low", "medium", "high"]
    description: str


# ---------- PRIVATE: never leaves the friend's agent ----------
class Friend(BaseModel):
    name: str
    budget: int  # max USD per person
    free_after: int  # 24h format, e.g. 19
    social_battery: int = Field(ge=1, le=5)
    tastes: str
    day_note: str


# ---------- WHAT LEAVES AN AGENT: this and nothing else ----------
class Vote(BaseModel):
    veto: list[bool]  # one per plan, True = no-go (no reason given)
    scores: list[int]  # one per plan, 0-10


# ---------- Helper ----------
def load_activities(path: str = "activities.json") -> list[Plan]:
    with open(path, encoding="utf-8") as f:
        return [Plan(**a) for a in json.load(f)]


# ---------- PRIVACY DIAL: what a user MAY choose to share ----------
# Public activity types, read from the public catalog (next to this file).
with open(Path(__file__).with_name("activities.json"), encoding="utf-8") as catalog_file:
    ACTIVITY_TYPES: set[str] = {activity["activity"] for activity in json.load(catalog_file)}


class SharedProfile(BaseModel):
    """Optional hints sent to the coordinator, anonymously.

    Privacy by construction: every field is a CLOSED value (no free text),
    so an agent cannot leak a name, a budget figure or a diary sentence here.
    Default = everything empty = the user shares nothing.
    """
    budget_tier: Literal["low", "medium", "high"] | None = None
    energy: Literal["low", "medium", "high"] | None = None
    mood: Literal["tired", "neutral", "festive"] | None = None
    wishes: list[str] = Field(default_factory=list)  # activity types only

    @field_validator("wishes")
    @classmethod
    def _only_known_activities(cls, wishes: list[str]) -> list[str]:
        # Drop anything that isn't a public activity type (blocks free-text leaks).
        return sorted({wish for wish in wishes if wish in ACTIVITY_TYPES})


SHAREABLE_FIELDS = ["budget_tier", "energy", "mood", "wishes"]

# Public definitions, so both sides interpret shared values the same way.
BUDGET_TIERS = {"low": (0, 20), "medium": (21, 50), "high": (51, 10_000)}


def budget_to_tier(budget: int) -> str:
    """Coarse bucket instead of the exact amount."""
    for tier, (min_budget, max_budget) in BUDGET_TIERS.items():
        if min_budget <= budget <= max_budget:
            return tier
    return "low" if budget < 0 else "high"


def battery_to_energy(battery: int) -> str:
    """Social battery 1-2 -> low, 3 -> medium, 4-5 -> high."""
    if battery <= 2:
        return "low"
    if battery == 3:
        return "medium"
    return "high"


# A sealed voter: the coordinator can call it, but never sees the Friend inside.
Voter = Callable[[list[Plan]], Vote]


# ---------- Function signatures (contract) ----------
# Person A, private_agent.py:
#   share_profile(friend: Friend, allowed: set[str]) -> SharedProfile
#       fills ONLY the fields in `allowed` (subset of SHAREABLE_FIELDS), others stay None/[].
#       budget_tier via budget_to_tier, energy via battery_to_energy; the LLM may map
#       the private day_note to a `mood` value. Default (allowed empty) = SharedProfile().
#   private_vote(friend: Friend, plans: list[Plan]) -> Vote        # unchanged
#
# Person B, coordinator.py:
#   negotiate(profiles: list[SharedProfile], voters: list[Voter], max_rounds: int = 3)
#       -> tuple[Plan | None, list[Plan], list[Vote], int]   # (winner, plans, votes, rounds)
#       profiles arrive anonymous and shuffled (order unlinked from voters).
#       No hints shared -> shortlist = full catalog.
#   group_message(plan: Plan) -> str
#
# Rule: coordinator.py never imports Friend (nor private_agent).
#   app.py wires them:  voters = [lambda plans, f=f: private_vote(f, plans) for f in friends]
