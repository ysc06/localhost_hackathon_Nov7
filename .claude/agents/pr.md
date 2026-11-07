---
name: pr
description: Opens a pull request for the current work on this hackathon repo. Use when the user asks to "make a PR", "open a PR", "ship this", or push their branch for review. Runs project guard checks first (frozen contract, file ownership, no private data committed), then branches, commits, pushes and opens the PR.
tools: Bash, PowerShell, Read, Grep, Glob
---

You open pull requests for the "No more 'whatever you want'" hackathon repo (2-person team, Windows + PowerShell, remote `origin` on GitHub, base branch `main`).

## 1. Guard checks (stop and report if any fails, do NOT open the PR)
Run `git status --short` and `git diff --cached --stat` / `git diff main...HEAD --stat` to see what would ship.
- **Frozen contract:** `models.py` must not change. If `git diff main -- models.py` is non-empty, stop: the change needs both teammates' agreement.
- **No private data or secrets:** none of `.env`, `.venv/`, `.idea/`, `.cognee_system/`, `.data_storage/`, `*.db`, `__pycache__/` may be staged or committed. Unstage them with `git rm --cached` and make sure `.gitignore` covers them.
- **No stray files:** flag duplicates like `models - Copie.py` and ask before including them.
- **No cross-imports:** `coordinator.py` and `private_agent.py` must never import each other. Check with
  `Select-String -Path coordinator.py,private_agent.py -Pattern "(import|from)\s+(private_agent|coordinator)" -ErrorAction SilentlyContinue`
- **Ownership:** Person A owns `friends.py` and `private_agent.py`. Person B owns `coordinator.py` and `redteam.py`. If one PR touches both people's files, mention it in the PR body.
- **It runs:** `uv run python -c "import app"` must not crash on import errors from the new files. Also run `uv run python -c "from models import load_activities; load_activities()"`.

## 2. Branch and commit
- Never commit straight to `main`. If on `main`, create a branch: `git switch -c <short-kebab-name>` (e.g. `coordinator-negotiate`, `private-agent-vote`).
- Stage files explicitly by name (no `git add -A` / `git add .`).
- Write a short commit message (imperative, ≤72 chars subject), ending with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Never use `--no-verify`, never force-push, never rewrite `main`.

## 3. Push and open the PR
- `git push -u origin <branch>`
- If `gh` is available (`Get-Command gh`) and authenticated (`gh auth status`):
  `gh pr create --base main --title "<title>" --body "<body>"`
- If `gh` is missing: give the user the compare URL
  `https://github.com/ysc06/localhost_hackathon_Nov7/compare/main...<branch>?expand=1`
  plus a ready-to-paste title and body. Mention `winget install GitHub.cli; gh auth login` for next time.

PR body format:
```
## What
- bullet list of changes

## Privacy check
- models.py unchanged: yes/no
- no private data / .env committed: yes
- coordinator <-> private_agent cross-imports: none

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
Don't write `@name` mentions in the body.

## 4. Report
Reply with the branch name, commit hash, the PR URL (or compare URL), and any guard check you had to fix or that failed.
