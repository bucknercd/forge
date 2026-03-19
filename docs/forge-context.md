# Forge Context (v1)

## Overview
Forge is a stateful design engine that converts high-level ideas into structured design artifacts.

The LLM is stateless. All real system state is persisted in files.

Forge v1 focuses ONLY on the design layer.

---

## Core Concepts

- Design artifacts are stored as markdown:
  - docs/vision.txt
  - docs/requirements.md
  - docs/architecture.md
  - docs/decisions.md
  - docs/milestones.md

- The system operates through:
  - parsing
  - execution
  - validation
  - state transitions

---

## Architecture

### Modules

- Paths: central file locations
- FileRepository: file read/write utilities
- VisionManager: vision load/save
- DesignManager: document load/save
- MilestoneService: parses milestones from markdown
- DecisionTracker: appends decisions
- RunHistory: logs execution events
- Executor: executes milestones
- Validator: validates execution results

---

## Execution Model

### Executor.execute_milestone(id)

Steps:
1. Load milestone
2. Create plan file
3. Log execution start
4. Update state → in_progress
5. Create result file
6. Validate
7. Update state → completed | retry_pending | failed
8. Log outcome

---

## Validation Rules

A milestone is valid if:
- plan file exists
- result file exists
- result contains required fields
- milestone fields are non-empty:
  - objective
  - scope
  - validation

---

## State Model

Stored in:
.system/milestone_state.json

Format:
{
  "1": {
    "status": "not_started | in_progress | retry_pending | completed | failed",
    "attempts": number
  }
}

---

## Retry Behavior

- MAX_RETRIES = 2

Execution:
- attempts increment on each run
- if validation fails:
  - attempts < max → retry_pending
  - attempts >= max → failed

---

## Constraints

- Python standard library only
- File-based persistence only
- No databases
- No frameworks
- Keep system minimal and extensible

---

## Current Status

- CLI implemented
- milestone parsing works
- execution + validation loop works
- retry-aware execution implemented
- tests passing (or close to passing)

---

## Next Direction

Move toward:
- milestone selection (next task logic)
- conversational interface (less manual CLI)
- smarter execution loop

---

## Guidance for Assistant

- Prefer minimal solutions
- Avoid overengineering
- Keep everything file-based
- Think like a systems engineer, not a framework builder
- Challenge bad design decisions



# Next TODO

