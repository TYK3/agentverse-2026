# Rules for every agent on this team

## 1. The board

All agents read and post on the pinned issue titled "Message Board" using `tools/board`. It needs only `gh`, logged in. If the board is not issue #1, set `BOARD_ISSUE`. Run it as `bash tools/board ...`, which works even when the file is not marked executable. New teammates run `bash tools/setup` once.

- Start every post with `[<person>'s <agent>]`, for example `[Anthony's Claude]`.
- Keep posts to one or two lines: what changed, where (PR or commit), what you need, from whom.
- Tag people by GitHub login. Team (fill this in at kickoff):
  - `@TYK3` (team lead)
  - `@login2` (Name)
  - `@login3` (Name)
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
4. Open a PR with `Closes #N`. A human reviews anything shared (APIs, schemas, env vars) before it merges.
5. `git fetch` and rebase before pushing. Never force-push a shared branch. If your pull request has a merge conflict, pull `main` into your branch, fix the conflicting lines, and ask on the board if unsure which version is right.
6. If a merge changes something others depend on, post on the board when it lands.

## 5. Safety

This repo is private, but keep it that way: never put keys, tokens, passwords or private data in a post, a commit or a file.

## 6. Who owns what

Fill this in at kickoff. Do not edit files in someone else's folders; ask on the board.

| Area | Owner (GitHub login) | Folders |
|---|---|---|
| | | |
