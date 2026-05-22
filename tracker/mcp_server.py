#!/usr/bin/env python3
"""
Instance Tracker MCP Server

Add this to your Claude Code MCP config so any session can read/update
its own entry in the tracker without leaving the terminal.

Config snippet (~/.claude/settings.json):
  "mcpServers": {
    "tracker": {
      "command": "python3",
      "args": ["/path/to/tracker/mcp_server.py"]
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
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Re-use the same data layer as the TUI app
sys.path.insert(0, str(Path(__file__).parent))
from tracker import _age, _assign, _done, _now, load, save

# ── MCP JSON-RPC transport ─────────────────────────────────────────────────────

def _send(obj: dict) -> None:
    line = json.dumps(obj)
    sys.stdout.write(line + "\n")
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
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "tracker_assign",
        "description": (
            "Assign a project to a named Claude instance. "
            "Creates the instance if it doesn't exist yet. "
            "Moves any existing project to history automatically."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance": {
                    "type": "string",
                    "description": "The instance name / character label (e.g. 'Morpheus')",
                },
                "project": {
                    "type": "string",
                    "description": "Short project or task name",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional brief context (one line)",
                },
            },
            "required": ["instance", "project"],
        },
    },
    {
        "name": "tracker_done",
        "description": (
            "Mark a Claude instance's current project as done and return it to idle. "
            "The completed entry moves to that instance's history."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance": {
                    "type": "string",
                    "description": "The instance name / character label",
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
                },
            },
            "required": ["instance"],
        },
    },
]


# ── Tool handlers ──────────────────────────────────────────────────────────────

def handle_status(_args: dict) -> str:
    state = load()
    instances = state.get("instances", {})
    if not instances:
        return "No instances tracked yet."
    lines = ["Instance Tracker — current assignments\n"]
    lines.append(f"{'INSTANCE':<20} {'PROJECT':<30} {'SINCE':<8} NOTES")
    lines.append("-" * 72)
    for name, data in instances.items():
        project = data.get("current_project") or "idle"
        since = _age(data.get("assigned_at")) if data.get("current_project") else ""
        notes = data.get("notes", "")
        lines.append(f"{name:<20} {project:<30} {since:<8} {notes}")
    return "\n".join(lines)


def handle_assign(args: dict) -> str:
    name = args.get("instance", "").strip()
    project = args.get("project", "").strip()
    notes = args.get("notes", "").strip()
    if not name or not project:
        return "Error: instance and project are required."
    state = load()
    if name not in state["instances"]:
        state["instances"][name] = {"history": []}
    _assign(state, name, project, notes)
    save(state)
    return f"✓ {name} → {project}"


def handle_done(args: dict) -> str:
    name = args.get("instance", "").strip()
    if not name:
        return "Error: instance name required."
    state = load()
    if _done(state, name):
        save(state)
        return f"✓ {name} marked done"
    return f"'{name}' has no active project."


def handle_add(args: dict) -> str:
    name = args.get("instance", "").strip()
    if not name:
        return "Error: instance name required."
    state = load()
    if name in state["instances"]:
        return f"'{name}' already exists."
    state["instances"][name] = {
        "current_project": None, "notes": "", "assigned_at": None, "history": [],
    }
    save(state)
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
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True,
                })

        elif method == "ping":
            _respond(req_id, {})

        elif req_id is not None:
            _error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
