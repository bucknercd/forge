# Forge

Forge is a **spec-driven CLI** that turns ideas into working systems.

It uses LLMs to generate milestones and code, while enforcing **review, validation, and reproducibility**.

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
