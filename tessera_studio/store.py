"""Read-only access to local Tessera project stores.

Tessera keeps one directory per project under ``tessera/projects/<sha256>``.
This module never writes, never follows paths taken from request input and
never exposes source text (``derived.json``, ``request.json``, ``context.json``).
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

PROJECT_ID = re.compile(r"^[0-9a-f]{64}$")
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
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
        if packages.is_dir():
            roots += sorted(p / "LocalCache/Local/tessera/projects" for p in packages.iterdir() if p.is_dir())
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


class Store:
    def __init__(self, roots: list[Path]):
        self.roots = [Path(r) for r in roots]

    def _directories(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for child in root.iterdir():
                if child.is_dir() and PROJECT_ID.match(child.name) and child.name not in found:
                    found[child.name] = child
        return found

    def _project_dir(self, project_id: str) -> Path:
        if not PROJECT_ID.match(project_id or ""):
            raise NotFound(project_id)
        directory = self._directories().get(project_id)
        if directory is None:
            raise NotFound(project_id)
        return directory

    # Listing ---------------------------------------------------------------

    def projects(self) -> list[dict]:
        items = [self._summary(pid, path) for pid, path in self._directories().items()]
        return sorted(items, key=lambda item: item["updated"], reverse=True)

    def _summary(self, project_id: str, directory: Path) -> dict:
        catalog = read_json(directory / "catalog.json") or {}
        inventory = read_json(directory / "inventory.json") or {}
        entries = catalog.get("entries") or []
        decisions = list((directory / "decisions").glob("*.json"))
        return {
            "id": project_id,
            "name": catalog.get("project") or self._repo_name(directory) or project_id[:12],
            "repo_path": self._repo_path(directory),
            "store": str(directory),
            "initialized": bool(catalog),
            "entries": len(entries),
            "kinds": Counter(e.get("kind", "unknown") for e in entries).most_common(),
            "files": len(inventory.get("files") or {}),
            "decisions": len(decisions),
            "revision": catalog.get("reviewed_revision"),
            "reviewed_on": catalog.get("reviewed_on"),
            "finalized": self._finalized(catalog, inventory),
            "updated": self._updated(directory),
        }

    @staticmethod
    def _finalized(catalog: dict, inventory: dict) -> bool:
        final = inventory.get("finalized") or {}
        return bool(final.get("revision")) and final.get("revision") == catalog.get("reviewed_revision")

    @staticmethod
    def _updated(directory: Path) -> float:
        stamps = [p.stat().st_mtime for p in (directory / "catalog.json", directory / "inventory.json") if p.is_file()]
        return max(stamps, default=directory.stat().st_mtime)

    @staticmethod
    def _manifests(directory: Path) -> list[dict]:
        runs = directory / "runs"
        if not runs.is_dir():
            return []
        manifests = [read_json(run / "manifest.json") for run in runs.iterdir() if run.is_dir()]
        return sorted((m for m in manifests if m), key=lambda m: m.get("created_at", ""))

    def _repo_path(self, directory: Path) -> str | None:
        manifests = self._manifests(directory)
        return manifests[-1].get("repo_path") if manifests else None

    def _repo_name(self, directory: Path) -> str | None:
        path = self._repo_path(directory)
        return Path(path).name if path else None

    # Project detail --------------------------------------------------------

    def project(self, project_id: str) -> dict:
        directory = self._project_dir(project_id)
        catalog = read_json(directory / "catalog.json") or {}
        inventory = read_json(directory / "inventory.json") or {}
        files = [
            {"path": path, "kind": (info.get("review") or {}).get("kind", "pending"),
             "reason": (info.get("review") or {}).get("reason")}
            for path, info in sorted((inventory.get("files") or {}).items())
        ]
        history = directory / "history"
        return {
            **self._summary(project_id, directory),
            "coverage": catalog.get("coverage"),
            "scope": catalog.get("scope") or [],
            "supporting_files": catalog.get("supporting_files") or [],
            "catalog": catalog.get("entries") or [],
            "inventory": files,
            "inventory_revision": inventory.get("revision"),
            "history": len(list(history.iterdir())) if history.is_dir() else 0,
            "decision_list": [self._decision_summary(d) for d in self._decisions(directory)],
        }

    @staticmethod
    def _decisions(directory: Path) -> list[dict]:
        items = [read_json(p) for p in sorted((directory / "decisions").glob("*.json"))]
        return sorted((d for d in items if d and d.get("task_id")), key=lambda d: d.get("reviewed_on") or "", reverse=True)

    @staticmethod
    def _decision_summary(decision: dict) -> dict:
        keys = ("task_id", "provider", "model", "provider_action", "provider_primary", "agent_final_choice",
                "relation_to_provider", "review_status", "reviewed_on", "implemented_in", "usage")
        return {key: decision.get(key) for key in keys}

    # Decision detail -------------------------------------------------------

    def decision(self, project_id: str, task_id: str) -> dict:
        directory = self._project_dir(project_id)
        if not TASK_ID.match(task_id or ""):
            raise NotFound(task_id)
        match = next((d for d in self._decisions(directory) if d["task_id"] == task_id), None)
        if match is None:
            raise NotFound(task_id)
        record = {k: v for k, v in match.items() if k != "run"}
        task = read_json(directory / "tasks" / f"{task_id}.json")
        record["task"] = {k: task.get(k) for k in ("id", "requirement", "acceptance")} if task else None
        run_name = Path(str(match.get("run") or "")).name
        run = directory / "runs" / run_name
        record["trace"] = self._trace(run) if run_name and run.is_dir() else None
        return record

    @staticmethod
    def _trace(run: Path) -> dict:
        manifest = read_json(run / "manifest.json") or {}
        batches, best = [], {}
        calls = run / "calls"
        for call in sorted(calls.iterdir()) if calls.is_dir() else []:
            answer = (read_json(call / "result.json") or {}).get("answer") or {}
            probabilities = answer.get("probabilities") or {}
            ranked = sorted(((k, v) for k, v in probabilities.items() if k not in OPEN_OPTIONS),
                            key=lambda item: -item[1])
            batches.append({"call": call.name, "choice": answer.get("choice"),
                            "confidence": answer.get("confidence"),
                            "best": ranked[0] if ranked else None})
            for option, value in ranked:
                best[option] = max(best.get(option, 0.0), value)
        response = read_json(run / "response.json") or {}
        final = ((response.get("answers") or {}).get("decision") or {}).get("probabilities") or {}
        keys = ("created_at", "strategy", "entry_count", "initial_batches", "max_calls", "revision", "provider")
        return {
            "manifest": {k: manifest.get(k) for k in keys},
            "batches": batches,
            "alternatives": sorted(best.items(), key=lambda item: -item[1])[:12],
            "final": sorted(final.items(), key=lambda item: -item[1]),
        }
