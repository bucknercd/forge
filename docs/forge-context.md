# Forge Context (Pivot v1)

## Overview

Forge is a stateful spec-driven workflow engine.

Its job is to reduce the planning and coordination burden of spec-driven development by turning a high-level idea into structured, editable project artifacts and task-level implementation prompts.

The LLM is stateless. All real project state is persisted in files.

Forge does not treat human review, manual edits, or external coding agents as failure cases. They are first-class parts of the workflow.

In the pivoted workflow, Forge is primarily responsible for:
- generating and maintaining design artifacts
- expanding milestones into tasks
- tracking task workflow state
- compiling task context into Cursor-ready prompts
- recording explicit completion and provenance

Forge is not primarily an autonomous application code generator in this workflow.

---

## Primary Workflow

The intended workflow is:

1. The user writes or refines `docs/vision.txt`
2. Forge generates or updates:
   - `docs/requirements.md`
   - `docs/architecture.md`
   - `docs/milestones.md`
3. The user reviews and edits milestones as needed
4. Forge expands one milestone or more into task files under `.system/tasks/`
5. The user reviews and edits tasks as needed
6. Forge syncs persistent prompt-task state
7. Forge generates a Cursor-ready prompt for:
   - one task
   - one milestone
   - or another explicit prompt scope supported by the CLI
8. The user copies the prompt into Cursor or another coding agent
9. The coding agent or human makes code changes outside Forge
10. The user reviews the result and runs tests as needed
11. The user explicitly marks the task complete through Forge
12. Forge persists task state and workflow provenance

This means Forge owns workflow state, but does not directly own application code authoring in the main pivot flow.

---

## Core Artifacts

### Design artifacts

Stored as markdown under `docs/`:
- `docs/vision.txt`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/milestones.md`

These artifacts are editable by the user. Manual changes are expected and supported.

### Task artifacts

Stored as file-based state under `.system/`:
- `.system/tasks/m<id>.json`
- `.system/prompt_tasks.json`
- `.system/prompts/`

These artifacts represent milestone-derived tasks, persistent prompt-task workflow state, and generated prompt outputs.

### Run artifacts

Structured run and workflow artifacts may be stored under:
- `.forge/runs/<run_id>/`

These are for diagnostics, provenance, and debugging.

---

## Product Boundary

Forge is a workflow orchestrator, not the primary coding engine.

Forge is responsible for:
- idea to specs
- specs to milestones
- milestones to tasks
- task state tracking
- prompt generation
- explicit completion tracking
- provenance and file-based state

Cursor or the human developer is responsible for:
- implementing code changes
- editing source files
- running and interpreting tests
- deciding when implementation quality is acceptable

Forge must not implicitly mark coding work complete based on prompt generation alone.

---

## State Model

Forge persists workflow state in files.

### Prompt-task state

Stored in:
- `.system/prompt_tasks.json`

Purpose:
- durable task inventory for the prompt workflow
- exactly one active task at a time
- explicit status transitions

Supported statuses:
- `pending`
- `active`
- `completed`

Task completion is explicit. It is not an automatic side effect of prompt generation.

### Milestone task files

Stored in:
- `.system/tasks/m<id>.json`

Purpose:
- milestone-local task decomposition
- editable task definitions
- source input for prompt-task synchronization

---

## Task Workflow Model

Forge treats tasks as the main unit of implementation planning.

A milestone may be expanded into multiple ordered tasks.

The user may:
- inspect tasks
- edit tasks manually
- remove tasks
- add tasks
- regenerate tasks when needed
- tighten task wording through future workflow helpers

Forge should preserve task linkage and workflow continuity when tasks are synchronized into prompt-task state.

Prompt-task synchronization should:
- be deterministic
- preserve ordering
- preserve source linkage where possible
- preserve completed history where safe
- maintain exactly one active task candidate

---

## Prompt Workflow

Prompt generation is a first-class feature of the pivot.

Forge should be able to compile a stable prompt from:
- the selected task
- milestone context
- `docs/vision.txt`
- `docs/requirements.md`
- `docs/architecture.md`
- relevant task metadata such as validation, done conditions, or allowed files

Prompt generation should:
- be deterministic
- be file-based
- produce inspectable output
- avoid mutating task completion state
- support clean handoff to Cursor

Generated prompt artifacts should be stored under:
- `.system/prompts/`

Prompt generation is a handoff step, not a completion step.

---

## Human Review and Editing

Human review is part of the normal workflow.

The user is expected to:
- edit milestones
- edit tasks
- review generated prompts
- review code produced by Cursor or another coding agent
- explicitly acknowledge completion

Forge should reduce planning overhead while preserving human judgment and control.

---

## Validation Model

In the pivot workflow, validation is centered on artifact quality and workflow correctness.

Forge should validate:
- milestone structure
- task structure
- prompt-task state integrity
- prompt generation inputs and outputs
- source linkage and ordering invariants
- explicit completion transitions

Forge may support optional validation helpers tied to task completion, but task completion remains an explicit Forge-owned action.

Forge should not assume code is correct merely because a prompt was generated.

---

## CLI Design Intent

The CLI should be task-first and easy to use.

Representative workflow commands include:
- `forge init`
- `forge build --from-vision`
- `forge task-expand --milestone 1`
- `forge prompt-task-sync --milestone 1`
- `forge prompt-task-list`
- `forge prompt-task-activate --id 2`
- `forge prompt-generate --task 2`
- `forge prompt-task-complete --id 2`

The CLI should make it easy to:
- move from idea to milestones
- move from milestones to tasks
- move from tasks to prompts
- explicitly mark progress

The CLI should not force the user into autonomous code generation as the main path.

---

## Architecture Direction

Forge should remain:
- file-based
- minimal
- explicit
- deterministic where possible
- easy to inspect
- easy to recover from
- safe to use incrementally

Prefer small modules and narrow responsibilities.

Avoid turning Forge into a framework-heavy orchestration system.

Think like a systems engineer building a reliable workflow tool, not like a framework builder.

---

## Current Pivot Priorities

### Phase 1 - Prompt-task state
Goal:
- durable prompt-task state with explicit task activation and completion

Status:
- complete

### Phase 2 - Task projection and synchronization
Goal:
- deterministic synchronization from milestone task files into prompt-task state

Status:
- complete

### Phase 3 - Prompt compiler
Goal:
- compile a selected task into a Cursor-ready prompt artifact

Status:
- complete

### Phase 4 - Explicit workflow ownership
Goal:
- ensure Forge owns state transitions while coding happens outside Forge

Status:
- complete

  - explicit task start/handoff added
  - prompt workflow history file added
  - completion provenance / fuller lifecycle tracking still pending


### Phase 5 - Validation and feedback
Goal:
- connect explicit completion, validation, and feedback loops without reverting to autonomous code generation as the default path

Status:
- TODO

---

## Non-Goals For The Primary Pivot Flow

The main pivot workflow should not primarily:
- generate and apply source-code changes automatically
- rewrite application files as its default happy path
- run autonomous repair loops as the core user experience
- mark milestones complete based on direct code application inside Forge

Legacy execution machinery may still exist internally during transition, but it is not the intended primary product behavior.

---

## Guidance For Future Changes

When making changes to Forge:
- prefer minimal solutions
- keep everything file-based
- preserve clear workflow state ownership
- support manual editing as a first-class capability
- keep prompts inspectable and reproducible
- avoid overengineering
- challenge design changes that blur the boundary between planning orchestration and code authoring

Forge should make spec-driven development easier, lighter, and more structured without taking control away from the developer.