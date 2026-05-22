#!/usr/bin/env bash
# Install tracker CLI and optionally register the MCP server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACKER="$SCRIPT_DIR/tracker.py"
MCP_SERVER="$SCRIPT_DIR/mcp_server.py"

# ── Preflight ─────────────────────────────────────────────────────────────────

if ! python3 -c "import textual, typer" 2>/dev/null; then
  echo "ERROR: required Python packages missing."
  echo "       Run: pip install textual typer rich"
  exit 1
fi

# ── CLI wrapper ───────────────────────────────────────────────────────────────

BIN="${HOME}/.local/bin"
mkdir -p "$BIN"

# Use printf %q to safely quote the path against spaces/special characters
printf '#!/usr/bin/env bash\nexec python3 %q "$@"\n' "$TRACKER" > "$BIN/tracker"
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

  # Back up before modifying
  cp "$SETTINGS" "${SETTINGS}.bak"

  # Merge the mcpServers entry using Python (no jq dependency)
  python3 - "$SETTINGS" "$MCP_SERVER" << 'PYEOF'
import json, sys

settings_path = sys.argv[1]
mcp_path = sys.argv[2]

try:
    with open(settings_path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("settings.json root is not a JSON object")
except Exception as e:
    print(f"ERROR: could not read {settings_path}: {e}", file=sys.stderr)
    sys.exit(1)

cfg.setdefault("mcpServers", {})["tracker"] = {
    "command": "python3",
    "args": [mcp_path]
}

try:
    with open(settings_path, "w") as f:
        json.dump(cfg, f, indent=2)
except Exception as e:
    print(f"ERROR: could not write {settings_path}: {e}", file=sys.stderr)
    print(f"       Backup is at {settings_path}.bak", file=sys.stderr)
    sys.exit(1)
PYEOF

  echo "✓  MCP server registered in $SETTINGS"
  echo "   (backup saved to ${SETTINGS}.bak)"
  echo "   In any Claude session you can now call:"
  echo "     tracker_status    — see all assignments"
  echo "     tracker_assign    — update your own entry"
  echo "     tracker_done      — mark yourself idle"
fi

echo ""
echo "Done.  Run: tracker"
