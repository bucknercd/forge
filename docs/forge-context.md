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
## Milestone Structure Validation and Parsing Hardening

Forge should validate milestone structure more explicitly so milestone-driven commands operate on predictable, well-formed milestone definitions.

### Goal
Make milestone parsing and execution safer by enforcing a minimal milestone structure and reporting malformed milestone definitions clearly.

### Deliverables
- Add centralized milestone validation logic
- Define a minimal valid milestone structure
- Detect malformed or incomplete milestone blocks in `docs/milestones.md`
- Refactor milestone parsing flow so `milestone-next` and `execute-next` depend on validated milestone data
- Improve error reporting for invalid milestone definitions
- Keep milestone parsing and validation logic centralized and reusable

### Minimal valid milestone structure
A milestone should include at least:
- a recognizable milestone heading, such as:
  - `## Milestone 1: Title`
- an objective field
- optional scope/validation fields may remain optional for now unless already required elsewhere

### Rules
- Keep CLI thin
- Do not duplicate milestone validation logic across commands
- Use Python standard library only
- Prefer simple deterministic parsing over flexible but fragile parsing
- Preserve compatibility with current milestone style where practical

### Command behavior expectations
- `forge milestone-next`
  - should ignore malformed milestones only if that is explicitly intended
  - otherwise should fail clearly when milestone definitions are invalid
- `forge execute-next`
  - should fail clearly if the next milestone is malformed or incomplete
- `forge status`
  - may report milestone validation issues as part of readiness output if practical

### Tests
Unit tests:
- valid milestone blocks parse successfully
- malformed milestone headings are detected
- milestones missing objective are detected
- multiple milestones parse deterministically
- validation errors are reported clearly

Integration tests:
- temp project with valid milestones supports `milestone-next`
- temp project with malformed milestones produces clear errors
- temp project with missing objective prevents execution cleanly

### Constraints
- Python standard library only
- minimal clean changes
- no large rewrite unless necessary

### Design intent
This step makes milestone-based workflows reliable by ensuring Forge operates on validated milestone definitions instead of loosely structured markdown.