# Work log: what Claude did (hackathon, 2026-11-07)

Project: "No more 'whatever you want'": private agents negotiate a group plan without sharing raw private data.
Branch: `setup-env` (not pushed yet: GitHub returned 403, `Fitiantsoa` needs collaborator access on `ysc06/localhost_hackathon_Nov7`).

## 1. Initialization check
- `models.py`, `activities.json` (10 plans, all validate), `app.py` (fallback fakes): OK.
- Found: `models - Copie.py` duplicate (left out of git), no Python env, no `.gitignore`, no Ollama models.

## 2. Ollama models
- `qwen2.5:7b` would take ~2.5 h at ~520 KB/s, so we switched to **`qwen2.5:3b`** (+ `nomic-embed-text`).
- The model name lives in `.env` (`LLM_MODEL`) so it can be swapped back in one line.

## 3. Environment (commit `22b9bd8`)
- Standalone uv project, Python 3.12: cognee 1.6.7, streamlit 1.67.0, openai, pydantic, python-dotenv.
- `uv init` had registered the repo in a parent workspace (`C:\Users\afiti\hack\pyproject.toml`): reverted, re-created with `--no-workspace`.
- `.gitignore`: `.venv`, `.env`, `.idea`, `__pycache__`, cognee storage. `.idea/` untracked.
- `.env` (not committed): Ollama settings for cognee (LLM + embeddings).
- `.claude/agents/pr.md`: a PR agent with guard checks (frozen contract, no private data, no cross-imports).

## 4. Privacy dial (commit `64a0ac2`)
- `models.py`: `SharedProfile` (closed values only, unknown wishes dropped), `SHAREABLE_FIELDS`,
  `BUDGET_TIERS`, `budget_to_tier`, `battery_to_energy`, `Voter` alias, updated contract.
- `app.py`: per-friend "Share with the group" checkboxes (all off by default), fake `share_profile`,
  fake `negotiate(profiles, voters)`, shuffled profiles and votes shown separately, shared-fields counter.
- Renamed single-letter variables to readable names; fixed 3 leftover names that crashed `match_score`.

## 5. Person B: coordinator.py
### B1: loop + aggregation (done)
- `propose_plans`: removes rejected ids; nobody shared → full catalog; otherwise deterministic
  ranking by hints (wishes, budget tier vs public price, calm/lively vs noise and crowd), top 5.
- `pick_plan`: drop vetoed plans, maximise the minimum score (nobody ends up at a plan they hate).
- `negotiate`: max 3 rounds, learns only rejected ids; stops early if the catalog runs out.
- Tests (`uv run python coordinator.py`): (a) nobody shares → 10 candidates; (b) karaoke + festive →
  karaoke ranked first; (c) everything vetoed → `None` (2 rounds with hints, since 10 plans / 5 per round);
  min-vs-average check passes.
- No import of `Friend` or `private_agent`.

### B2: AI shortlist (done)
- Local LLM via Ollama (`OpenAI(base_url="http://localhost:11434/v1")`), model from `LLM_MODEL` in `.env` (`qwen2.5:3b`).
- `summarize_hints`: profiles aggregated into COUNTS before reaching the LLM (e.g. `energy (2 shared): 1 high, 1 low`).
- `llm_shortlist`: public catalog + hint counts + already-rejected plans → `{"plan_ids": [...]}`, validated by pydantic `Proposal`.
- `clean_shortlist`: keeps only real ids, dedupes, tops up from the rule-based ranking (never random).
- Nobody shared → no LLM call, full catalog. ≤5 plans left → no LLM call. Any LLM error → rule-based ranking.
- Tests: LLM shortlists returned for both hint scenarios; hint summary checked for names/private words;
  `clean_shortlist([99, 3, 3, -1])` → `[3, 1, 4, 6, 8]`; LLM offline → rule-based ranking, no crash.
### B3: group message (done)
- `group_message(plan)`: LLM gets ONLY the public plan (never votes or profiles), JSON `{"message"}` validated by pydantic.
- Post-processing: hashtags stripped, max 2 lines; number guard: any number not from the plan
  (e.g. an invented end time "23:00") → template fallback. Any LLM error → template.
- Known limit: qwen2.5:3b still sometimes adds "Reserve now!" despite the prompt.
### B4: red-team (done)
- `redteam.py` rebuilds exactly what the coordinator sees: 5 public plans (from the real `propose_plans`),
  3 anonymous shuffled profiles (one empty), 3 anonymous shuffled votes. Prints it first.
- It imports neither `Friend` nor `private_agent`: the private data is not even in the process.
- 3 prompt injections (Lea's day, Sam's exact budget, who is tired): qwen2.5:3b answered all three
  "no such information"; even a specific answer would be a hallucination, not a leak.
