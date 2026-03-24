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

Forge supports a high-level execution loop via `run-next` (task-first: the next roadmap milestone’s next pending task).

- Automatically selects the next eligible milestone (roadmap ordering)
- Plans/applies/validates the **selected task** (not the whole milestone in one shot)
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


### Recently Shipped

#### Vertical slice
End-to-end flow is available via `forge vertical-slice`:

- `--demo`: deterministic bundle (todo CLI under `examples/`), no LLM for docs
- `--idea "..."`: LLM-generated vision + specs + milestones (requires `forge-policy.json` LLM client)
- `--vision-file PATH` / `--from-vision` (`docs/vision.txt`): vision text from file is authoritative; LLM generates requirements, architecture, and milestones only (same LLM client requirement)

Pipeline:
materialize docs -> save reviewed plan -> apply -> validation gates

Current file creation/edit support includes:
- `write_file`
- `path_file_contains`

`write_file` is currently restricted to:
- `examples/`
- `src/`
- `scripts/`
- `tests/`

See README Quick Start (vertical slice) for usage and expected behavior.

**LLM bundle JSON (internal):** The model is asked for a single `json.loads`-parseable object (not user-facing UX). Extraction tolerates harmless noise (leading/trailing prose, a single markdown fenced JSON block, or the longest unambiguous balanced `{...}`). Ambiguous output (e.g. two same-length top-level objects) or invalid JSON is rejected; failures persist `llm_bundle_raw_*.txt` and optional `llm_bundle_extract_debug_*.txt` under the run artifact dir for debugging.

**Task repair classification:** On apply or gate failure, Forge records a small **repair mode** (`syntax_fix`, `behavior_fix`, `format_fix`, `missing_impl`, `validation_bug`, `planner_output_bug`, `no_op_repair`, `unknown_failure`) in `.system/task_feedback/` and appends a **mode-specific** block to the next LLM planner prompt (`forge/failure_classification.py`, `forge/repair_prompts.py`). Identical replans after an **apply** failure short-circuit with `no_op_repair`; identical plans after **gate** failure still re-run apply so external or mocked gates can change.

**Simple CLI:** `forge start`, `forge build`, `forge fix`, `forge doctor`, `forge logs` are thin wrappers over `init` / `vertical-slice` / `run-next` / diagnostics; see README “Simple CLI shortcuts”.

#### Tasks (two-layer planning)
- **Execution is task-only:** preview, save-plan, **`run-next`**, **`vertical-slice`**, and **`workflow-guarded`** ensure **`.system/tasks/m<id>.json`** exists (same expansion as **`forge task-expand`**) and operate on a **task id**—explicit **`--task`** or the **next pending task**. Milestones in **`docs/milestones.md`** are not executed directly.
- Task JSON holds **2–6 ordered tasks** when deterministic splitting succeeds (`mark_milestone_completed` + validation on the last task); optional LLM JSON expansion when a non-stub OpenAI client is configured; else **one compatibility task**. **`--force`** on **`task-expand`** regenerates from the current milestone text.
- **`forge task-preview <id>`** without **`--task`** lists tasks; with **`--task <n>`** builds/saves reviewed plans; plan ids **`m<id>-t<n>-<hash>`**; apply uses **`task-apply-plan`** + gates. Legacy reviewed plans without **`task_id`** may still apply against the milestone definition in docs. Older CLI names (`milestone-preview`, `milestone-apply-plan`, `execute-next`) remain as deprecated aliases with stderr warnings.
- Milestones may include optional **`- **Summary**:`** in `docs/milestones.md` for short roadmap text.

#### Execution progress + run logs
Structured run events ship for **`forge vertical-slice`** (and the same bus/hooks can extend to other commands later).

- **CLI**: concise, event-driven progress (not `print` spaghetti or logging-as-UX); optional `--verbose`
- **Persistence**: `.forge/runs/<run_id>/` with `run_meta.json` + **`events.jsonl`** (one JSON object per line)
- **`--json`**: same payload shape as before, plus `events`, `run_id`, `run_log_dir`, `events_path`

Event types include: `run_started`, `phase_started`, `phase_completed`, `artifact_written`, `plan_saved`, `action_applied`, `validation_started`, `validation_completed`, `run_completed`, `run_failed`.

#### Bounded file edits (first slice)
Forge supports **minimal bounded edit actions** on allowed repo paths (`examples/`, `src/`, `scripts/`, `tests/`) using deterministic text-matching rules:

- `insert_after_in_file`, `insert_before_in_file`, `replace_text_in_file`, `replace_block_in_file`
- Separators: literal ` @@FORGE@@ ` between payload parts; `\\n` escapes in payloads
- Default matching rule: **exactly one non-overlapping match required**, otherwise fail safely with no partial write
- `write_file` remains supported for bootstrapping and full-file replacement cases

#### Bounded edits — phase 1 extensions
Practical, code-oriented bounded editing (still stdlib-only, no AST):

- **Matching**: optional `occurrence=N`; default remains unique-or-fail
- **Line matching**: optional `line_match=true` for full-line equality matching
- **Lines**: `replace_lines_in_file` with inclusive 1-based `start_line` / `end_line`; invalid ranges fail safely
- **Newlines**: bounded-edit matching and writes normalize to `\n`
- **Diffs**: emit a unified diff with context lines and a `# forge-action:` header tied to the action
- **Safety**: zero matches, ambiguous matches, invalid ranges, or malformed payloads fail safely with no partial write

### Prompt-Driven Pivot Roadmap

#### Phase 1 — Todo State Model (persistent, single-active)
- **Goal**
  - Introduce durable workflow state where milestones/tasks can be represented as persistent todos with exactly one active todo at a time.
- **Implementation tasks**
  - Add `.system`-backed todo state storage with atomic save/load and corruption-safe defaults.
  - Define todo status transitions (`pending`, `active`, `completed`) with explicit invariants.
  - Add service operations to set active todo and complete todos explicitly (no implicit completion).
  - Provide minimal CLI commands for viewing, activating, and completing todos.
  - Reuse existing task metadata as source input when bootstrapping todos.
- **Expected artifacts/files**
  - `forge/prompt_todo_state.py` (new)
  - `forge/cli.py` (minimal command wiring)
  - `tests/test_prompt_todo_state.py` (new)

#### Phase 2 — Milestone/Task to Todo Expansion
- **Goal**
  - Materialize milestone-derived task breakdowns into persistent todo state that survives process restarts.
- **Implementation tasks**
  - Add deterministic projection from `.system/tasks/m<id>.json` into todo entries.
  - Preserve ordering/dependencies and emit one active candidate at a time.
  - Track source linkage (`milestone_id`, `task_id`) on each todo for traceability.
- **Expected artifacts/files**
  - `forge/task_service.py` (integration hooks)
  - `forge/prompt_todo_state.py` (source-sync functions)
  - `tests/test_task_to_todo_projection.py` (new)

#### Phase 3 — Prompt Compiler (Todo → Cursor Prompt)
- **Goal**
  - Compile the active todo into a stable prompt payload that can be handed to Cursor without mutating Forge state directly.
- **Implementation tasks**
  - Add deterministic prompt rendering from todo + context docs.
  - Include explicit acceptance criteria and bounded file/action hints.
  - Persist generated prompt artifacts for inspection/debugging.
- **Expected artifacts/files**
  - `forge/prompt_compiler.py` (new)
  - `.system/prompts/` artifacts (new directory usage)
  - `tests/test_prompt_compiler.py` (new)

#### Phase 4 — Execution Handshake + State Ownership
- **Goal**
  - Ensure Forge remains sole owner of workflow state transitions while coding agents only return outputs.
- **Implementation tasks**
  - Add explicit “start active todo” and “complete active todo” command flow.
  - Gate completion on explicit Forge command + optional validation checks.
  - Record state transition events in run history with clear provenance.
- **Expected artifacts/files**
  - `forge/cli.py` (state transition commands)
  - `forge/run_history.py` / event payload updates
  - `tests/test_prompt_workflow_transitions.py` (new)

#### Phase 5 — Validation + Repair Feedback for Prompt Workflow
- **Goal**
  - Keep existing deterministic safety model while adapting validation/repair to todo/prompt execution.
- **Implementation tasks**
  - Connect todo completion checks to existing validator and gate outputs.
  - Persist actionable failure feedback per todo for follow-up prompt generation.
  - Prevent no-op loops by detecting unchanged todo outcomes.
- **Expected artifacts/files**
  - `forge/validator.py` (todo-aware entrypoints)
  - `forge/task_feedback.py` (todo linkage)
  - `tests/test_todo_validation_feedback.py` (new)

#### Ordered build progression
1. Phase 1: durable single-active todo state primitives.
2. Phase 2: deterministic task → todo expansion.
3. Phase 3: prompt compiler for active todo.
4. Phase 4: explicit command-driven state transitions owned by Forge.
5. Phase 5: validation and repair feedback integrated with todo lifecycle.