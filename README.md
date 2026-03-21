# Forge

Forge is a **spec-driven CLI** that turns ideas into working systems.

It uses LLMs to generate milestones and code, while enforcing **review, validation, and reproducibility**.

---

## Quick Start (vertical slice)

Reproduce the full loop **vision → requirements/architecture → milestones → plan → apply → validation** without writing policy by hand using the built-in demo:

```bash
mkdir forge-demo && cd forge-demo
forge init
forge vertical-slice --demo
```

**What happens**

1. Writes `docs/vision.txt`, `docs/requirements.md`, `docs/architecture.md`, and `docs/milestones.md` with a tiny **CLI todo** example.
2. Builds an execution plan from milestone **Forge Actions** (deterministic by default), including `write_file examples/todo_cli.py | …`.
3. Saves a reviewed plan under `.system/reviewed_plans/`.
4. Applies the plan (creates `examples/todo_cli.py`, appends to requirements, updates milestone status in `docs/milestones.md`).
5. Runs **Forge Validation** (`path_file_contains`, `file_contains`) and the repo test gate **`python examples/todo_cli.py`** (demo default).

**Progress output** is driven by a small **event bus** (not ad hoc `print` / logging): you’ll see phases (materialize, plan, apply, validation), each applied action (especially file paths), and gate results. It ends with **`Overall: success`** or **`Overall: failure`**.

Each run also writes an inspectable log under **`.forge/runs/<run_id>/`**:

- `run_meta.json` — command, flags, milestone id  
- `events.jsonl` — one JSON object per line (`type`, `ts`, `run_id`, `data`)

Use **`--verbose`** for a bit more detail (e.g. phase summaries). Use **`--json`** for a single machine-readable blob (includes the same `events` list plus `run_log_dir` / `events_path`).

Then try:

```bash
python examples/todo_cli.py --add "buy milk"
```

which should print a line like `Added todo: buy milk`.

**JSON trace**

```bash
forge vertical-slice --demo --json
```

**Your own idea (LLM)**

Configure `forge-policy.json` → `planner.llm_client` (e.g. `openai` with `FORGE_OPENAI_API_KEY` or `OPENAI_API_KEY` set). Then:

```bash
forge vertical-slice --idea "Small FastAPI service with a /health route"
```

Use `--gate-test-cmd 'pytest -q'` (or similar) to match whatever the LLM milestone expects.

**Bounded file writes**

- Forge action: `write_file <rel_path> | <body>` (use `\n` in the body for newlines).  
  Allowed prefixes: `examples/`, `src/`, `scripts/`, `tests/`.
- Validation: `path_file_contains <rel_path> <substring>` (substring is the rest of the line).

---

## Overview

Forge follows a spec-driven workflow:

```text
Idea
→ Vision
→ Specs (requirements, architecture)
→ Milestones (LLM-generated)
→ Implementation Plan
→ Code + Tests
→ Validation + Feedback Loop
→ Working System
```

Forge is not just code generation.

It is a **system compiler**:

* specs define intent
* LLMs generate work
* Forge enforces correctness

---

## How Forge Works

```text
Idea
  │
  ▼
Vision
  │
  ▼
Specs
(requirements, architecture)
  │
  ▼
LLM Synthesis
(milestones + plans + code)
  │
  ▼
Execution Engine (Forge)
  │
  ├── Generate code
  ├── Run tests
  ├── Apply changes
  │
  ▼
Validation Gates
  │
  ├── pass → commit + next milestone
  └── fail → feedback loop
                │
                ▼
         LLM refinement
                │
                └───────────────┐
                                ▼
                          retry execution
```
---

## What Forge Does

* Converts ideas into structured specs
* Generates milestones using LLMs
* Produces implementation plans
* Generates code and tests
* Applies changes through validation gates
* Iterates until the system passes validation

---

## Core Model

Forge separates responsibilities:

| Layer | Responsibility                   |
| ----- | -------------------------------- |
| Idea  | Human input                      |
| Specs | Source of truth                  |
| LLM   | Generate milestones, plans, code |
| Forge | Execute, validate, track state   |

---

## From Idea to Specs

Start with an idea:

```text
Build a CLI tool that prints "hello world"
```

Forge turns this into structured specs:

* `vision.txt`
* `requirements.md`
* `architecture.md`

These become the foundation for all work.

---

## Milestone Generation (LLM)

Forge uses LLMs to generate milestones from specs:

```json
{
  "id": "M1",
  "objective": "Implement CLI hello command",
  "derived_from": ["REQ-1"],
  "tasks": [
    "create CLI entrypoint",
    "implement hello command",
    "add unit tests"
  ]
}
```

Milestones are:

* structured
* traceable to specs
* reviewed before execution

---

## Code Generation + Execution

Each milestone produces:

* file changes
* code
* tests

Forge executes through a plan:

```text
- create forge/cli.py
- implement hello command
- add tests/test_cli.py
- run pytest
```

---

## Validation + Feedback Loop

Forge enforces validation before applying changes:

* run tests
* enforce timeouts
* check outputs

If validation fails:

```text
fail → refine → regenerate → retry
```

This creates a loop:

```text
generate → test → fix → repeat
```

Until the system passes.

---

## Installation

```bash
git clone git@github.com:bucknercd/forge.git
cd forge
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Usage

```bash
forge milestone-next
forge milestone-preview --milestone-id 1
forge milestone-apply-plan --milestone-id 1
```

---

## Enable LLM

```bash
export OPENAI_API_KEY=your_key_here
```

```bash
forge milestone-preview --milestone-id 1 --planner llm
```

---

## Guarded Workflow

```bash
forge workflow-guarded \
  --synthesize \
  --apply-plan \
  --gate-test-cmd "pytest"
```

This performs:

1. milestone generation (LLM)
2. review + acceptance
3. plan generation
4. execution with validation

---

## Validation Gates

Forge enforces safety:

* test execution (`pytest`)
* timeout limits
* output limits

Example:

```bash
forge milestone-apply-plan \
  --milestone-id 1 \
  --gate-test-cmd "pytest" \
  --gate-test-timeout-seconds 60
```

---

## Project Layout

* `docs/` — specs (source of truth)
* `forge/` — engine (CLI, planner, executor, validator)
* `tests/` — validation
* `.system/` — generated state

---

## Design Principles

* Spec-driven — specs define all work
* LLM-first generation — milestones and code are synthesized
* Deterministic execution — reproducible by default
* Validation before apply — no unsafe changes
* Explicit state — everything persisted

---

## Summary

Forge is a:

> **Spec-driven system generator with LLM-assisted planning and built-in validation**

It turns structured intent into working, validated software.

---

## License

MIT
