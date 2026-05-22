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

# printf %q shell-quotes the path, preventing injection from special characters.
printf '#!/usr/bin/env bash\nexec python3 %q "$@"\n' "$TRACKER" > "$BIN/tracker"
chmod +x "$BIN/tracker"
echo "✓  tracker command installed → $BIN/tracker"

if [[ ":$PATH:" != *":$BIN:"* ]]; then
  echo "   Add to your shell profile: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ── MCP server (optional) ─────────────────────────────────────────────────────

echo ""
read -rp "Register MCP server with Claude Code? (y/N) " yn
if [[ "${yn,,}" == "y" ]]; then
  SETTINGS="${HOME}/.claude/settings.json"
  mkdir -p "$(dirname "$SETTINGS")"

  # Refuse to follow symlinks — could silently overwrite an unintended target.
  if [[ -L "$SETTINGS" ]]; then
    echo "ERROR: $SETTINGS is a symlink. Refusing to modify to avoid overwriting the target."
    exit 1
  fi

  if [[ ! -f "$SETTINGS" ]]; then
    echo '{}' > "$SETTINGS"
    chmod 600 "$SETTINGS"
  fi

  # Verify the scripts are owned by the current user and not writable by others.
  python3 -c "
import os, sys, stat
for path in sys.argv[1:]:
    try:
        st = os.stat(path)
    except OSError as e:
        print(f'ERROR: cannot stat {path}: {e}', file=sys.stderr)
        sys.exit(1)
    if st.st_uid != os.getuid():
        print(f'ERROR: {path} is not owned by you; aborting MCP registration.', file=sys.stderr)
        sys.exit(1)
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        print(f'ERROR: {path} is group/world-writable; aborting MCP registration.', file=sys.stderr)
        sys.exit(1)
" "$TRACKER" "$MCP_SERVER"

  # Back up before modifying; restrict backup permissions.
  cp "$SETTINGS" "${SETTINGS}.bak"
  chmod 600 "${SETTINGS}.bak"

  # Merge the mcpServers entry using Python (no jq dependency).
  # Uses an atomic write (temp file + os.replace) so a mid-write crash can't corrupt the file.
  python3 - "$SETTINGS" "$MCP_SERVER" << 'PYEOF'
import json, os, sys, tempfile

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
    dir_path = os.path.dirname(os.path.abspath(settings_path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as tf:
            json.dump(cfg, tf, indent=2)
        os.replace(tmp_path, settings_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
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
