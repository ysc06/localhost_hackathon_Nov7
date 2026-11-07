"""
Streamlit UI. Run with:  uv run streamlit run app.py

Works BEFORE integration: if private_agent.py / friends.py are missing or
broken, it falls back to fake functions so the UI can be tested.
"""

import random

import streamlit as st

from booking_agent import discover_options
from coordinator import group_message, negotiate
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
except Exception:
    DEFAULT_FRIENDS = [
        Friend(
            name="Lea",
            budget=30,
            free_after=19,
            social_battery=2,
            tastes="cozy places, movies, board games",
            day_note="Long exhausting day at work.",
        ),
        Friend(
            name="Sam",
            budget=15,
            free_after=18,
            social_battery=4,
            tastes="food, walks, museums",
            day_note="Chill day, saving money this month.",
        ),
        Friend(
            name="Maya",
            budget=60,
            free_after=20,
            social_battery=5,
            tastes="music, karaoke, bars",
            day_note="Just got good news, wants to celebrate!",
        ),
    ]

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
            shared_values["budget_tier"] = budget_to_tier(
                friend.budget
            )  # a bucket, never the amount
        if "energy" in allowed_fields:
            shared_values["energy"] = battery_to_energy(friend.social_battery)
        if "mood" in allowed_fields:
            battery = friend.social_battery
            shared_values["mood"] = (
                "tired" if battery <= 2 else "neutral" if battery == 3 else "festive"
            )
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

# ---------- UI ----------
st.set_page_config(page_title="No more 'whatever you want'", page_icon="🎯", layout="wide")
st.title('🎯 Settled')
st.caption(
    "You choose what your agent shares. Share nothing, you're still protected. "
    "Share more, you get better plans."
)

with st.sidebar:
    st.markdown("**Status**")
    st.write(("✅" if VOTE_IS_REAL else "🧪 fake") + " private votes")
    st.write(("✅" if SHARE_IS_REAL else "🧪 fake") + " shared profiles")
    st.write("✅ coordinator")

if "friends" not in st.session_state:
    st.session_state.friends = [friend.model_copy() for friend in DEFAULT_FRIENDS]

friends: list[Friend] = st.session_state.friends
allowed_fields_per_friend: list[set[str]] = []  # fields each friend agreed to share
tabs = st.tabs([f"🔒 {friend.name}" for friend in friends] + ["👥 Group"])

# --- One private tab per friend ---
for friend_index, friend in enumerate(friends):
    with tabs[friend_index]:
        st.info(f"Private to {friend.name}. Only what you tick below can leave this tab.")
        sliders_column, notes_column = st.columns(2)
        with sliders_column:
            battery = st.slider(
                "Social battery 🔋", 1, 5, friend.social_battery, key=f"battery_{friend_index}"
            )
            budget = st.slider(
                "Budget ($ max)", 0, 100, friend.budget, key=f"budget_{friend_index}"
            )
            free_after = st.slider(
                "Free after (h)", 16, 23, friend.free_after, key=f"free_after_{friend_index}"
            )
        with notes_column:
            tastes = st.text_area("Tastes", friend.tastes, key=f"tastes_{friend_index}")
            day_note = st.text_area(
                "How was my day?", friend.day_note, key=f"day_note_{friend_index}"
            )
        friends[friend_index] = Friend(
            name=friend.name,
            budget=budget,
            free_after=free_after,
            social_battery=battery,
            tastes=tastes,
            day_note=day_note,
        )

        st.markdown("#### 📤 Share with the group")
        st.caption("More sharing → better plans. Nothing is required.")
        checkbox_columns = st.columns(len(SHAREABLE_FIELDS))
        # Privacy default: every box starts unchecked (share nothing).
        ticked_fields = {
            field
            for column, field in zip(checkbox_columns, SHAREABLE_FIELDS, strict=True)
            if column.checkbox(
                SHARE_LABELS[field], value=False, key=f"share_{friend_index}_{field}"
            )
        }
        allowed_fields_per_friend.append(ticked_fields)

# --- Group tab ---
with tabs[-1]:
    shared_count = sum(len(fields) for fields in allowed_fields_per_friend)
    possible_count = len(friends) * len(SHAREABLE_FIELDS)
    st.caption(f"📤 {shared_count} fields shared out of {possible_count} possible")

    if st.button("🎲 Find a plan", type="primary"):
        with st.spinner("Agents are voting privately..."):
            profiles = [
                share_profile(friend, allowed_fields_per_friend[friend_index])
                for friend_index, friend in enumerate(friends)
            ]
            random.shuffle(profiles)  # anonymous: order no longer matches the friends
            # Sealed voters: the coordinator can ask for a vote, never read the Friend.
            voters = [
                lambda plans, friend=friend: private_vote(friend, plans) for friend in friends
            ]
            result = negotiate(profiles, voters)
            shuffled_votes = result[2][:]
            random.shuffle(shuffled_votes)  # can't tell whose vote is whose
            st.session_state.result = result
            st.session_state.shuffled_profiles = profiles
            st.session_state.shuffled_votes = shuffled_votes
            # One LLM call per search, not one per Streamlit rerun.
            st.session_state.group_message = group_message(result[0]) if result[0] else ""

    result = st.session_state.get("result")
    if result:
        winner, candidates, votes, rounds = result
        result_column, privacy_column = st.columns([3, 2])

        with result_column:
            if winner:
                st.success(
                    f"### 🏆 {winner.name}\n{winner.description}\n\n"
                    f"🕖 {winner.start_hour}:00 · 💵 ${winner.price_min}-{winner.price_max} "
                    f"· found in {rounds} round(s)"
                )
                st.text_area("📱 Message for the group chat", st.session_state.group_message)
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
            st.caption(
                "Both lists are shuffled separately: no names, and profiles can't be "
                "matched to votes."
            )

            st.markdown("**📤 Shared profiles** (what the coordinator used to shortlist)")
            for profile in st.session_state.shuffled_profiles:
                profile_json = profile.model_dump_json(
                    exclude_defaults=True
                )  # drops None and empty wishes
                st.code(profile_json if profile_json != "{}" else "nothing shared", language="json")

            st.markdown("**🗳️ Private votes** (veto + scores, no reasons)")
            for vote in st.session_state.shuffled_votes:
                st.code(vote.model_dump_json(), language="json")

            st.markdown("#### 🔒 Never shared")
            st.markdown(
                ":gray[exact budget · free time · social battery number · "
                "tastes text · how my day went · names]"
            )

        # ---------- Discovery & Booking Agent (only the public winning plan leaves) ----------
        if winner:
            st.divider()
            st.markdown("### Turn Your Plan Into Reality 🚀")
            st.caption(f"Winning activity: **{winner.name}**. Only this public plan + "
                       "the city/date below are sent to Google. No friend data, votes or memory.")
            city_column, date_column = st.columns(2)
            city = city_column.text_input("📍 City / location", "New York")
            date = date_column.date_input("📅 Date (optional)", value=None)

            if st.button("📍 Find Places"):
                st.session_state.discovery = discover_options(winner, city, date)

            if "discovery" in st.session_state:
                found = st.session_state.discovery
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
