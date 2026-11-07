"""
Streamlit UI. Run with:  uv run streamlit run app.py

Works BEFORE integration: if coordinator.py / private_agent.py / friends.py
are missing or broken, it falls back to fake functions so the UI can be tested.
"""
import random

import streamlit as st

from models import Friend, Plan, Vote, load_activities

# ---------- Real code if available, fakes otherwise ----------
try:
    from friends import FRIENDS as DEFAULT_FRIENDS
except Exception:
    DEFAULT_FRIENDS = [
        Friend(name="Lea", budget=30, free_after=19, social_battery=2,
               tastes="cozy places, movies, board games", day_note="Long exhausting day at work."),
        Friend(name="Sam", budget=15, free_after=18, social_battery=4,
               tastes="food, walks, museums", day_note="Chill day, saving money this month."),
        Friend(name="Maya", budget=60, free_after=20, social_battery=5,
               tastes="music, karaoke, bars", day_note="Just got good news, wants to celebrate!"),
    ]

try:
    from private_agent import private_vote
    VOTE_IS_REAL = True
except Exception:
    VOTE_IS_REAL = False

    def private_vote(friend: Friend, plans: list[Plan]) -> Vote:
        veto = [p.price_min > friend.budget or p.start_hour < friend.free_after for p in plans]
        scores = [random.randint(0, 10) for _ in plans]
        return Vote(veto=veto, scores=scores)

try:
    from coordinator import negotiate
    COORD_IS_REAL = True
except Exception:
    COORD_IS_REAL = False

    def negotiate(friends, vote_fn, max_rounds: int = 3):
        activities = load_activities()
        plans, votes = [], []
        for r in range(max_rounds):
            plans = random.sample(activities, k=min(5, len(activities)))
            votes = [vote_fn(f, plans) for f in friends]
            ok = [i for i in range(len(plans)) if not any(v.veto[i] for v in votes)]
            if ok:
                best = max(ok, key=lambda i: min(v.scores[i] for v in votes))
                return plans[best], plans, votes, r + 1
        return None, plans, votes, max_rounds

try:
    from coordinator import group_message
except Exception:
    def group_message(plan: Plan) -> str:
        return f"Plan for tonight: {plan.name} at {plan.start_hour}:00, ${plan.price_min}-{plan.price_max} 🎉"


# ---------- UI ----------
st.set_page_config(page_title="No more 'whatever you want'", page_icon="🎯", layout="wide")
st.title("🎯 No more \"whatever you want\"")
st.caption("Your agent knows your social battery. The group doesn't.")

with st.sidebar:
    st.markdown("**Status**")
    st.write(("✅" if VOTE_IS_REAL else "🧪 fake") + " private agents")
    st.write(("✅" if COORD_IS_REAL else "🧪 fake") + " coordinator")

if "friends" not in st.session_state:
    st.session_state.friends = [f.model_copy() for f in DEFAULT_FRIENDS]

friends: list[Friend] = st.session_state.friends
tabs = st.tabs([f"🔒 {f.name}" for f in friends] + ["👥 Group"])

# --- One private tab per friend ---
for i, f in enumerate(friends):
    with tabs[i]:
        st.info(f"Private to {f.name}. Nothing here is ever sent to the group.")
        c1, c2 = st.columns(2)
        with c1:
            battery = st.slider("Social battery 🔋", 1, 5, f.social_battery, key=f"bat_{i}")
            budget = st.slider("Budget ($ max)", 0, 100, f.budget, key=f"bud_{i}")
            free_after = st.slider("Free after (h)", 16, 23, f.free_after, key=f"free_{i}")
        with c2:
            tastes = st.text_area("Tastes", f.tastes, key=f"tastes_{i}")
            day_note = st.text_area("How was my day?", f.day_note, key=f"day_{i}")
        friends[i] = Friend(name=f.name, budget=budget, free_after=free_after,
                            social_battery=battery, tastes=tastes, day_note=day_note)

# --- Group tab ---
with tabs[-1]:
    if st.button("🎲 Find a plan", type="primary"):
        with st.spinner("Agents are voting privately..."):
            st.session_state.result = negotiate(friends, private_vote)

    result = st.session_state.get("result")
    if result:
        winner, plans, votes, rounds = result
        left, right = st.columns([3, 2])

        with left:
            if winner:
                st.success(f"### 🏆 {winner.name}\n{winner.description}\n\n"
                           f"🕖 {winner.start_hour}:00 · 💵 ${winner.price_min}-{winner.price_max} "
                           f"· found in {rounds} round(s)")
                st.text_area("📱 Message for the group chat", group_message(winner))
            else:
                st.error(f"No plan works for everyone after {rounds} round(s).")

            st.markdown("#### Candidate plans (last round)")
            for j, p in enumerate(plans):
                n_veto = sum(v.veto[j] for v in votes)
                worst = min(v.scores[j] for v in votes)
                if n_veto:
                    st.write(f"❌ **{p.name}**: no-go ({n_veto} {'person' if n_veto == 1 else 'people'})")
                else:
                    st.write(f"✅ **{p.name}**: lowest score {worst}/10")

        with right:
            st.markdown("#### 🔍 What left each agent")
            st.caption("Order shuffled: the coordinator can't tell whose vote is whose.")
            shuffled = votes[:]
            random.shuffle(shuffled)
            for v in shuffled:
                st.code(v.model_dump_json(), language="json")
            st.markdown("#### 🔒 Never shared")
            st.markdown(":gray[budget · free time · social battery · tastes · how my day went]")
