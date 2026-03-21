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
1. Load milestone definition
2. Build a bounded `ExecutionPlan`
3. Update runtime state → `in_progress`
4. Apply deterministic actions to real design artifacts
5. Record structured execution results, including artifact summaries and diffs
6. Validate resulting artifact state
7. Update runtime state → `completed | retry_pending | failed`
8. Log outcome in run history

---

## Validation Model

Forge validates execution at multiple levels:

- milestone structure must parse correctly
- action definitions must conform to the bounded action grammar
- validation rules must parse correctly
- execution results must reflect actual artifact changes
- reviewed plans must pass stale/mismatch checks before apply
- optional post-apply gates may run:
  - milestone validation
  - explicit test commands

LLM-generated plans must pass the same bounded action parsing and validation as deterministic plans.

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

Forge currently supports:

- deterministic milestone execution against real design artifacts
- retry-aware state transitions and run history
- line-aware milestone diagnostics
- milestone linting and preview
- reviewed-plan save/apply workflow
- stale plan detection
- optional validation and test gates
- repo-configured policy defaults
- optional LLM-backed planning through a bounded planner interface
- passing automated test coverage across unit, integration, and CLI layers

---

## Design Direction

Continue improving trust and transparency for non-deterministic planning, while keeping deterministic execution as the default and safest path.

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


## LLM planner (optional)

- Default remains **deterministic** planning from milestone `Forge Actions`.
- Forge supports an optional LLM-backed planner through the `LLMClient` abstraction.
- Repo policy (`forge-policy.json` → `planner`) selects planner mode and client implementation.
- Sensitive credentials are provided only through environment variables, never repo config.
- All provider-backed plans must still pass the same bounded action parsing and validation as deterministic plans.
- The planner may propose actions, but it never writes files directly.
- `OpenAIChatClient` is the first real provider-backed implementation; additional providers can be added behind the same interface.


## Next TODO

Add a real LLM-backed planner implementation behind the existing planner interface.

- implement an LLM planner that generates milestone preview plans from repository state
- keep the planner behind the current planner selection flow so deterministic planners still work unchanged
- make the first version narrow and predictable: one prompt, one response shape, one parser
- validate and normalize LLM output into the same internal plan structure used by existing workflows
- fail clearly when LLM output is malformed, incomplete, or cannot be parsed safely
- preserve planner provenance metadata so outputs clearly show LLM-generated origin
- avoid applying plans directly; continue routing non-deterministic plans through reviewed-plan safeguards

Goal:
Introduce a real non-deterministic planner without weakening the existing deterministic path or review guarantees.