"""
Streamlit UI. Run with:  uv run streamlit run app.py

Pick who you are in the sidebar: you only see YOUR private settings and the
groups you belong to. Works BEFORE integration: if private_agent.py / friends.py
are missing or broken, it falls back to fake functions so the UI can be tested.
"""

import random

import streamlit as st

from booking_agent import discover_options
from coordinator import group_dataset, group_message, negotiate, past_outcomes
from models import (
    SHAREABLE_FIELDS,
    Friend,
    Plan,
    SharedProfile,
    Vote,
    battery_to_energy,
    budget_to_tier,
)

# ---------- Real code if available, fakes otherwise ----------
try:
    from friends import FRIENDS as DEFAULT_FRIENDS
    from friends import GROUPS
except Exception:
    DEFAULT_FRIENDS = [
        Friend(name="Lea", budget=30, free_after=19, social_battery=2,
               tastes="cozy places, movies, board games", day_note="Long exhausting day at work."),
        Friend(name="Sam", budget=15, free_after=18, social_battery=4,
               tastes="food, walks, museums", day_note="Chill day, saving money this month."),
        Friend(name="Maya", budget=60, free_after=20, social_battery=5,
               tastes="music, karaoke, bars", day_note="Just got good news, wants to celebrate!"),
        Friend(name="Nina", budget=35, free_after=19, social_battery=3,
               tastes="museums, jazz, ramen", day_note="Normal day, a bit curious to try something new."),
    ]
    GROUPS = {"1": ["Sam", "Lea", "Maya"], "2": ["Sam", "Maya"], "3": ["Maya", "Nina"]}

try:
    from private_agent import private_vote

    VOTE_IS_REAL = True
except Exception:
    VOTE_IS_REAL = False

    def private_vote(friend: Friend, plans: list[Plan]) -> Vote:
        # Hard constraints are checked privately; only a bare True/False leaves.
        veto = [
            plan.price_min > friend.budget or plan.start_hour < friend.free_after for plan in plans
        ]
        scores = [random.randint(0, 10) for _ in plans]
        return Vote(veto=veto, scores=scores)


try:
    from private_agent import share_profile

    SHARE_IS_REAL = True
except Exception:
    SHARE_IS_REAL = False

    # Simple keyword -> public activity type mapping (fake only; the real agent uses an LLM).
    TASTE_KEYWORDS = {
        "cinema": ["movie", "cinema", "film"],
        "games": ["game"],
        "restaurant": ["food", "dinner", "restaurant", "ramen", "pizza"],
        "walk": ["walk", "outdoor"],
        "museum": ["museum", "art"],
        "karaoke": ["karaoke", "sing"],
        "bar": ["bar", "drink", "cocktail"],
        "concert": ["music", "concert", "jazz"],
    }

    def share_profile(friend: Friend, allowed_fields: set[str]) -> SharedProfile:
        # Only ticked fields are filled; everything else stays None / [].
        shared_values = {}
        if "budget_tier" in allowed_fields:
            shared_values["budget_tier"] = budget_to_tier(friend.budget)  # a bucket, never the amount
        if "energy" in allowed_fields:
            shared_values["energy"] = battery_to_energy(friend.social_battery)
        if "mood" in allowed_fields:
            battery = friend.social_battery
            shared_values["mood"] = "tired" if battery <= 2 else "neutral" if battery == 3 else "festive"
        if "wishes" in allowed_fields:
            tastes = friend.tastes.lower()
            shared_values["wishes"] = [
                activity
                for activity, keywords in TASTE_KEYWORDS.items()
                if any(keyword in tastes for keyword in keywords)
            ]
        return SharedProfile(**shared_values)


SHARE_LABELS = {
    "budget_tier": "Budget tier (low / medium / high)",
    "energy": "Energy level (from my battery)",
    "mood": "Mood (tired / neutral / festive)",
    "wishes": "Activity wishes (from my tastes)",
}


def group_label(group_id: str) -> str:
    return f"Group {group_id} · {', '.join(GROUPS[group_id])}"


# ---------- Per-session state ----------
# Widgets that are not displayed lose their state in Streamlit, so each person's
# private settings and per-group sharing choices are kept here and survive user switches.
if "friends" not in st.session_state:
    st.session_state.friends = {friend.name: friend.model_copy() for friend in DEFAULT_FRIENDS}
if "sharing" not in st.session_state:
    st.session_state.sharing = {}  # (name, group_id) -> set of fields. Default: share nothing.
if "results" not in st.session_state:
    st.session_state.results = {}  # group_id -> last negotiation shown in that group's tab

friends: dict[str, Friend] = st.session_state.friends
sharing: dict[tuple[str, str], set[str]] = st.session_state.sharing

# ---------- UI ----------
st.set_page_config(page_title="No more 'whatever you want'", page_icon="🎯", layout="wide")
st.title('🎯 No more "whatever you want"')
st.caption(
    "You choose what your agent shares. Share nothing, you're still protected. "
    "Share more, you get better plans."
)

with st.sidebar:
    me = st.selectbox("👤 I am", list(friends), key="me")
    st.caption("You only see your own private data and the groups you belong to.")
    st.markdown("**Status**")
    st.write(("✅" if VOTE_IS_REAL else "🧪 fake") + " private votes")
    st.write(("✅" if SHARE_IS_REAL else "🧪 fake") + " shared profiles")
    st.write("✅ coordinator + group memory (cognee)")

my_groups = [group_id for group_id, members in GROUPS.items() if me in members]
tabs = st.tabs([f"🔒 Me ({me})"] + [f"👥 {group_label(group_id)}" for group_id in my_groups])

# --- My private tab: only MY data ---
with tabs[0]:
    friend = friends[me]
    st.info(f"Private to {me}. Only what you tick below can leave this tab, group by group.")
    sliders_column, notes_column = st.columns(2)
    with sliders_column:
        battery = st.slider("Social battery 🔋", 1, 5, friend.social_battery, key=f"battery_{me}")
        budget = st.slider("Budget ($ max)", 0, 100, friend.budget, key=f"budget_{me}")
        free_after = st.slider("Free after (h)", 16, 23, friend.free_after, key=f"free_after_{me}")
    with notes_column:
        tastes = st.text_area("Tastes", friend.tastes, key=f"tastes_{me}")
        day_note = st.text_area("How was my day?", friend.day_note, key=f"day_note_{me}")
    friends[me] = Friend(name=me, budget=budget, free_after=free_after,
                         social_battery=battery, tastes=tastes, day_note=day_note)

    st.markdown("#### 📤 What I share, per group")
    st.caption("More sharing → better plans. Nothing is required. You can share different "
               "things with different groups.")
    if not my_groups:
        st.write("You are not in any group yet.")
    for group_id in my_groups:
        st.markdown(f"**{group_label(group_id)}**")
        checkbox_columns = st.columns(len(SHAREABLE_FIELDS))
        current = sharing.get((me, group_id), set())  # privacy default: nothing ticked
        sharing[(me, group_id)] = {
            field
            for column, field in zip(checkbox_columns, SHAREABLE_FIELDS, strict=True)
            if column.checkbox(SHARE_LABELS[field], value=field in current,
                               key=f"share_{me}_{group_id}_{field}")
        }


def show_result(group_id: str) -> None:
    """Winner, candidates and exactly what crossed the privacy boundary for this group."""
    shown = st.session_state.results[group_id]
    winner, candidates, votes, rounds = shown["result"]
    result_column, privacy_column = st.columns([3, 2])

    with result_column:
        if winner:
            st.success(
                f"### 🏆 {winner.name}\n{winner.description}\n\n"
                f"🕖 {winner.start_hour}:00 · 💵 ${winner.price_min}-{winner.price_max} "
                f"· found in {rounds} round(s)"
            )
            st.text_area("📱 Message for the group chat", shown["message"], key=f"message_{group_id}")
        else:
            st.error(f"No plan works for everyone after {rounds} round(s).")

        st.markdown("#### Candidate plans (last round)")
        for plan_index, plan in enumerate(candidates):
            veto_count = sum(vote.veto[plan_index] for vote in votes)
            lowest_score = min(vote.scores[plan_index] for vote in votes)
            if veto_count:
                people = "person" if veto_count == 1 else "people"
                st.write(f"❌ **{plan.name}**: no-go ({veto_count} {people})")
            else:
                st.write(f"✅ **{plan.name}**: lowest score {lowest_score}/10")

    with privacy_column:
        st.markdown("#### 🔍 What left each agent")
        st.caption("Both lists are shuffled separately: no names, and profiles can't be "
                   "matched to votes.")
        st.markdown("**📤 Shared profiles** (what the coordinator used to shortlist)")
        for profile in shown["profiles"]:
            profile_json = profile.model_dump_json(exclude_defaults=True)  # drops None and empty wishes
            st.code(profile_json if profile_json != "{}" else "nothing shared", language="json")
        st.markdown("**🗳️ Private votes** (veto + scores, no reasons)")
        for vote in shown["votes"]:
            st.code(vote.model_dump_json(), language="json")
        st.markdown("#### 🔒 Never shared")
        st.markdown(":gray[exact budget · free time · social battery number · "
                    "tastes text · how my day went · names]")

    # ---------- Discovery & Booking Agent (only the public winning plan leaves) ----------
    if winner:
        st.divider()
        st.markdown("### Turn Your Plan Into Reality 🚀")
        st.caption(f"Winning activity: **{winner.name}**. Only this public plan + "
                   "the city/date below are sent to Google. No friend data, votes or memory.")
        city_column, date_column = st.columns(2)
        city = city_column.text_input("📍 City / location", "New York", key=f"city_{group_id}")
        date = date_column.date_input("📅 Date (optional)", value=None, key=f"date_{group_id}")

        if st.button("📍 Find Places", key=f"places_{group_id}"):
            shown["discovery"] = discover_options(winner, city, date)

        if "discovery" in shown:
            found = shown["discovery"]
            if found["error"]:
                st.warning(found["error"])
            if found["places"]:
                for place in found["places"]:
                    rating = f" · ⭐ {place['rating']}" if place["rating"] else ""
                    st.markdown(f"**{place['name']}**{rating}  \n{place['address']}  \n"
                                f"[Open in Google Maps]({place['maps_url']})")
            else:
                st.caption("Google Places API not configured: showing a live search instead.")
            st.link_button("Open places search ↗", found["links"]["places"])
            st.caption("We link out to real search results. We never complete or fake a booking.")


# --- One tab per group I belong to ---
for tab, group_id in zip(tabs[1:], my_groups, strict=True):
    with tab:
        members = GROUPS[group_id]
        shared_count = sum(len(sharing.get((name, group_id), set())) for name in members)
        st.caption(f"📤 {shared_count} fields shared out of {len(members) * len(SHAREABLE_FIELDS)} "
                   "possible in this group · other members' agents use their own private settings")

        if st.button("🎲 Find a plan", type="primary", key=f"find_{group_id}"):
            with st.spinner("Agents are voting privately..."):
                profiles = [share_profile(friends[name], sharing.get((name, group_id), set()))
                            for name in members]
                random.shuffle(profiles)  # anonymous: order no longer matches the members
                # Sealed voters: the coordinator can ask for a vote, never read the Friend.
                voters = [lambda plans, friend=friends[name]: private_vote(friend, plans)
                          for name in members]
                result = negotiate(profiles, voters, group_id=group_id)
                shuffled_votes = result[2][:]
                random.shuffle(shuffled_votes)  # can't tell whose vote is whose
                st.session_state.results[group_id] = {
                    "result": result,
                    "profiles": profiles,
                    "votes": shuffled_votes,
                    # One LLM call per search, not one per Streamlit rerun.
                    "message": group_message(result[0]) if result[0] else "",
                }

        if group_id in st.session_state.results:
            show_result(group_id)

        with st.expander(f"🧠 Group memory (cognee dataset `{group_dataset(group_id)}`)"):
            st.caption("Public outcomes only: chosen plan + veto counts. No names, no profiles, "
                       "no votes. The coordinator never reads anyone's private dataset.")
            history = past_outcomes(group_id)
            if history:
                for line in reversed(history):
                    st.write(f"• {line}")
            else:
                st.write("No outcome stored yet for this group.")

# ---------- Business model (proposed, not live) ----------
with st.expander("💰 How We Make Money"):
    st.markdown(
        "**Proposed revenue models: none of these are active integrations today.**\n\n"
        "- **Affiliate commissions** on eligible event and activity bookings\n"
        "- **Referral revenue** from future business partnerships (venues, restaurants)\n"
        "- **Premium AI concierge**: recurring group plans, smarter memory, priority booking help\n\n"
        ":gray[Currently live: plain Google Maps / Search links, plus Google Places "
        "results only if an API key is configured. No affiliate tracking, no payments.]"
    )
