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

## Testing Model

Forge uses layered testing to validate system behavior.

### Unit tests
- Validate pure logic:
  - milestone parsing
  - state transitions
  - dependency resolution
  - validation rules
  - milestone selection

### Integration tests
- Validate end-to-end system behavior through core services
- Use real file-based state and artifacts
- Call services directly (Executor, MilestoneService, etc.)
- Do NOT rely on CLI invocation

### CLI tests
- Minimal smoke tests only
- Validate commands run successfully and produce expected output
- Do not use CLI as primary testing interface

### Design intent
Testing should validate system behavior, not interface behavior.
The CLI is a thin wrapper and should not be the primary integration boundary.

## Orchestration

Forge supports a high-level execution loop via `execute-next`.

- Automatically selects the next eligible milestone
- Executes and validates it
- Updates runtime state
- Reports outcome

This enables iterative, state-aware project progression.


## Next TODO
## Project Status Validation and Missing-Content Reporting

Forge should provide clearer project health feedback by validating required files and reporting missing or incomplete content in a structured way.

### Goal
Make `forge status` more useful by showing whether a Forge project is merely initialized or actually ready for use, based on required files and meaningful content.

### Deliverables
- Add centralized project status validation logic
- Distinguish between:
  - project not initialized
  - project initialized but incomplete
  - project initialized and minimally ready
- Detect missing required files
- Detect empty or placeholder-only content in key docs
- Refactor `forge status` to report structured readiness information
- Keep validation/reporting logic centralized and reusable

### Rules
- Keep CLI thin
- Do not duplicate validation logic across commands
- Use Python standard library only
- Prefer simple readable checks over complex scoring
- Keep output practical and easy to understand

### Suggested readiness checks
- `docs/vision.txt` exists and is not empty
- `docs/requirements.md` exists and is not empty
- `docs/architecture.md` exists and is not empty
- `docs/milestones.md` exists and contains at least one milestone heading or recognizable milestone entry
- `docs/decisions.md` may exist even if currently empty, but should still be reported clearly

### Tests
Unit tests:
- validation reports missing files correctly
- validation reports empty/template-only files correctly
- validation distinguishes initialized vs minimally ready project

Integration tests:
- run `forge status` in a temp initialized project with only template content
- verify output marks project as incomplete
- fill in minimal content and verify output marks project as ready
- verify missing-file scenarios are reported clearly

### Constraints
- Python standard library only
- minimal clean changes
- no large rewrite

### Design intent
This step makes Forge status meaningful by turning it into a project-health report instead of only a filesystem check.