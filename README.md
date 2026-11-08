# Settled

Settled helps a group of friends pick a plan for tonight. Each friend gets a private AI agent, and the agents negotiate the plan without anyone's personal data being shared.

Everyone has said "I don't mind, whatever you want" when what they meant was "I'm exhausted", "I'm broke this month" or "I really want to sing." Settled lets each agent act on that private context while the group only ever sees a plan everyone can live with.

---

## How it works

```
 ┌──────────── private (one per friend) ────────────┐
 │  Friend data: budget, free time, social battery, │
 │  tastes, "how was my day", cognee memory         │
 │                     │                            │
 │              private_agent.py                    │
 └─────────┬───────────────────────┬────────────────┘
           │ optional              │ always
           ▼ SharedProfile         ▼ Vote
   (closed values only,      (veto + 0-10 score per plan,
    ticked by the friend)     no reasons, no names)
           │                       │
           └──── shuffled, anonymous ────┐
                                         ▼
                                  coordinator.py
                      shortlist → vote → drop vetoed → repeat (≤ 3 rounds)
                                         │
                                         ▼
                        🏆 winning plan + group-chat message
                                         │
                                         ▼
                                  booking_agent.py
                      real places & search links (public plan + city only)
```

1. **Private agents** (`private_agent.py`). Each friend's agent reads only that friend's data and returns a `Vote`:
   - **Hard vetoes are computed in code, not by the LLM.** A plan is vetoed if it costs more than the friend's budget or starts before they're free.
   - **Scores (0-10)** come from an LLM that weighs the friend's social battery, tastes, day note and private [cognee](https://github.com/topoteretes/cognee) memory. If the LLM fails, the agent falls back to a rule-based score.
2. **Privacy dial.** Each friend can tick what to share: budget *tier*, energy, mood and activity wishes. Every field is a closed value (`low/medium/high`, `tired/neutral/festive`, known activity types). No free text can leak, and nothing is shared by default.
3. **Coordinator** (`coordinator.py`). It sees only anonymous, shuffled profiles and sealed voter functions. It shortlists 5 plans (LLM + rule-based fallback), collects votes, discards vetoed plans, and picks the plan that **maximises the lowest score**, so nobody ends up somewhere they hate. When a round fails, it learns only *which* plans were vetoed, never by whom or why.
4. **Group message.** The LLM writes a short invite for the group chat from the public plan only. A number guard rejects invented times or prices.
5. **Discovery & Booking agent** (`booking_agent.py`). It turns the winner into real places via the Google Places API, or into plain Google Maps / Search links if no key is set. It never invents businesses and never books anything.

## Privacy guarantees

| Never leaves a friend's agent | May leave (if the friend ticks it) | Always leaves |
|---|---|---|
| Name, exact budget, free time, battery number, tastes text, day note, memories | Budget tier, energy level, mood, activity wishes | Veto flags + scores |

These are enforced by the code, not just by prompts:
- `coordinator.py` never imports `Friend` or `private_agent`, so private data isn't reachable from it.
- `SharedProfile` only accepts closed values, and its validator drops unknown wishes.
- Profiles and votes are shuffled separately, so they can't be linked to each other or to people.
- Hints reach the coordinator's LLM only as aggregated counts (e.g. `energy: 1 low, 1 high`).
- Each friend's cognee memory lives in an isolated dataset (`{name}_private`).
- LLMs run locally via Ollama by default. The voting LLM can optionally point to a confidential-inference endpoint.

## Quick start

**Requirements:** Python 3.12, [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com/).

```bash
# 1. Local models
ollama pull qwen2.5:3b          # coordinator LLM
ollama pull llama3.2:3b         # private-agent voting LLM
ollama pull nomic-embed-text    # cognee embeddings

# 2. Dependencies
uv sync

# 3. Config: create .env (see below)

# 4. Run the app
uv run streamlit run app.py
```

The app still runs if `private_agent.py` or `friends.py` can't load: it falls back to fake functions, and the sidebar shows which parts are real. If an LLM is offline, every LLM step falls back to rule-based logic.

### `.env`

| Variable | Purpose | Default |
|---|---|---|
| `LLM_MODEL` | Coordinator model (Ollama) | `qwen2.5:3b` |
| `OLLAMA_BASE_URL` | Coordinator endpoint | `http://localhost:11434/v1` |
| `VOTE_LLM_BASE_URL` / `VOTE_LLM_API_KEY` / `VOTE_LLM_MODEL` | Private-agent voting LLM (Ollama or a confidential-inference provider) | Ollama, `llama3.2:3b` |
| `LLM_PROVIDER`, `LLM_ENDPOINT`, `LLM_API_KEY` | cognee LLM settings | n/a |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_ENDPOINT`, `EMBEDDING_DIMENSIONS`, `HUGGINGFACE_TOKENIZER` | cognee embedding settings (e.g. `nomic-embed-text`) | n/a |
| `GOOGLE_MAPS_API_KEY` | Optional: real places in the booking step | search links only |

`.env` is git-ignored. Never commit it.

## Using the app

1. Open a friend's 🔒 tab and adjust their social battery, budget, free time, tastes and day note.
2. Tick what that friend agrees to share (all boxes start unchecked).
3. In 👥 **Group**, click **🎲 Find a plan**. You'll see the winner, a group-chat message, every candidate's veto/score summary, and exactly what left each agent.
4. Under **Turn Your Plan Into Reality**, enter a city and date, then click **📍 Find Places**.

## Demos & tests

```bash
uv run python coordinator.py              # negotiation scenarios, LLM shortlist, fallbacks
uv run python private_agent.py            # voting by battery level + veto check
uv run python private_agent.py --memory   # cognee isolation: Lea's memory can't see Sam's
uv run python redteam.py                  # prompt-injection attacks on the coordinator's context
uv run python multigroup_demo.py          # memory isolation across overlapping friend groups
uv run python booking_agent.py            # places / search links for sample plans
```

`redteam.py` prints everything the coordinator knows, then tries to extract names, budgets and moods. That data was never loaded into the process, so any specific answer is a hallucination, not a leak.

## Project layout

| File | Role |
|---|---|
| `app.py` | Streamlit UI that wires agents, coordinator and booking together |
| `models.py` | Shared contract: `Plan`, `Friend`, `Vote`, `SharedProfile`, privacy helpers |
| `private_agent.py` | Per-friend agent: hard vetoes, LLM scores, privacy dial, cognee memory |
| `coordinator.py` | Shortlisting, multi-round negotiation, max-min pick, group message |
| `booking_agent.py` | Turns the winning plan into real places and search links |
| `friends.py` | Three demo friends (Lea, Sam, Maya) |
| `activities.json` | Public catalog of 10 plans (price, start time, noise, crowd) |
| `redteam.py` | Prompt-injection red team |
| `multigroup_demo.py` | cognee isolation across overlapping groups |

## Business model (proposed, not live)

- Affiliate commissions on eligible event and activity bookings
- Referral revenue from venue and restaurant partners
- Premium AI concierge for recurring group plans, smarter memory and priority booking help

Today Settled only links to Google Maps / Search (plus Places results if a key is set). There's no affiliate tracking and no payments.

## Built with

Python 3.12 · Streamlit · Ollama (Qwen 2.5, Llama 3.2) · cognee · Pydantic · OpenAI SDK · Google Places API

*Built at the localhost hackathon, 7 November 2026.*
