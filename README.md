# acorns

A terminal-first tool for tracking which Claude instance is working on which project.

State is stored in `~/.claude-tracker/tracker.db` (SQLite, WAL mode). Concurrent access from the TUI and MCP server is safe.

## Requirements

```
pip install textual typer rich
```

Python 3.10+.

## Install

```bash
bash install.sh
```

The installer:
- Creates a `tracker` command in `~/.local/bin`
- Optionally registers the MCP server in `~/.claude/settings.json`

## Usage

### TUI

```bash
tracker
```

| Key | Action |
|-----|--------|
| `n` | Add new instance |
| `e` / `Enter` | Assign or edit project |
| `d` | Mark current project done |
| `h` | View history |
| `Delete` | Remove instance (with confirmation) |
| `←` / `→` | Navigate cards |
| `r` | Refresh |
| `q` | Quit |

### CLI

```bash
tracker status                          # print table
tracker add "Morpheus"                  # register an instance
tracker assign "Morpheus" "Auth PR"     # assign a project
tracker assign "Morpheus" "Auth PR" --notes "unblock design first"
tracker done "Morpheus"                 # mark done
tracker remove "Morpheus"              # remove entirely
```

### MCP server

Any Claude session with the MCP server configured can call these tools directly:

| Tool | Description |
|------|-------------|
| `tracker_status` | Get current assignments (all instances) |
| `tracker_assign` | Assign a project to a named instance |
| `tracker_done` | Mark current project done |
| `tracker_add` | Register a new instance |

The MCP server communicates over stdio — no network exposure.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `TRACKER_DB` | `~/.claude-tracker/tracker.db` | Override the database path (useful for testing) |

## Data

- Database: `~/.claude-tracker/tracker.db` (`0o600`, directory `0o700`)
- History is capped at 100 entries per instance
- Project names, notes, and timestamps are stored in plaintext — treat the file's OS permissions as your only protection

## Running tests

```bash
pip install pytest
pytest tests/
```

## License

MIT — see [LICENSE](LICENSE).
