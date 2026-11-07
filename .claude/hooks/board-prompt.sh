#!/usr/bin/env bash
# Claude Code UserPromptSubmit hook: before each prompt, surface any new board posts.
# Prints nothing when there is nothing new, so it costs no tokens on a quiet board.

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
[ -f tools/board ] || exit 0

out="$(bash tools/board unread 2>/dev/null)"
if [ -n "$out" ]; then
  echo "New team board posts:"
  echo
  printf '%s\n' "$out"
fi
exit 0
