# Forge

**Forge** is a file-based CLI for turning high-level ideas into structured design artifacts and validated, milestone-driven execution. State lives on disk—no database, no frameworks.

## Features

- **Design artifacts** under `docs/`: vision, requirements, architecture, decisions, milestones
- **Runtime state** under `.system/`: milestone state, plans, results, run history
- **Dependency-aware milestones**, retries, LLM-backed execution (stub-friendly), and append-only audit trails

## Requirements

- Python **3.12+**
- Standard library only at runtime (see `pyproject.toml`)

## Install

From the repository root:

```bash
git clone <repository-url> forge
cd forge
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

This installs the `forge` console script (`forge.cli:main`).

## Quick start

Create or enter a project directory, then initialize Forge:

```bash
mkdir my-project && cd my-project
forge init
```

`forge init` creates (when missing):

| Path | Purpose |
|------|---------|
| `docs/` | Design documents |
| `.system/` | Runtime state and logs |
| `artifacts/` | Optional generated outputs |

Baseline files (with starter templates where applicable):

- `docs/vision.txt`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/milestones.md`
- `.system/run_history.log`

Existing files are **not** overwritten.

### Project readiness

```bash
forge status
```

Reports a **project state** such as:

- **not_initialized** — run `forge init`
- **initialized_incomplete** — templates or empty docs need real content
- **ready** — minimal structure and content look usable

### Milestones

Edit `docs/milestones.md`. Each milestone should use a heading like:

```markdown
## Milestone 1: Your title
- **Objective**: …
```

(Objective is required; see project docs for full rules.)

### Common commands

```bash
forge milestone-sync-state   # reconcile .system/milestone_state.json with milestones.md
forge milestone-next         # show next eligible milestone
forge execute-next           # run the next eligible milestone (orchestration)
```

Other commands (`milestone-list`, `milestone-show`, `milestone-execute`, etc.) are available; run `forge --help` after install.

## Where things live

```
docs/                 # Vision, requirements, architecture, decisions, milestones
.system/              # milestone_state.json, plans/, results/, run_history.log
artifacts/            # Reserved for generated outputs
forge/                # Package source
tests/                # Pytest suite
```

## Audit trails

- **Decisions** — append-only entries in `docs/decisions.md` (e.g. after successful milestone completion).
- **Run history** — JSON Lines in `.system/run_history.log` (structured attempt records; append-only).

## Development

```bash
source .venv/bin/activate
python -m pytest
```

## License

MIT
