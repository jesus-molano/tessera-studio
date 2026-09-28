"""Read-only access to local Tessera project stores.

Tessera keeps one directory per project under ``tessera/projects/<sha256>``.
This module never writes, never follows paths taken from request input and
never exposes source text (``derived.json``, ``request.json``, ``context.json``).

Store files are written by other tools and may be malformed, so every value
read from disk is shape-checked before use: one broken project must not break
the listing or the server.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

PROJECT_ID = re.compile(r"^[0-9a-f]{64}$")
OPEN_OPTIONS = ("create", "insufficient_evidence")


class NotFound(Exception):
    pass


def default_roots() -> list[Path]:
    """Store roots in the same order ``tessera.py`` uses, plus sandboxed app caches.

    Desktop apps packaged with MSIX on Windows (such as Claude) virtualize
    ``%LOCALAPPDATA%``: files written by agents appear under
    ``Packages/<app>/LocalCache/Local`` for every other process.
    """
    roots = []
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        roots.append(local / "tessera/projects")
        packages = local / "Packages"
        try:
            roots += sorted(p / "LocalCache/Local/tessera/projects" for p in packages.iterdir() if p.is_dir())
        except OSError:
            pass
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        roots.append(base / "tessera/projects")
    return roots


def read_json(path: Path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def read_obj(path: Path) -> dict:
    """Read a JSON file that must hold an object; anything else becomes ``{}``."""
    value = read_json(path)
    return value if isinstance(value, dict) else {}


def as_obj(value) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value) -> list:
    return value if isinstance(value, list) else []


def as_text(value) -> str | None:
    """Scalars become text so mixed-type fields sort and render safely."""
    if value is None or isinstance(value, (dict, list)):
        return None
    return str(value)


def as_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _entries(catalog: dict) -> list[dict]:
    entries = []
    for entry in as_list(catalog.get("entries")):
        if not isinstance(entry, dict):
            continue
        entries.append({
            **entry,
            "id": as_text(entry.get("id")) or "",
            "kind": as_text(entry.get("kind")) or "unknown",
            "source": as_text(entry.get("source")) or "",
            "tags": [t for t in as_list(entry.get("tags")) if isinstance(t, (str, int, float))],
            "constraints": [c for c in as_list(entry.get("constraints")) if isinstance(c, (str, int, float))],
            "usages": [u for u in as_list(entry.get("usages")) if isinstance(u, dict)],
        })
    return entries


def _listdir(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


class Store:
    def __init__(self, roots: list[Path]):
        self.roots = [Path(r) for r in roots]

    def _directories(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for root in self.roots:
            for child in _listdir(root):
                if PROJECT_ID.match(child.name) and child.name not in found and child.is_dir():
                    found[child.name] = child
        return found

    def _project_dir(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not PROJECT_ID.match(project_id):
            raise NotFound(project_id)
        directory = self._directories().get(project_id)
        if directory is None:
            raise NotFound(project_id)
        return directory

    # Listing ---------------------------------------------------------------

    def projects(self) -> list[dict]:
        items = []
        for pid, path in self._directories().items():
            try:
                items.append(self._summary(pid, path))
            except Exception:  # noqa: BLE001 - one unreadable project must not hide the others
                items.append(self._broken_summary(pid, path))
        return sorted(items, key=lambda item: item["updated"], reverse=True)

    def _summary(self, project_id: str, directory: Path) -> dict:
        catalog = read_obj(directory / "catalog.json")
        inventory = read_obj(directory / "inventory.json")
        entries = _entries(catalog)
        decisions = list((directory / "decisions").glob("*.json"))
        return {
            "id": project_id,
            "name": as_text(catalog.get("project")) or self._repo_name(directory) or project_id[:12],
            "repo_path": self._repo_path(directory),
            "store": str(directory),
            "initialized": bool(catalog),
            "entries": len(entries),
            "kinds": Counter(e["kind"] for e in entries).most_common(),
            "files": len(as_obj(inventory.get("files"))),
            "reviewed": sum(1 for info in as_obj(inventory.get("files")).values()
                            if isinstance(info, dict) and isinstance(info.get("review"), dict)),
            "decisions": len(decisions),
            "revision": as_text(catalog.get("reviewed_revision")),
            "reviewed_on": as_text(catalog.get("reviewed_on")),
            "finalized": self._finalized(catalog, inventory),
            "updated": self._updated(directory),
        }

    @staticmethod
    def _broken_summary(project_id: str, directory: Path) -> dict:
        return {"id": project_id, "name": project_id[:12], "repo_path": None, "store": str(directory),
                "initialized": False, "entries": 0, "kinds": [], "files": 0, "reviewed": 0, "decisions": 0,
                "revision": None, "reviewed_on": None, "finalized": False, "updated": _mtime(directory)}

    @staticmethod
    def _finalized(catalog: dict, inventory: dict) -> bool:
        final = as_obj(inventory.get("finalized"))
        revision = as_text(final.get("revision"))
        return bool(revision) and revision == as_text(catalog.get("reviewed_revision"))

    @staticmethod
    def _updated(directory: Path) -> float:
        stamps = [_mtime(p) for p in (directory / "catalog.json", directory / "inventory.json") if p.is_file()]
        return max(stamps, default=_mtime(directory))

    @staticmethod
    def _repo_path(directory: Path) -> str | None:
        """Repository path from the newest run, reading as few manifests as possible."""
        runs = [run for run in _listdir(directory / "runs") if run.is_dir()]
        for run in sorted(runs, key=_mtime, reverse=True):
            path = as_text(read_obj(run / "manifest.json").get("repo_path"))
            if path:
                return path
        return None

    def _repo_name(self, directory: Path) -> str | None:
        path = self._repo_path(directory)
        return Path(path).name if path else None

    # Project detail --------------------------------------------------------

    def project(self, project_id: str) -> dict:
        directory = self._project_dir(project_id)
        catalog = read_obj(directory / "catalog.json")
        inventory = read_obj(directory / "inventory.json")
        files = []
        for path, info in sorted(as_obj(inventory.get("files")).items()):
            review = as_obj(as_obj(info).get("review"))
            files.append({"path": path, "kind": as_text(review.get("kind")) or "pending",
                          "reason": as_text(review.get("reason"))})
        history = directory / "history"
        return {
            **self._summary(project_id, directory),
            "coverage": as_text(catalog.get("coverage")),
            "scope": as_list(catalog.get("scope")),
            "supporting_files": as_list(catalog.get("supporting_files")),
            "catalog": _entries(catalog),
            "inventory": files,
            "inventory_revision": as_text(inventory.get("revision")),
            "history": len(_listdir(history)),
            "decision_list": [self._decision_summary(d) for d in self._decisions(directory)],
        }

    @staticmethod
    def _decisions(directory: Path) -> list[dict]:
        items = []
        for path in sorted((directory / "decisions").glob("*.json")):
            decision = read_json(path)
            if isinstance(decision, dict) and isinstance(decision.get("task_id"), str) and decision["task_id"]:
                items.append(decision)
        return sorted(items, key=lambda d: as_text(d.get("reviewed_on")) or "", reverse=True)

    @staticmethod
    def _decision_summary(decision: dict) -> dict:
        keys = ("task_id", "provider", "model", "provider_action", "provider_primary", "agent_final_choice",
                "relation_to_provider", "review_status", "reviewed_on", "implemented_in", "usage")
        return {key: decision.get(key) for key in keys}

    # Decision detail -------------------------------------------------------

    def decision(self, project_id: str, task_id: str) -> dict:
        directory = self._project_dir(project_id)
        if not isinstance(task_id, str) or not task_id:
            raise NotFound(task_id)
        # The id only selects among decisions read from disk; it never becomes a path.
        match = next((d for d in self._decisions(directory) if d["task_id"] == task_id), None)
        if match is None:
            raise NotFound(task_id)
        record = {k: v for k, v in match.items() if k != "run"}
        task = self._task(directory, match["task_id"])
        record["task"] = {k: task.get(k) for k in ("id", "requirement", "acceptance")} if task else None
        # ``run`` may be a Windows or POSIX absolute path; only its last segment is used.
        run_name = re.split(r"[\\/]", as_text(match.get("run")) or "")[-1]
        run = self._child(directory / "runs", run_name)
        record["trace"] = self._trace(run) if run and run.is_dir() else None
        return record

    @staticmethod
    def _child(parent: Path, name: str) -> Path | None:
        """``parent/name`` only when ``name`` is a plain file name that stays inside ``parent``."""
        if not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name:
            return None
        if os.sep in name or (os.altsep and os.altsep in name):
            return None
        try:
            base = parent.resolve()
            candidate = (parent / name).resolve()
        except (OSError, ValueError):
            return None
        return candidate if candidate.parent == base else None

    def _task(self, directory: Path, task_id: str) -> dict | None:
        path = self._child(directory / "tasks", f"{task_id}.json")
        if path is None:
            return None
        task = read_json(path)
        return task if isinstance(task, dict) else None

    @staticmethod
    def _trace(run: Path) -> dict:
        def ranked(probabilities: dict, skip=()) -> list:
            pairs = ((str(k), as_number(v)) for k, v in probabilities.items() if k not in skip)
            return sorted(((k, v) for k, v in pairs if v is not None), key=lambda item: -item[1])

        manifest = read_obj(run / "manifest.json")
        batches, best = [], {}
        for call in sorted(p for p in _listdir(run / "calls") if p.is_dir()):
            answer = as_obj(read_obj(call / "result.json").get("answer"))
            options = ranked(as_obj(answer.get("probabilities")), OPEN_OPTIONS)
            batches.append({"call": call.name, "choice": as_text(answer.get("choice")),
                            "confidence": as_number(answer.get("confidence")),
                            "best": options[0] if options else None})
            for option, value in options:
                best[option] = max(best.get(option, 0.0), value)
        response = read_obj(run / "response.json")
        final = as_obj(as_obj(as_obj(response.get("answers")).get("decision")).get("probabilities"))
        keys = ("created_at", "strategy", "entry_count", "initial_batches", "max_calls", "revision", "provider")
        return {
            "manifest": {k: manifest.get(k) for k in keys},
            "batches": batches,
            "alternatives": sorted(best.items(), key=lambda item: -item[1])[:12],
            "final": ranked(final),
        }
