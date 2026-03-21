# Forge

**Forge** is a file-based CLI for turning high-level ideas into structured design artifacts and validated, milestone-driven execution. State lives on disk—no database, no frameworks.

## Features

- **Design artifacts** under `docs/`: vision, requirements, architecture, decisions, milestones
- **Runtime state** under `.system/`: milestone state, structured results, run history
- **Dependency-aware milestones**, deterministic **artifact actions** (no shell / no network), retries, and append-only audit trails

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
- **Scope**: …
- **Validation**: …
```

**Execution (required for `forge execute-next` / `forge milestone-execute`)** — declare deterministic file updates and how to verify them:

```markdown
- **Forge Actions**:
  - append_section requirements Overview | Your marker text or paragraph
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements YOUR_MARKER
```

Supported action verbs (first token): `append_section`, `replace_section`, `add_decision`, `mark_milestone_completed`.  
Targets: `requirements`, `architecture`, `decisions`, `milestones` (mapped to files under `docs/`).

Results are written to `.system/results/milestone_<id>.json`, including `execution_plan`, `files_changed`, `artifact_summary`, and per-action records in `actions_applied` (`outcome`: `changed` | `skipped` | `failed`, optional bounded `diff` unified text when a file actually changes). Structured JSONL in `.system/run_history.log` may include `artifact_summary` on milestone attempts for a quick read of what changed. Successful runs also append a summary entry to `docs/decisions.md` unless the plan includes `add_decision`.

#### Authoring tips and diagnostics

- Use indented list items under `Forge Actions` / `Forge Validation` (`  - ...`).
- Keep action format strict: `append_section <target> <Section Heading> | <body>`.
- Keep validation format strict: `file_contains <target> <substring>` or `section_contains <target> <Section Heading> <substring>`.
- Diagnostics now include milestone + source line when parsing fails (for example: `Milestone 3 action parse error: forge action line 42: ...`).

Example (valid):

```markdown
## Milestone 2: Capture API requirements
- **Objective**: Add API requirements section.
- **Scope**: Update requirements and mark completion.
- **Validation**: Ensure API text exists.
- **Forge Actions**:
  - append_section requirements API | - Define REST endpoints for v1.
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements Define REST endpoints for v1.
```

### Common commands

```bash
forge milestone-sync-state   # reconcile .system/milestone_state.json with milestones.md
forge milestone-next         # show next eligible milestone
forge milestone-preview      # dry-run preview for next eligible milestone
forge milestone-preview 2    # dry-run preview for a specific milestone
forge execute-next           # run the next eligible milestone (orchestration)
```

Other commands (`milestone-list`, `milestone-show`, `milestone-execute`, etc.) are available; run `forge --help` after install.

## Where things live

```
docs/                 # Vision, requirements, architecture, decisions, milestones
.system/              # milestone_state.json, results/*.json, run_history.log
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
