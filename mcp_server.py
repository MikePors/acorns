#!/usr/bin/env python3
"""
Instance Tracker MCP Server

Add this to your Claude Code MCP config so any session can read/update
its own entry in the tracker without leaving the terminal.

Config snippet (~/.claude/settings.json):
  "mcpServers": {
    "tracker": {
      "command": "python3",
      "args": ["/path/to/mcp_server.py"]
    }
  }

Tools exposed:
  tracker_status          — get current assignments (all instances)
  tracker_assign          — assign a project to a named instance
  tracker_done            — mark current project done for an instance
  tracker_add             — register a new instance by name
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tracker_state

# ── MCP JSON-RPC transport ─────────────────────────────────────────────────────

def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _respond(req_id, result) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "tracker_status",
        "description": (
            "Get the current assignment status for all tracked Claude instances. "
            "Returns a plain-text table suitable for reading in a conversation."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "tracker_assign",
        "description": (
            "Add a project to a named Claude instance. "
            "Creates the instance if it doesn't exist yet. "
            "Multiple projects can be active simultaneously."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance": {
                    "type": "string",
                    "description": "The instance name / character label (e.g. 'Morpheus')",
                    "maxLength": tracker_state.MAX_NAME_LEN,
                },
                "project": {
                    "type": "string",
                    "description": "Short project or task name",
                    "maxLength": tracker_state.MAX_PROJECT_LEN,
                },
                "notes": {
                    "type": "string",
                    "description": "Optional brief context (one line)",
                    "maxLength": tracker_state.MAX_NOTES_LEN,
                },
            },
            "required": ["instance", "project"],
        },
    },
    {
        "name": "tracker_done",
        "description": (
            "Mark an active project as done for a Claude instance. "
            "The completed entry moves to history. "
            "If the instance has multiple active projects, 'project' is required to identify which one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance": {
                    "type": "string",
                    "description": "The instance name / character label",
                    "maxLength": tracker_state.MAX_NAME_LEN,
                },
                "project": {
                    "type": "string",
                    "description": "Project name to mark done. Required when the instance has multiple active projects.",
                    "maxLength": tracker_state.MAX_PROJECT_LEN,
                },
            },
            "required": ["instance"],
        },
    },
    {
        "name": "tracker_add",
        "description": "Register a new instance by name so it appears in the tracker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance": {
                    "type": "string",
                    "description": "Instance name or character label",
                    "maxLength": tracker_state.MAX_NAME_LEN,
                },
            },
            "required": ["instance"],
        },
    },
]


# ── Tool handlers ──────────────────────────────────────────────────────────────

def _validate_lengths(**fields: str) -> None:
    limits = {
        "instance": tracker_state.MAX_NAME_LEN,
        "project": tracker_state.MAX_PROJECT_LEN,
        "notes": tracker_state.MAX_NOTES_LEN,
    }
    for field, value in fields.items():
        limit = limits.get(field, 1024)
        if len(value) > limit:
            raise ValueError(f"'{field}' exceeds maximum length of {limit}")


def handle_status(_args: dict) -> str:
    state = tracker_state.load()
    instances = state.get("instances", {})
    if not instances:
        return "No instances tracked yet."
    lines = ["Instance Tracker — current assignments\n"]
    lines.append(f"{'INSTANCE':<20} {'PROJECT':<30} {'SINCE':<8} NOTES")
    lines.append("-" * 72)
    for name, data in instances.items():
        active = data.get("active", [])
        if not active:
            lines.append(f"{name:<20} {'idle':<30} {'':<8}")
        else:
            for i, entry in enumerate(active):
                row_name = name if i == 0 else ""
                since = tracker_state.age(entry.get("assigned_at"))
                notes = entry.get("notes", "")
                lines.append(f"{row_name:<20} {entry['project']:<30} {since:<8} {notes}")
    return "\n".join(lines)


def handle_assign(args: dict) -> str:
    name = args.get("instance", "").strip()
    project = args.get("project", "").strip()
    notes = args.get("notes", "").strip()
    if not name or not project:
        raise ValueError("instance and project are required.")
    _validate_lengths(instance=name, project=project, notes=notes)
    tracker_state.assign(name, project, notes)
    return f"✓ {name} → {project}"


def handle_done(args: dict) -> str:
    name = args.get("instance", "").strip()
    project = args.get("project", "").strip()
    if not name:
        raise ValueError("instance name required.")
    _validate_lengths(instance=name, project=project)
    state = tracker_state.load()
    active = state.get("instances", {}).get(name, {}).get("active", [])
    if not active:
        raise ValueError(f"'{name}' has no active project.")
    if project:
        matches = [e for e in active if e["project"] == project]
        if not matches:
            raise ValueError(f"No active project named '{project}' for '{name}'.")
        if len(matches) > 1:
            raise ValueError(
                f"'{name}' has {len(matches)} active projects both named '{project}'. "
                "This is ambiguous — mark one done from the TUI instead."
            )
        project_id = matches[0]["id"]
    elif len(active) == 1:
        project_id = active[0]["id"]
    else:
        names = ", ".join(f"'{e['project']}'" for e in active)
        raise ValueError(f"'{name}' has multiple active projects: {names}. Specify 'project'.")
    completed_name = next(e["project"] for e in active if e["id"] == project_id)
    if not tracker_state.done(name, project_id):
        raise ValueError(f"Project '{completed_name}' for '{name}' was already completed.")
    return f"✓ {name} → {completed_name} marked done"


def handle_add(args: dict) -> str:
    name = args.get("instance", "").strip()
    if not name:
        raise ValueError("instance name required.")
    _validate_lengths(instance=name)
    if not tracker_state.add(name):
        raise ValueError(f"'{name}' already exists.")
    return f"✓ Added: {name}"


HANDLERS = {
    "tracker_status": handle_status,
    "tracker_assign": handle_assign,
    "tracker_done": handle_done,
    "tracker_add": handle_add,
}


# ── Main loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            _error(None, -32700, "Parse error")
            continue

        method = msg.get("method", "")
        req_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            _respond(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "tracker", "version": "1.0.0"},
            })

        elif method == "initialized":
            pass  # notification, no response

        elif method == "tools/list":
            _respond(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            handler = HANDLERS.get(tool_name)
            if handler is None:
                _error(req_id, -32601, f"Unknown tool: {tool_name}")
                continue
            try:
                result_text = handler(tool_args)
                _respond(req_id, {
                    "content": [{"type": "text", "text": result_text}],
                    "isError": False,
                })
            except Exception as e:
                _respond(req_id, {
                    "content": [{"type": "text", "text": str(e)}],
                    "isError": True,
                })

        elif method == "ping":
            _respond(req_id, {})

        elif req_id is not None:
            _error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
