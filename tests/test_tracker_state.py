"""Tests for tracker_state.py — storage layer."""
from __future__ import annotations

import pytest
import tracker_state


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Point DB_PATH at a throwaway file for each test."""
    monkeypatch.setattr(tracker_state, "DB_PATH", tmp_path / "test.db")


# ── add ────────────────────────────────────────────────────────────────────────

class TestAdd:
    def test_returns_true_for_new_instance(self):
        assert tracker_state.add("Alice") is True

    def test_returns_false_for_duplicate(self):
        tracker_state.add("Alice")
        assert tracker_state.add("Alice") is False

    def test_instance_appears_in_load(self):
        tracker_state.add("Alice")
        state = tracker_state.load()
        assert "Alice" in state["instances"]

    def test_new_instance_is_idle(self):
        tracker_state.add("Alice")
        inst = tracker_state.load()["instances"]["Alice"]
        assert inst["active"] == []
        assert inst["history"] == []

    def test_name_too_long_raises(self):
        with pytest.raises(ValueError, match="name"):
            tracker_state.add("x" * (tracker_state.MAX_NAME_LEN + 1))


# ── exists ─────────────────────────────────────────────────────────────────────

class TestExists:
    def test_true_after_add(self):
        tracker_state.add("Bob")
        assert tracker_state.exists("Bob") is True

    def test_false_for_unknown(self):
        assert tracker_state.exists("Nobody") is False

    def test_false_after_remove(self):
        tracker_state.add("Bob")
        tracker_state.remove("Bob")
        assert tracker_state.exists("Bob") is False


# ── remove ─────────────────────────────────────────────────────────────────────

class TestRemove:
    def test_returns_true_for_existing(self):
        tracker_state.add("Carol")
        assert tracker_state.remove("Carol") is True

    def test_returns_false_for_missing(self):
        assert tracker_state.remove("Ghost") is False

    def test_instance_gone_from_load(self):
        tracker_state.add("Carol")
        tracker_state.remove("Carol")
        assert "Carol" not in tracker_state.load()["instances"]

    def test_history_purged_on_remove(self):
        tracker_state.add("Dave")
        tracker_state.assign("Dave", "Project A")
        pid = tracker_state.load()["instances"]["Dave"]["active"][0]["id"]
        tracker_state.done("Dave", pid)
        tracker_state.remove("Dave")
        # Re-add to confirm no orphan history rows survive.
        tracker_state.add("Dave")
        assert tracker_state.load()["instances"]["Dave"]["history"] == []


# ── assign ─────────────────────────────────────────────────────────────────────

class TestAssign:
    def test_creates_new_instance_returns_true(self):
        created = tracker_state.assign("Eve", "Project X")
        assert created is True
        assert tracker_state.exists("Eve")

    def test_update_existing_returns_false(self):
        tracker_state.add("Frank")
        assert tracker_state.assign("Frank", "Project Y") is False

    def test_adds_to_active(self):
        tracker_state.add("Grace")
        tracker_state.assign("Grace", "Project A", "some notes")
        inst = tracker_state.load()["instances"]["Grace"]
        assert len(inst["active"]) == 1
        assert inst["active"][0]["project"] == "Project A"
        assert inst["active"][0]["notes"] == "some notes"
        assert inst["active"][0]["assigned_at"] is not None

    def test_multiple_projects_stack(self):
        tracker_state.add("Hank")
        tracker_state.assign("Hank", "Project A")
        tracker_state.assign("Hank", "Project B")
        inst = tracker_state.load()["instances"]["Hank"]
        projects = [e["project"] for e in inst["active"]]
        assert "Project A" in projects
        assert "Project B" in projects
        assert inst["history"] == []

    def test_name_too_long_raises(self):
        with pytest.raises(ValueError, match="name"):
            tracker_state.assign("x" * (tracker_state.MAX_NAME_LEN + 1), "P")

    def test_project_too_long_raises(self):
        tracker_state.add("Iris")
        with pytest.raises(ValueError, match="project"):
            tracker_state.assign("Iris", "p" * (tracker_state.MAX_PROJECT_LEN + 1))

    def test_notes_too_long_raises(self):
        tracker_state.add("Jake")
        with pytest.raises(ValueError, match="notes"):
            tracker_state.assign("Jake", "Project Z", "n" * (tracker_state.MAX_NOTES_LEN + 1))


# ── done ───────────────────────────────────────────────────────────────────────

class TestDone:
    def test_returns_true_when_active(self):
        tracker_state.add("Kate")
        tracker_state.assign("Kate", "Project A")
        pid = tracker_state.load()["instances"]["Kate"]["active"][0]["id"]
        assert tracker_state.done("Kate", pid) is True

    def test_returns_true_without_project_id(self):
        tracker_state.add("Kate2")
        tracker_state.assign("Kate2", "Project A")
        assert tracker_state.done("Kate2") is True

    def test_returns_false_when_idle(self):
        tracker_state.add("Liam")
        assert tracker_state.done("Liam") is False

    def test_returns_false_for_missing_instance(self):
        assert tracker_state.done("Nobody") is False

    def test_removes_from_active(self):
        tracker_state.add("Mia")
        tracker_state.assign("Mia", "Project A")
        pid = tracker_state.load()["instances"]["Mia"]["active"][0]["id"]
        tracker_state.done("Mia", pid)
        inst = tracker_state.load()["instances"]["Mia"]
        assert inst["active"] == []

    def test_only_removes_specified_project(self):
        tracker_state.add("Mia2")
        tracker_state.assign("Mia2", "Project A")
        tracker_state.assign("Mia2", "Project B")
        active = tracker_state.load()["instances"]["Mia2"]["active"]
        pid_a = next(e["id"] for e in active if e["project"] == "Project A")
        tracker_state.done("Mia2", pid_a)
        inst = tracker_state.load()["instances"]["Mia2"]
        assert len(inst["active"]) == 1
        assert inst["active"][0]["project"] == "Project B"

    def test_completed_project_in_history(self):
        tracker_state.add("Noah")
        tracker_state.assign("Noah", "Project A", "notes here")
        pid = tracker_state.load()["instances"]["Noah"]["active"][0]["id"]
        tracker_state.done("Noah", pid)
        history = tracker_state.load()["instances"]["Noah"]["history"]
        assert len(history) == 1
        assert history[0]["project"] == "Project A"
        assert history[0]["notes"] == "notes here"
        assert history[0]["completed_at"] is not None

    def test_returns_false_for_wrong_project_id(self):
        tracker_state.add("Pat")
        tracker_state.assign("Pat", "Project A")
        assert tracker_state.done("Pat", project_id=99999) is False


# ── history cap ────────────────────────────────────────────────────────────────

class TestHistoryCap:
    def test_history_capped_at_limit(self, monkeypatch):
        monkeypatch.setattr(tracker_state, "HISTORY_LIMIT", 3)
        tracker_state.add("Oscar")
        for i in range(5):
            tracker_state.assign("Oscar", f"Project {i}")
        # Mark all 5 done (oldest first via no project_id)
        for _ in range(5):
            tracker_state.done("Oscar")
        history = tracker_state.load()["instances"]["Oscar"]["history"]
        assert len(history) == 3

    def test_most_recent_entries_kept(self, monkeypatch):
        monkeypatch.setattr(tracker_state, "HISTORY_LIMIT", 2)
        tracker_state.add("Pam")
        for i in range(4):
            tracker_state.assign("Pam", f"Project {i}")
        for _ in range(4):
            tracker_state.done("Pam")
        # cap=2 keeps only the 2 most recent
        history = tracker_state.load()["instances"]["Pam"]["history"]
        projects = [h["project"] for h in history]
        assert "Project 0" not in projects
        assert len(projects) == 2


# ── load ───────────────────────────────────────────────────────────────────────

class TestLoad:
    def test_empty_db(self):
        assert tracker_state.load() == {"instances": {}}

    def test_returns_all_instances(self):
        tracker_state.add("Quinn")
        tracker_state.add("Rose")
        instances = tracker_state.load()["instances"]
        assert "Quinn" in instances
        assert "Rose" in instances

    def test_full_instance_shape(self):
        tracker_state.add("Sam")
        tracker_state.assign("Sam", "My Project", "context")
        inst = tracker_state.load()["instances"]["Sam"]
        assert len(inst["active"]) == 1
        assert inst["active"][0]["project"] == "My Project"
        assert inst["active"][0]["notes"] == "context"
        assert inst["active"][0]["assigned_at"] is not None
        assert inst["history"] == []

    def test_instances_ordered_by_name(self):
        for name in ["Zara", "Alice", "Mike"]:
            tracker_state.add(name)
        names = list(tracker_state.load()["instances"].keys())
        assert names == sorted(names)


# ── age / duration_between ─────────────────────────────────────────────────────

class TestFormatters:
    def test_age_none_returns_empty(self):
        assert tracker_state.age(None) == ""

    def test_age_invalid_returns_question_mark(self):
        assert tracker_state.age("not-a-date") == "?"

    def test_duration_both_none(self):
        assert tracker_state.duration_between(None, None) == "?"

    def test_duration_one_none(self):
        assert tracker_state.duration_between("2024-01-01T00:00:00+00:00", None) == "?"

    def test_duration_one_hour(self):
        result = tracker_state.duration_between(
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T01:00:00+00:00",
        )
        assert result == "1h00m"

    def test_duration_thirty_seconds(self):
        result = tracker_state.duration_between(
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T00:00:30+00:00",
        )
        assert result == "30s"
