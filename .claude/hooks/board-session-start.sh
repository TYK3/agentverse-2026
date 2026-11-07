#!/usr/bin/env bash
# Claude Code SessionStart hook: show unread board posts at the start of a session.
# Anything printed to stdout is added to the session context. Never fails the session.

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
[ -f tools/board ] || exit 0

out="$(bash tools/board unread 2>/dev/null)"
if [ -n "$out" ]; then
  echo "Team board: unread posts from teammates and their agents."
  echo "Act on anything that tags you or @all, and reply with tools/board post."
  echo
  printf '%s\n' "$out"
else
  echo "Team board: no unread posts."
fi
exit 0
