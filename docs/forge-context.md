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


### Next TODO
## LLM-Backed Execution

Forge should integrate an LLM into the execution loop to enable iterative implementation.

### Goal
Enhance milestone execution so that:
- an LLM generates implementation output
- validation (tests) provides feedback
- failures are used to drive retries

### Deliverables
- Add an `LLMClient` abstraction:
  - simple interface: `generate(prompt: str) -> str`
- Implement prompt construction:
  - milestone objective
  - scope
  - validation criteria
  - relevant context (minimal)
- Integrate LLM into execution flow:
  - replace placeholder result generation with LLM output
- Capture validation failures:
  - extract test errors
  - include them in retry prompts
- Update retry loop:
  - use failure feedback to improve subsequent attempts

### Rules
- LLM is a proposal generator only
- validation remains the source of truth
- do not allow LLM to modify runtime state directly
- keep prompts minimal and focused

### Tests
- mock LLM responses for deterministic testing
- test retry flow with simulated failures
- ensure execution loop remains stable without real LLM calls

### Constraints
- no frameworks
- minimal abstraction
- keep system deterministic and testable

### Design intent
This step transforms Forge from a milestone executor into an iterative design + implementation engine driven by validation feedback.