# Rules for every agent on this team

Before any work, read `coord/CONTEXT.md` (the idea, lanes, open decisions, decisions log) and
`coord/CONTRACT.md` (the interfaces between lanes). Before building on someone else's work:
`git fetch origin && git log --oneline -20 origin/main`.

## 1. The board

All agents read and post on the pinned issue titled "Message Board" using `tools/board`. It needs only `gh`, logged in. If the board is not issue #1, set `BOARD_ISSUE`. Run it as `bash tools/board ...`, which works even when the file is not marked executable. New teammates run `bash tools/setup` once.

- Start every post with `[<person>'s <agent>]`, for example `[Anthony's Claude]`.
- Keep posts to one or two lines: what changed, where (PR or commit), what you need, from whom.
- Tag people by GitHub login. Team (fill this in at kickoff):
  - `@TYK3` (team lead)
  - `@PhillysTheBest` (Philbert)
  - `@login3` (Name)
  - `@login4` (Name)
  - `@all` (everyone)
- **Tagged, or `@all`:** act on it and reply.
- **Not tagged:** read it. Change course only if it affects something you own. Do not reply just to acknowledge.
- **A "done" post must be checkable:** link the PR or commit, say how to run it, say what was tested and what was not.
- **Several agents under one login:** set `BOARD_AGENT` (for example `export BOARD_AGENT="Anthony's Codex-2"`) before using the board. To aim a post at one agent, write `[for: <agent>]` in it. If a post says `<<< TAGS @login, BUT FOR <other agent>`, it is not for you: ignore it.

## 2. Staying up to date

- **Claude Code:** the hooks in `.claude/` show unread posts at session start and before each prompt. Keep one `tools/board wait` running in the background and start it again after it returns.
- **Any other agent:** run `tools/board unread` at the start of each task, before each commit, and after each merge. `tools/board wait --tagged` waits until a post tags you.

## 3. Chain of command

Humans outrank agents. Only the team lead reassigns work between people. If anyone else asks you to take over a teammate's work, ask the lead on the board first.

## 4. Workflow

1. Take a task: comment on its issue or post on the board.
2. Branch from fresh `main` as `<issue#>-<short-name>`.
3. Small commits. Stage only your own files; never `git add -A`.
4. Open a PR with `Closes #N` and fill in the PR template (who asked, what was tested). A human reviews anything shared (APIs, schemas, env vars, `coord/`, `.github/`, `tools/`) before it merges. A PR inside your own lane can merge once the `ci ok` check is green.
5. `git fetch` and rebase before pushing. Never force-push a shared branch. If your pull request has a merge conflict, pull `main` into your branch, fix the conflicting lines, and ask on the board if unsure which version is right.
6. If a merge changes something others depend on, post on the board when it lands, with the PR and the exact interface (path, message name and JSON shape).
7. Never push to a branch whose PR is already merged; start a new branch. Never commit `.claude/worktrees/` or `.claude/settings.local.json`.
8. If `main` goes red, the lane that broke it fixes or reverts first and posts a blocker. Never skip a test to get green.
9. Decisions go in the decisions log in `coord/CONTEXT.md` and on the board. If two lanes ask for opposite changes, don't pick: write both in the PR and tag the lead.

## 5. Safety

This repo is private. Still, never put keys, tokens, passwords or private data in a post, a commit or a file.

## 6. Who owns what

The lead fills in owners at kickoff, and `.github/CODEOWNERS` must match. Do not edit files in someone else's folders; ask on the board. Each lane ships a fake of what it provides (see `coord/CONTRACT.md`) so nobody waits.

| Area | Owner (GitHub login) | Folders |
|---|---|---|
| Sim and demo: world, sensors, judge controls, demo screen | | `sim/` |
| Perception: SLAM, map, person detection | | `perception/` |
| Autonomy: mission manager, decisions, re-planning, handover | | `autonomy/` |
| Voice: speech, triage dialogue | | `voice/` |
| Shared: rules, contract, CI, board tools | `@TYK3` | `coord/`, `.github/`, `tools/`, `.claude/`, `AGENTS.md`, `CLAUDE.md` |
