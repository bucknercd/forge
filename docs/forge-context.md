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
## Structured Run History Tracking

Forge should record structured execution history for each milestone run, making execution observable and debuggable.

### Goal
Make `.system/run_history.log` a meaningful, structured record of milestone execution attempts.

### Deliverables
- Add centralized run-history recording logic
- Record an entry for every execution attempt (success or failure)
- Each run entry should include:
  - timestamp
  - milestone id
  - milestone title
  - execution status (success / failure)
  - optional error message (for failures)
- Ensure append-only behavior
- Keep run history machine-readable (JSON lines or similar format)

### Rules
- Keep CLI thin
- Do not duplicate run-history logic
- Use Python standard library only
- Preserve append-only writes
- Keep entries deterministic and consistent

### Suggested format
Each line in `.system/run_history.log` should be a JSON object:
{
  "timestamp": "...",
  "milestone_id": 1,
  "title": "...",
  "status": "success" | "failure",
  "error": "..." (optional)
}

### Behavior expectations
- Every call to execute-next or execute-milestone writes a run entry
- Successful execution writes a success entry
- Failed execution writes a failure entry with error context
- Decision recording remains separate and only occurs on success

### Tests
Unit tests:
- run entry is written in expected format
- repeated runs append entries
- failure includes error message
- success excludes error field

Integration tests:
- execute milestone in temp project → verify log entry created
- execute failing milestone → verify failure entry written
- repeated runs produce multiple entries

### Constraints
- Python standard library only
- minimal clean changes
- no large rewrite unless necessary

### Design intent
This step makes Forge observable and debuggable by introducing structured execution history alongside decision history.