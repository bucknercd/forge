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
## Explicit Project Bootstrap and Safe Command Behavior

Forge should support explicit project initialization and safer command behavior when run in directories that are not yet valid Forge projects.

### Goal
Make Forge behave like a real CLI tool by adding a dedicated `forge init` command, project validation, and predictable handling for missing Forge files.

### Deliverables
- Add a real `forge init` command
- `forge init` should create required directories:
  - `docs/`
  - `.system/`
  - `artifacts/`
- `forge init` should create required baseline files if missing:
  - `docs/vision.txt`
  - `docs/requirements.md`
  - `docs/architecture.md`
  - `docs/decisions.md`
  - `docs/milestones.md`
  - `.system/run_history.log`
- Add centralized project validation logic
- Add a way to determine whether the current directory is a valid Forge project
- Refactor command behavior so non-init commands do not silently create a full project unless that is intentionally desired
- Ensure commands fail clearly and helpfully when required project files are missing
- Show actionable guidance such as suggesting `forge init`

### Rules
- Keep CLI thin
- Keep project validation and initialization logic centralized
- Do not duplicate path or bootstrap logic across commands
- Preserve minimal standard-library-only design
- Prefer explicit initialization over surprising side effects

### Command behavior expectations
- `forge init`
  - initializes the current working directory as a Forge project
  - creates missing directories and baseline files
  - does not overwrite existing files
- `forge status`
  - should work safely in initialized projects
  - should show a clear message if run outside a Forge project
- `forge milestone-next`
  - should fail clearly if project files are missing or project is not initialized
- `forge execute-next`
  - should fail clearly if project files are missing or project is not initialized

### Tests
Unit tests:
- project validation returns true for a valid initialized project
- project validation returns false for a non-Forge directory
- init creates all required directories
- init creates all required files without overwriting existing content

Integration tests:
- run `forge init` inside a temporary directory
- verify all required directories/files are created
- verify `status` works after init
- verify non-init commands produce clear errors before init
- verify repeated `forge init` is safe and idempotent

### Constraints
- Python standard library only
- no frameworks
- minimal clean changes
- no large architectural rewrite unless necessary

### Design intent
This step makes Forge safer and more predictable by separating project bootstrap from normal command execution.