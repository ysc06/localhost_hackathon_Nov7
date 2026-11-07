"""
Shared contract between Person A and Person B.
FROZEN after Step 0: don't change anything here without telling your teammate.
"""
import json
from typing import Literal

from pydantic import BaseModel, Field


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


# ---------- Function signatures (contract) ----------
# Person A, private_agent.py:
#   private_vote(friend: Friend, plans: list[Plan]) -> Vote
#
# Person B, coordinator.py:
#   negotiate(friends: list[Friend], vote_fn, max_rounds: int = 3)
#       -> tuple[Plan | None, list[Plan], list[Vote], int]   # (winner, plans, votes, rounds)
#   group_message(plan: Plan) -> str
