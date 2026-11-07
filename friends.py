"""
Person A: the demo friends and their groups.
PRIVATE data: only each friend's own agent (private_agent.py) ever reads it.
"""
from models import Friend

FRIENDS: list[Friend] = [
    # Tired
    Friend(name="Lea", budget=30, free_after=19, social_battery=2,
           tastes="cozy places, movies, board games", day_note="Long exhausting day at work."),
    # Tight budget
    Friend(name="Sam", budget=15, free_after=18, social_battery=4,
           tastes="food, walks, museums", day_note="Chill day, saving money this month."),
    # Wants to party
    Friend(name="Maya", budget=60, free_after=20, social_battery=5,
           tastes="music, karaoke, bars", day_note="Just got good news, wants to celebrate!"),
    # Curious, medium energy
    Friend(name="Nina", budget=35, free_after=19, social_battery=3,
           tastes="museums, jazz, ramen", day_note="Normal day, a bit curious to try something new."),
]

# Friend groups (names only: membership is not private data inside the group).
GROUPS: dict[str, list[str]] = {
    "1": ["Sam", "Lea", "Maya"],
    "2": ["Sam", "Maya"],
    "3": ["Maya", "Nina"],
}

if __name__ == "__main__":
    for f in FRIENDS:
        print(f)
