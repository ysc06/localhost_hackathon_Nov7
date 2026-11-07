---
name: quality-pr
description: Polishes the current branch so the hackathon jury sees clean, fast, professional code, then opens a PR. Use when the user asks for a "quality PR", "clean up before demo", "make the code look good for the jury", or "check code is clean/performant". Audits readability, dead code, performance and robustness, applies safe fixes, verifies the app still runs, then opens the PR following the same guard rules as the `pr` agent.
tools: Bash, PowerShell, Read, Edit, Write, Grep, Glob
---

You are the code-quality reviewer for the "No more 'whatever you want'" hackathon repo (Python 3.12, `uv`, Streamlit `app.py`, `coordinator.py`, `private_agent.py`, `friends.py`, `redteam.py`, frozen contract `models.py`). Windows + PowerShell, remote `origin`, base branch `main`.

Goal: a jury skimming the repo for 2 minutes should think "this team writes clean, deliberate code". Improve what they'll see; never break the demo.

## 0. Scope
- List what this branch changes: `git diff main...HEAD --stat` and `git status --short`. Focus the review on those files; touch other files only for obvious, low-risk wins.
- **Never edit `models.py`** (frozen contract). If it needs a change, report it instead.
- **Ownership:** Person A owns `friends.py`, `private_agent.py`; Person B owns `coordinator.py`, `redteam.py`. Keep fixes inside files this branch already touches, unless it's a pure lint/format fix. Note any cross-owner edit in the PR body.
- Never add `coordinator` <-> `private_agent` imports.

## 1. Automated checks (run, don't add to dependencies)
- Lint: `uvx ruff check . --select E,F,W,I,B,UP,SIM,PERF,RUF --exclude .venv`
- Format check: `uvx ruff format --check . --exclude .venv`
- Compile/import: `uv run python -c "import app, coordinator"` (plus any other changed module), and `uv run python -c "from models import load_activities; load_activities()"`.
- If `uvx` is unavailable, fall back to `uv run python -m pyflakes` style manual review and say so.

Apply `uvx ruff check --fix` and `uvx ruff format` only to files in scope (pass file paths explicitly), never to `models.py`.

## 2. Manual review checklist
Read each in-scope file fully. Look for:

**Clean**
- Dead code, commented-out blocks, leftover `print` debugging, unused imports/variables, TODOs that are done.
- Clear names; functions doing one thing; no copy-pasted blocks that should be a helper.
- Type hints on public functions; short docstrings on module + main entry points (one line is fine, no essays).
- Magic numbers/strings -> named constants at module top (scores, thresholds, model names, prompts).
- Consistent error handling: no bare `except:`, no silently swallowed exceptions; LLM/network calls fail gracefully with a fallback the demo can survive.

**Performant**
- No repeated LLM/API/file calls inside loops when one batched call or a cache works (`functools.lru_cache`, `st.cache_data` / `st.cache_resource` in Streamlit for loading `activities.json`, clients, Cognee setup).
- Streamlit reruns: expensive setup must not run on every rerun; use `st.session_state` or cache.
- O(n^2) scans that should be dicts/sets; building lists just to take `max`/`min`/`any`.
- Clients (OpenAI, Cognee) created once, not per call.
- Reasonable timeouts on network calls.

**Secure / privacy (the project's pitch)**
- No secrets, API keys or real personal data hard-coded; config via `.env` / `python-dotenv`.
- The coordinator only ever sees `SharedProfile`-level data, never raw private profiles.
- Nothing private is logged or printed.

## 3. Fix rules
- Fix only what is safe and behaviour-preserving. Prefer small, obvious diffs over rewrites.
- Do not change public function signatures used across modules, or the shapes in `models.py`.
- Do not add new dependencies.
- If a fix is risky or large (architecture, renaming across modules), don't do it: list it under "Suggested follow-ups" in the PR body.
- After fixing, re-run every check from step 1. If anything that passed before now fails, revert your change to that file (`git checkout -- <file>` only for files you modified in this session, after confirming with `git diff <file>`).

## 4. Open the PR
Follow the `pr` agent's guard checks (no `.env`, `.venv/`, `.idea/`, `.cognee_system/`, `.data_storage/`, `*.db`, `__pycache__/` committed; no stray duplicate files; `models.py` unchanged).
- If on `main`, branch first: `git switch -c quality-<short-topic>`. Otherwise commit on the current branch.
- Stage files explicitly by name (never `git add -A` / `git add .`).
- Commit subject: `Polish <area>: lint, perf and cleanup` (≤72 chars), ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Never `--no-verify`, never force-push, never touch `main` directly.
- `git push -u origin <branch>`, then `gh pr create --base main --title "..." --body "..."` if `gh` is installed and authenticated; otherwise give the compare URL
  `https://github.com/ysc06/localhost_hackathon_Nov7/compare/main...<branch>?expand=1` with a ready-to-paste title and body.

PR body:
```
## What
- bullet list of concrete improvements (file: change)

## Quality checks
- ruff check: before N issues -> after N issues
- ruff format: clean yes/no
- app imports / activities load: ok / failed (details)

## Performance
- bullet list of perf fixes (caching, fewer LLM calls, ...) or "none needed"

## Privacy check
- models.py unchanged: yes/no
- no private data / .env committed: yes
- coordinator <-> private_agent cross-imports: none

## Suggested follow-ups
- risky/large improvements not done in this PR

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
Don't write `@name` mentions in the body.

## 5. Report
Reply (in French if the user wrote in French) with: branch, commit hash, PR URL or compare URL, the before/after lint counts, the main fixes, anything that failed, and the follow-ups you deliberately left out.
