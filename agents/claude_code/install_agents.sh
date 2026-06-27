#!/usr/bin/env bash
# Installs the Layer 1 subagents + /analyze command into this project's .claude/
# folder so Claude Code picks them up. Run once from the project root:
#     bash agents/claude_code/install_agents.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/agents/claude_code"

mkdir -p "$ROOT/.claude/agents" "$ROOT/.claude/commands"
cp "$SRC/agents/"*.md     "$ROOT/.claude/agents/"
cp "$SRC/commands/"*.md   "$ROOT/.claude/commands/"

echo "Installed subagents:"
ls -1 "$ROOT/.claude/agents/"
echo "Installed commands:"
ls -1 "$ROOT/.claude/commands/"
echo
echo "Now open Claude Code in $ROOT and run:  /analyze"
