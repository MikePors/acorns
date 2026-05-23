#!/usr/bin/env python3
"""
Instance Tracker
Track which Claude session is assigned to what project.

Usage:
  tracker              launch interactive TUI
  tracker status       print table (pipe-friendly)
  tracker assign NAME PROJECT [--notes TEXT]
  tracker done NAME
  tracker add NAME
  tracker remove NAME
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import tracker_state
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, Static

# ── TUI ────────────────────────────────────────────────────────────────────────

CSS = """
Screen {
    background: $background;
}

#cards-row {
    height: 1fr;
    padding: 1 2;
    overflow-x: auto;
    overflow-y: hidden;
}

InstanceCard {
    width: 30;
    height: 1fr;
    margin: 0 1;
    border: round $panel-darken-2;
    padding: 1 2;
    background: $surface;
}

InstanceCard.active {
    border: round $success-darken-1;
}

InstanceCard.overdue {
    border: round $warning;
}

InstanceCard:focus {
    border: round $accent;
    background: $boost;
}

.add-card {
    width: 16;
    height: 1fr;
    margin: 0 1;
    border: dashed $panel;
    padding: 1 2;
    background: $surface;
    color: $text-disabled;
    content-align: center middle;
    text-align: center;
}

.add-card:focus {
    border: dashed $accent;
    color: $accent;
}

AddModal, EditModal, HistoryModal, ConfirmModal {
    align: center middle;
}

.dialog {
    width: 64;
    background: $surface;
    border: round $primary;
    padding: 2 4;
    height: auto;
}

.dialog-title {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}

.dialog-label {
    color: $text-muted;
    margin-top: 1;
}

.dialog-buttons {
    margin-top: 2;
    align: right middle;
    height: 3;
}

.dialog-buttons Button {
    margin-left: 1;
}

.history-scroll {
    height: 16;
    border: tall $panel-darken-1;
    margin-top: 1;
    background: $surface-darken-1;
    padding: 0 1;
}

.hist-row {
    color: $text-muted;
    padding: 0 1;
}

.hint {
    color: $text-disabled;
    text-style: italic;
    padding: 1 2;
}
"""


def _card_markup(name: str, data: dict) -> str:
    project = data.get("current_project")
    notes = data.get("notes", "")
    assigned_at = data.get("assigned_at")
    parts = [f"[bold]{escape(name)}[/bold]", ""]
    if project:
        parts.append(f"[green]📁 {escape(project)}[/green]")
        if assigned_at:
            a = tracker_state.age(assigned_at)
            try:
                t = datetime.fromisoformat(assigned_at)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                is_overdue = (datetime.now(timezone.utc) - t) > timedelta(hours=8)
                color = "yellow" if is_overdue else "dim"
                parts.append(f"[{color}]⏱  {a}[/{color}]")
            except Exception:
                parts.append(f"[dim]⏱  {a}[/dim]")
        if notes:
            parts += ["", f"[dim italic]{escape(notes)}[/dim italic]"]
    else:
        parts.append("[dim]— idle —[/dim]")
    return "\n".join(parts)


def _card_classes(data: dict) -> list[str]:
    project = data.get("current_project")
    if not project:
        return []
    assigned_at = data.get("assigned_at")
    try:
        t = datetime.fromisoformat(assigned_at)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - t) > timedelta(hours=8):
            return ["overdue"]
    except Exception:
        pass
    return ["active"]


class InstanceCard(Static, can_focus=True):
    def __init__(self, name: str, data: dict, **kwargs):
        super().__init__(_card_markup(name, data), **kwargs)
        self._name = name
        self._data = data
        for cls in _card_classes(data):
            self.add_class(cls)

    @property
    def instance_name(self) -> str:
        return self._name

    @property
    def instance_data(self) -> dict:
        return self._data

    def reload(self, data: dict) -> None:
        self._data = data
        self.remove_class("active", "overdue")
        for cls in _card_classes(data):
            self.add_class(cls)
        self.update(_card_markup(self._name, data))


# ── Modals ─────────────────────────────────────────────────────────────────────

class AddModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("New Instance", classes="dialog-title")
            yield Label("Character name:", classes="dialog-label")
            yield Input(placeholder="e.g. Morpheus", id="name-in")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Add", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#name-in", Input).focus()

    @on(Button.Pressed, "#ok")
    def do_ok(self) -> None:
        val = self.query_one("#name-in", Input).value.strip()
        if val:
            self.dismiss(val)

    @on(Button.Pressed, "#cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def submitted(self) -> None:
        self.do_ok()


class EditModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, name: str, data: dict, **kwargs):
        super().__init__(**kwargs)
        self._name = name
        self._data = data

    def compose(self) -> ComposeResult:
        project = self._data.get("current_project", "")
        notes = self._data.get("notes", "")
        with Vertical(classes="dialog"):
            yield Label(f"Assign: {self._name}", classes="dialog-title")
            yield Label("Project:", classes="dialog-label")
            yield Input(value=project, placeholder="e.g. Auth service refactor", id="proj-in")
            yield Label("Notes (optional):", classes="dialog-label")
            yield Input(value=notes, placeholder="Brief context...", id="notes-in")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Save", variant="primary", id="save")
                if project:
                    yield Button("Mark done ✓", variant="success", id="done")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#proj-in", Input).focus()

    @on(Button.Pressed, "#save")
    def do_save(self) -> None:
        proj = self.query_one("#proj-in", Input).value.strip()
        notes = self.query_one("#notes-in", Input).value.strip()
        self.dismiss({"action": "assign", "project": proj, "notes": notes} if proj else None)

    @on(Button.Pressed, "#done")
    def do_done(self) -> None:
        self.dismiss({"action": "done"})

    @on(Button.Pressed, "#cancel")
    def do_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#proj-in")
    def proj_submitted(self) -> None:
        self.query_one("#notes-in", Input).focus()

    @on(Input.Submitted, "#notes-in")
    def notes_submitted(self) -> None:
        self.do_save()


class HistoryModal(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(self, name: str, history: list, **kwargs):
        super().__init__(**kwargs)
        self._name = name
        self._history = history

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(f"History · {self._name}", classes="dialog-title")
            if not self._history:
                yield Label("No completed projects yet.", classes="hint")
            else:
                with ScrollableContainer(classes="history-scroll"):
                    for entry in reversed(self._history):
                        proj = entry.get("project", "?")
                        a = entry.get("assigned_at")
                        c = entry.get("completed_at")
                        notes = entry.get("notes", "")
                        dur = tracker_state.duration_between(a, c)
                        try:
                            ts = datetime.fromisoformat(a)
                            date_str = ts.strftime("%b %d")
                        except Exception:
                            date_str = "?"
                        line = f"  {date_str}  [bold]{escape(proj)}[/bold]  [dim]({dur})[/dim]"
                        if notes:
                            line += f"\n       [dim italic]{escape(notes)}[/dim italic]"
                        yield Label(line, classes="hist-row", markup=True)
            with Horizontal(classes="dialog-buttons"):
                yield Button("Close", id="close")

    @on(Button.Pressed, "#close")
    def do_close(self) -> None:
        self.dismiss()


class ConfirmModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Confirm", classes="dialog-title")
            yield Label(self._message)
            with Horizontal(classes="dialog-buttons"):
                yield Button("Yes, remove", variant="error", id="yes")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    @on(Button.Pressed, "#yes")
    def do_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def do_cancel(self) -> None:
        self.dismiss(False)


# ── App ────────────────────────────────────────────────────────────────────────

class TrackerApp(App):
    CSS = CSS
    TITLE = "Instance Tracker"
    BINDINGS = [
        Binding("n", "new_instance", "New"),
        Binding("e", "edit", "Assign/Edit"),
        Binding("enter", "edit", "Assign/Edit", show=False),
        Binding("h", "history", "History"),
        Binding("d", "mark_done", "Done"),
        Binding("delete", "remove_instance", "Remove", show=False),
        Binding("r", "reload", "Refresh", show=False),
        Binding("q", "quit", "Quit"),
        Binding("left", "focus_prev", show=False),
        Binding("right", "focus_next", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="cards-row"):
            state = tracker_state.load()
            for name, data in state.get("instances", {}).items():
                yield InstanceCard(name, data)
            yield Static("[ + ]\n\npress n", classes="add-card")
        yield Footer()

    def on_mount(self) -> None:
        self._focus_first()
        self.set_interval(60, self._schedule_rebuild)

    def _focus_first(self) -> None:
        cards = list(self.query(InstanceCard))
        if cards:
            cards[0].focus()
        else:
            self.query_one(".add-card").focus()

    def _focused_card(self) -> InstanceCard | None:
        f = self.focused
        return f if isinstance(f, InstanceCard) else None

    def _schedule_rebuild(self, *, prefer: str | None = None) -> None:
        """Fire-and-forget wrapper: cancels any in-progress rebuild before starting a new one."""
        self.run_worker(self._rebuild(prefer=prefer), exclusive=True, name="rebuild")

    async def _rebuild(self, *, prefer: str | None = None) -> None:
        """Rebuild card row with serialised DOM operations and in-place reload where possible."""
        target = prefer
        if target is None:
            card = self._focused_card()
            if card:
                target = card.instance_name

        state = tracker_state.load()
        new_instances: dict[str, dict] = state.get("instances", {})
        row = self.query_one("#cards-row")

        existing: dict[str, InstanceCard] = {
            c.instance_name: c for c in row.query(InstanceCard)
        }
        cards_to_remove = [c for name, c in existing.items() if name not in new_instances]
        names_to_add = [name for name in new_instances if name not in existing]

        if cards_to_remove or names_to_add:
            async with row.batch():
                if cards_to_remove:
                    await row.remove_children(cards_to_remove)
                if names_to_add:
                    new_widgets = [
                        InstanceCard(name, new_instances[name]) for name in names_to_add
                    ]
                    await row.mount(*new_widgets, before=row.query_one(".add-card"))

        for name, card in existing.items():
            if name in new_instances and card not in cards_to_remove:
                card.reload(new_instances[name])

        def _restore() -> None:
            if target is not None:
                for card in self.query(InstanceCard):
                    if card.instance_name == target:
                        card.focus()
                        return
            self._focus_first()

        self.call_after_refresh(_restore)

    def action_new_instance(self) -> None:
        def cb(name: str | None) -> None:
            if not name:
                return
            try:
                added = tracker_state.add(name)
            except ValueError as e:
                self.notify(str(e), severity="error")
                return
            if not added:
                self.notify(f"'{name}' already exists", severity="warning")
                return
            self._schedule_rebuild(prefer=name)
            self.notify(f"Added: {name}")

        self.push_screen(AddModal(), cb)

    def action_edit(self) -> None:
        card = self._focused_card()
        if card is None:
            self.notify("Select an instance card first", severity="warning")
            return
        state = tracker_state.load()
        data = state["instances"].get(card.instance_name, {})
        name = card.instance_name

        def cb(result: dict | None) -> None:
            if result is None:
                return
            try:
                if result["action"] == "assign":
                    tracker_state.assign(name, result["project"], result["notes"])
                    self.notify(f"{name} → {result['project']}")
                elif result["action"] == "done":
                    if tracker_state.done(name):
                        self.notify(f"{name} ✓ done")
            except ValueError as e:
                self.notify(str(e), severity="error")
            self._schedule_rebuild(prefer=name)

        self.push_screen(EditModal(name, data), cb)

    def action_mark_done(self) -> None:
        card = self._focused_card()
        if card is None:
            return
        if not card.instance_data.get("current_project"):
            self.notify("No active project", severity="warning")
            return
        name = card.instance_name
        if not tracker_state.done(name):
            self.notify("No active project", severity="warning")
            return
        self._schedule_rebuild(prefer=name)
        self.notify(f"{name} ✓ done")

    def action_history(self) -> None:
        card = self._focused_card()
        if card is None:
            self.notify("Select an instance card first", severity="warning")
            return
        state = tracker_state.load()
        history = state["instances"].get(card.instance_name, {}).get("history", [])
        self.push_screen(HistoryModal(card.instance_name, history))

    def action_remove_instance(self) -> None:
        card = self._focused_card()
        if card is None:
            return
        name = card.instance_name

        def cb(confirmed: bool | None) -> None:
            if not confirmed:
                return
            tracker_state.remove(name)
            self._schedule_rebuild()
            self.notify(f"Removed: {name}", severity="warning")

        self.push_screen(ConfirmModal(f"Remove '{name}' and all history?"), cb)

    def action_reload(self) -> None:
        self._schedule_rebuild()

    def action_focus_prev(self) -> None:
        self.focus_previous()

    def action_focus_next(self) -> None:
        self.focus_next()


# ── CLI ────────────────────────────────────────────────────────────────────────

cli = typer.Typer(no_args_is_help=False, add_completion=False)
console = Console()


@cli.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Instance Tracker — launch TUI or use subcommands."""
    if ctx.invoked_subcommand is None:
        TrackerApp().run()


@cli.command("status")
def cmd_status() -> None:
    """Print current assignments as a table."""
    state = tracker_state.load()
    instances = state.get("instances", {})
    if not instances:
        console.print("[dim]No instances yet.  Run: tracker add 'Darth Vader'[/]")
        return
    table = Table(border_style="dim", show_header=True, header_style="bold")
    table.add_column("Instance", style="bold")
    table.add_column("Project")
    table.add_column("Since")
    table.add_column("Notes", style="dim")
    for name, data in instances.items():
        project = data.get("current_project")
        assigned_at = data.get("assigned_at")
        notes = data.get("notes", "")
        if project:
            table.add_row(name, f"[green]{escape(project)}[/]", tracker_state.age(assigned_at), notes)
        else:
            table.add_row(name, "[dim]idle[/]", "", "")
    console.print(table)


@cli.command("add")
def cmd_add(name: str = typer.Argument(..., help="Instance or character name")) -> None:
    """Add a new instance."""
    try:
        added = tracker_state.add(name)
    except ValueError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    if not added:
        console.print(f"[yellow]'{name}' already exists[/]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/] Added: {name}")


@cli.command("assign")
def cmd_assign(
    name: str = typer.Argument(..., help="Instance name"),
    project: str = typer.Argument(..., help="Project name"),
    notes: str = typer.Option("", "--notes", "-n", help="Optional context"),
) -> None:
    """Assign a project to an instance."""
    try:
        created = tracker_state.assign(name, project, notes)
    except ValueError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    if created:
        console.print(f"[dim]Note: created new instance '{name}'[/]")
    console.print(f"[green]✓[/] {name} → {project}")


@cli.command("done")
def cmd_done(name: str = typer.Argument(..., help="Instance name")) -> None:
    """Mark an instance's current project as done."""
    if not tracker_state.done(name):
        console.print(f"[yellow]'{name}' has no active project[/]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/] {name} marked done")


@cli.command("remove")
def cmd_remove(name: str = typer.Argument(..., help="Instance name")) -> None:
    """Remove an instance entirely."""
    if not tracker_state.remove(name):
        console.print(f"[yellow]'{name}' not found[/]")
        raise typer.Exit(1)
    console.print(f"[dim]Removed: {name}[/]")


if __name__ == "__main__":
    cli()
