#!/usr/bin/env bash
# Install tracker CLI and optionally register the MCP server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACKER="$SCRIPT_DIR/tracker.py"
MCP_SERVER="$SCRIPT_DIR/mcp_server.py"

# ── CLI symlink ───────────────────────────────────────────────────────────────

BIN="${HOME}/.local/bin"
mkdir -p "$BIN"

cat > "$BIN/tracker" << EOF
#!/usr/bin/env bash
exec python3 "$TRACKER" "\$@"
EOF
chmod +x "$BIN/tracker"
echo "✓  tracker command installed → $BIN/tracker"

if ! echo "$PATH" | grep -q "$BIN"; then
  echo "   Add to your shell profile: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ── MCP server (optional) ─────────────────────────────────────────────────────

echo ""
read -rp "Register MCP server with Claude Code? (y/N) " yn
if [[ "${yn,,}" == "y" ]]; then
  SETTINGS="${HOME}/.claude/settings.json"
  mkdir -p "$(dirname "$SETTINGS")"

  if [[ ! -f "$SETTINGS" ]]; then
    echo '{}' > "$SETTINGS"
  fi

  # Merge the mcpServers entry using Python (no jq dependency)
  python3 - "$SETTINGS" "$MCP_SERVER" << 'PYEOF'
import json, sys

settings_path = sys.argv[1]
mcp_path = sys.argv[2]

with open(settings_path) as f:
    cfg = json.load(f)

cfg.setdefault("mcpServers", {})["tracker"] = {
    "command": "python3",
    "args": [mcp_path]
}

with open(settings_path, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF

  echo "✓  MCP server registered in $SETTINGS"
  echo "   In any Claude session you can now call:"
  echo "     tracker_status    — see all assignments"
  echo "     tracker_assign    — update your own entry"
  echo "     tracker_done      — mark yourself idle"
fi

echo ""
echo "Done.  Run: tracker"
