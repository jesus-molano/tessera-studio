# Tessera Studio

A local, read-only browser for [Tessera](https://github.com/jesus-molano/dotfiles/tree/main/ai/skills/tessera)
catalogs: the per-project knowledge of reusable components and utilities, the
file inventory behind it, and the reuse decisions made with Jev.

- **Projects**: every Tessera store found on this machine, with status and composition.
- **Overview**: KPIs, a mosaic with one tile per catalog entry, kinds, inventory review and coverage.
- **Catalog**: search and filter entries; inspect contract, constraints and real usages.
- **Inventory**: every tracked file and how the review classified it.
- **Decisions**: requirement and acceptance, Jev versus the agent, final-round
  probabilities, per-batch choices and the strongest candidates.
- **Command palette** (`Ctrl`/`Cmd` + `K`) to jump to any project, view, decision or entry. `/` focuses search.

## Run

Requires Python 3.11+. No dependencies, no build step.

```bash
python -m tessera_studio --open
```

Options: `--port 8765` (use `0` for a free port) and `--store PATH` (repeatable) to add more
`tessera/projects` directories.

Default store locations, matching `tessera.py`, in lookup order:

| Order | Directory |
|---|---|
| 1. Current store, every platform | `$TESSERA_HOME/projects`, else `${XDG_DATA_HOME:-~/.local/share}/tessera/projects` (on Windows `%USERPROFILE%\.local\share\tessera\projects`) |
| 2. Older Windows store | `%LOCALAPPDATA%\tessera\projects` |
| 3. Older MSIX app copies (Claude Desktop, Codex) | `%LOCALAPPDATA%\Packages\<app>\LocalCache\Local\tessera\projects` |

MSIX apps virtualize `%LOCALAPPDATA%`, so catalogs written by an agent running
inside them used to exist only in that app's `LocalCache`. `tessera.py` now keeps
the store in the user profile and copies an older one with
`tessera.py adopt-store --repo PROJECT --from PATH`. When the same project exists
in several places, Studio shows the current store's copy; projects found only in
an older store are marked so you can adopt them.

## Privacy and safety

Catalogs often describe work repositories. Studio is built so that data never leaves the machine:

- Binds to `127.0.0.1` only and rejects requests whose `Host` is not the loopback address (DNS rebinding).
- `GET` only; it never writes to the store.
- Never serves run evidence that contains source text (`derived.json`, `context.json`, `request.json`).
- Project and task identifiers are validated; request paths never become file paths.
- Strict Content Security Policy: no external scripts, styles, fonts or requests.

This repository contains only the tool. Do not commit catalogs or screenshots of work projects.

## Develop

```bash
python -m unittest discover -s tests -v
```

The UI is plain HTML, CSS and ES modules under `tessera_studio/static`. The palette
follows Project Atlas "Waypoint Signal": graphite neutrals with a coral signal accent.
