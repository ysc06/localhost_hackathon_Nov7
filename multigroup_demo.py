"""
Multi-group memory isolation demo with cognee.

Run:  uv run python multigroup_demo.py

Question: several friend groups overlap (A is in groups 1 and 2, B in 1 and 3...).
Can one group's coordinator, or one friend's agent, see memory it shouldn't?

Layout:
- one PRIVATE dataset per person, `{person}_private`, reused across all their groups
- one SHARED dataset per group, `group_{id}_shared`: public outcomes only
  (chosen activity + veto COUNTS, no names)

Config: cognee reads the project's `.env` (Ollama LLM + nomic-embed-text embeddings,
already set up for the team). This script only adds demo-specific settings below.
"""
import asyncio
import json
import os
import random
from pathlib import Path

# ---------- Settings that must exist BEFORE importing cognee ----------
os.environ["TELEMETRY_DISABLED"] = "1"  # sovereign: no usage stats sent to cognee's servers
os.environ.setdefault("LOG_LEVEL", "ERROR")  # keep the demo output readable

import cognee  # noqa: E402
from cognee import SearchType  # noqa: E402
from cognee.modules.users.methods import create_user  # noqa: E402
from cognee.modules.users.permissions.methods import give_permission_on_dataset  # noqa: E402

from models import SharedProfile, battery_to_energy, budget_to_tier  # noqa: E402

# cognee 1.6.7 sends {"input": ...}, which only Ollama's /api/embed accepts
# (the legacy /api/embeddings returns an empty vector). Override here; .env wins over env vars.
cognee.config.set_embedding_endpoint("http://localhost:11434/api/embed")
# With LLM_PROVIDER=ollama, litellm appends /api/... itself: the endpoint must NOT end in /v1.
cognee.config.set_llm_endpoint("http://localhost:11434")

# Separate storage for this demo, so resetting it never wipes the app's real memories.
# Kept SHORT on purpose: LanceDB writes paths with two UUIDs inside, and Windows' 260-char
# limit (LongPathsEnabled=0) breaks cognify if the root is deep (e.g. inside the repo or .venv).
DEMO_ROOT = Path.home() / ".cgdemo"
cognee.config.system_root_directory(str(DEMO_ROOT / "system"))
cognee.config.data_root_directory(str(DEMO_ROOT / "data"))

random.seed(42)

# ---------- Demo data ----------
GROUPS = {"1": ["A", "B", "C"], "2": ["A", "C"], "3": ["D", "B"], "4": ["E", "F", "G"]}

# Private facts. Each person has a DISTINCTIVE keyword so we can detect leaks in search results.
PEOPLE = {
    "A": {"keyword": "pho", "budget": 18, "battery": 2, "mood": "tired", "wishes": ["restaurant"],
          "facts": "A loves pho and hates crowds. Today A had a stressful dentist appointment."},
    "B": {"keyword": "cello", "budget": 12, "battery": 3, "mood": "neutral", "wishes": ["walk"],
          "facts": "B is saving money this month. B practices the cello every evening."},
    "C": {"keyword": "salsa", "budget": 45, "battery": 5, "mood": "festive", "wishes": ["karaoke"],
          "facts": "C adores salsa dancing. C just finished a long marathon training run."},
    "D": {"keyword": "vinyl", "budget": 30, "battery": 4, "mood": "neutral", "wishes": ["concert"],
          "facts": "D collects vinyl records. D is allergic to cats."},
    "E": {"keyword": "climbing", "budget": 60, "battery": 4, "mood": "festive", "wishes": ["bar"],
          "facts": "E loves rock climbing. E had a job interview this morning."},
    "F": {"keyword": "origami", "budget": 25, "battery": 1, "mood": "tired", "wishes": ["cinema"],
          "facts": "F folds origami cranes to relax. F is vegan."},
    "G": {"keyword": "chess", "budget": 35, "battery": 3, "mood": "neutral", "wishes": ["games"],
          "facts": "G plays chess online at night. G is learning Japanese."},
}

# Public outcome per group: chosen activity + veto COUNTS only. The activity name is the keyword.
OUTCOMES = {
    "1": ("Indie cinema", "3 of 5 plans had at least one veto, 4 vetoes in total"),
    "2": ("Ramen dinner", "2 of 5 plans had at least one veto, 2 vetoes in total"),
    "3": ("Live jazz club", "1 of 5 plans had at least one veto, 1 veto in total"),
    "4": ("Sunset walk on the High Line", "4 of 5 plans had at least one veto, 6 vetoes in total"),
}

# What each person agreed to share, PER GROUP (default: nothing).
SHARING = {
    ("A", "1"): set(),               # A shares nothing with group 1...
    ("A", "2"): {"mood"},            # ...but shares their mood with group 2
    ("B", "1"): {"budget_tier"},
    ("B", "3"): {"budget_tier", "wishes"},
    ("C", "1"): set(),
    ("C", "2"): set(),
    ("D", "3"): {"energy"},
    ("E", "4"): {"energy", "wishes"},
    ("F", "4"): {"mood"},
    ("G", "4"): set(),
}


def shared_profile(person: str, group: str) -> SharedProfile:
    """Build ONLY the fields this person allowed for this group (closed values, no free text)."""
    allowed = SHARING.get((person, group), set())
    data = PEOPLE[person]
    values = {}
    if "budget_tier" in allowed:
        values["budget_tier"] = budget_to_tier(data["budget"])
    if "energy" in allowed:
        values["energy"] = battery_to_energy(data["battery"])
    if "mood" in allowed:
        values["mood"] = data["mood"]
    if "wishes" in allowed:
        values["wishes"] = data["wishes"]
    return SharedProfile(**values)


def coordinator_input(group: str) -> list[str]:
    """What a group's coordinator receives: anonymous, shuffled profiles (no person label)."""
    profiles = [shared_profile(person, group) for person in GROUPS[group]]
    random.shuffle(profiles)
    return [profile.model_dump_json(exclude_defaults=True).replace("{}", "nothing shared")
            for profile in profiles]


# ---------- Small helpers ----------
def header(title: str) -> None:
    print("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)


def check(ok: bool, label: str) -> bool:
    print(f"{'✅' if ok else '❌'} {label}")
    return ok


def as_text(results) -> str:
    """Flatten search results to lowercase text for keyword checks."""
    return json.dumps(results, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False).lower()


def found_people(text: str) -> list[str]:
    return [person for person, data in PEOPLE.items() if data["keyword"] in text]


def found_groups(text: str) -> list[str]:
    return [group for group, (activity, _) in OUTCOMES.items() if activity.lower() in text]


def show_raw(text: str, limit: int = 300) -> None:
    print(f"   raw: {text[:limit]}{'...' if len(text) > limit else ''}")


async def search(query: str, datasets=None, user=None):
    """CHUNKS search = raw stored text, no LLM paraphrasing: ideal for checking leaks."""
    return await cognee.search(query_text=query, query_type=SearchType.CHUNKS,
                               datasets=datasets, user=user, top_k=50)


# ---------- Demo ----------
async def main() -> None:
    header("0. RESET")
    # Fresh start: delete stored files, then graph + vector + relational metadata (users, datasets).
    await cognee.prune.prune_data()
    await cognee.prune.prune_system(metadata=True)
    print(f"cognee.prune.prune_data() + prune_system(metadata=True) on {DEMO_ROOT.name}/")
    print(f"LLM: {os.getenv('LLM_MODEL')} | embeddings: {os.getenv('EMBEDDING_MODEL')} (local Ollama)")

    header("1. MEMORY LAYOUT")
    for person, data in PEOPLE.items():
        await cognee.add(data["facts"], dataset_name=f"{person}_private")
    for group, (activity, vetoes) in OUTCOMES.items():
        await cognee.add(f"Group {group} outcome: the group chose {activity}. Veto counts: {vetoes}.",
                         dataset_name=f"group_{group}_shared")
    for group, members in GROUPS.items():
        print(f"group {group}  members {members}")
        print(f" ├─ group_{group}_shared   → chose '{OUTCOMES[group][0]}' + veto counts (no names)")
        for index, person in enumerate(members):
            branch = "└─" if index == len(members) - 1 else "├─"
            other_groups = [g for g, m in GROUPS.items() if person in m and g != group]
            reuse = f"  (same dataset reused in group {', '.join(other_groups)})" if other_groups else ""
            print(f" {branch} {person}_private{reuse}")

    print("\nBuilding the knowledge graph (cognify, local LLM)... this takes a few minutes.")
    all_datasets = [f"{person}_private" for person in PEOPLE] + [f"group_{g}_shared" for g in GROUPS]
    await cognee.cognify(datasets=all_datasets)

    header("2. WHAT EACH COORDINATOR RECEIVES (anonymous, shuffled)")
    inputs = {group: coordinator_input(group) for group in GROUPS}
    for group, profiles in inputs.items():
        print(f"group {group}: {profiles}")

    header("3. ISOLATION TESTS")
    results = []

    # Test 1: group 2's coordinator, scoped to group_2_shared only.
    text = as_text(await search("What did the group choose?", datasets=["group_2_shared"]))
    print("\nTest 1: group 2 coordinator searches ONLY group_2_shared")
    show_raw(text)
    results.append(check(found_groups(text) == ["2"] and not found_people(text),
                         f"only group 2's outcome (groups found: {found_groups(text)}, "
                         f"private facts found: {found_people(text)})"))

    # Test 2: A's agent, scoped to A_private only. A and C share groups 1 AND 2.
    text = as_text(await search("What does this person like and how was their day?",
                                datasets=["A_private"]))
    print("\nTest 2: A's agent searches ONLY A_private (A and C share 2 groups)")
    show_raw(text)
    results.append(check(found_people(text) == ["A"] and not found_groups(text),
                         f"only A's facts, nothing from C (people found: {found_people(text)})"))

    # Test 3: B is in groups 1 and 3. Group 3's coordinator must not see group 1's outcome.
    text = as_text(await search("What did the group choose?", datasets=["group_3_shared"]))
    print("\nTest 3: group 3 coordinator (B is also in group 1) searches group_3_shared")
    show_raw(text)
    results.append(check("1" not in found_groups(text) and "cello" not in text,
                         f"no group 1 outcome, no B private fact (groups found: {found_groups(text)})"))

    # Test 4: group 4 (E, F, G) overlaps with nobody.
    print("\nTest 4: group 4 is fully separate")
    leaks = []
    for group in ["1", "2", "3"]:
        other = as_text(await search("What did the group choose?", datasets=[f"group_{group}_shared"]))
        if "4" in found_groups(other):
            leaks.append(f"group_{group}_shared")
    for person in ["E", "F", "G"]:
        own = as_text(await search("What does this person like?", datasets=[f"{person}_private"]))
        if found_people(own) != [person]:
            leaks.append(f"{person}_private")
    results.append(check(not leaks, f"no cross-group data in or out of group 4 (leaks: {leaks or 'none'})"))

    # Test 5 (negative): NO dataset restriction -> everything the default user owns.
    text = as_text(await search("What do these people like, and what did the groups choose?"))
    print("\nTest 5 (negative): search WITHOUT restricting datasets")
    show_raw(text)
    leaked_people, leaked_groups = found_people(text), found_groups(text)
    print(f"   private facts returned: {leaked_people}")
    print(f"   group outcomes returned: {leaked_groups}")
    everything = len(leaked_people) == len(PEOPLE) and len(leaked_groups) == len(GROUPS)
    results.append(check(everything, "an unscoped query returns EVERYONE's data (expected: this is the leak)"))
    print("   ⚠️  WARNING: isolation here is LOGICAL, not cryptographic. All datasets live in one")
    print("      local store owned by one cognee user; the only barrier is the `datasets=` argument.")
    print("      One badly scoped query from the coordinator would read every private memory.")

    # Test 6: sharing scope. A shares mood with group 2 only. (A is the only "tired" member here.)
    print("\nTest 6: A's mood ('tired') reaches group 2's coordinator, not group 1's")
    in_group_2 = any('"mood":"tired"' in profile for profile in inputs["2"])
    in_group_1 = any('"mood"' in profile for profile in inputs["1"])
    results.append(check(in_group_2 and not in_group_1,
                         f"group 2 input has A's mood: {in_group_2} | group 1 input has a mood: {in_group_1}"))

    # Test 7 (fix): use cognee's per-user access control instead of trusting `datasets=`.
    print("\nTest 7 (fix): a dedicated cognee user for group 2's coordinator, read access on group_2_shared only")
    coordinator_2 = await create_user("coordinator-group-2@example.com", "demo-password")
    group_2_id = next(d.id for d in await cognee.datasets.list_datasets() if d.name == "group_2_shared")
    await give_permission_on_dataset(coordinator_2, group_2_id, "read")
    text = as_text(await search("What do these people like, and what did the groups choose?",
                                user=coordinator_2))  # NO datasets= on purpose
    show_raw(text)
    results.append(check(found_groups(text) == ["2"] and not found_people(text),
                         f"unscoped query as that user sees only group 2 (groups: {found_groups(text)}, "
                         f"private facts: {found_people(text)})"))

    header(f"RESULT: {sum(results)}/{len(results)} checks as expected")

    header("LIMITS")
    print("• Isolation is LOGICAL: one local store, scoped by dataset name. In production each private\n"
          "  memory should live on the user's own device or in a confidential enclave (e.g. Tinfoil),\n"
          "  so the coordinator's machine physically never holds it.")
    print("• Cross-group inference: A and C are together in groups 1 AND 2. Comparing veto counts\n"
          "  across both groups (and B being the only other member of group 1) can hint at who vetoed.")
    print("• cognee 1.6.7 has per-user ACL (create_user + give_permission_on_dataset, checked by\n"
          "  search). Test 7 shows it: give each coordinator its own cognee user with read access to\n"
          "  its group dataset only, and even an unscoped query can't reach private memories.\n"
          "  It is still enforced by the same process on the same disk, not by encryption.")


if __name__ == "__main__":
    asyncio.run(main())
