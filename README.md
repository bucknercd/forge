# Forge

Forge is a **spec-driven, prompt-first workflow engine** for AI-assisted software engineering. It turns ideas into structured specs, milestones, and tasks; compiles **task-scoped, Cursor-ready prompts**; and **tracks explicit workflow state** (sync, start, complete) on disk. Implementation and tests happen **outside Forge**—in Cursor or by hand—while Forge remains the source of truth for planning artifacts and task lifecycle.

## What Forge Is

Forge is a workflow and state layer for AI-assisted development, not an autonomous coding agent. It does not replace your editor or assume autonomous code apply; it orchestrates **what to do next** and **when a task is officially started or done**.

It focuses on:
- explicit design artifacts in `docs/`
- deterministic task decomposition from milestones
- persistent, inspectable workflow state on disk
- task-scoped prompts and explicit completion

Forge owns workflow state transitions. Coding agents should not mutate Forge state files directly.

## Why Forge Exists

Most failures in AI-assisted coding are process failures:
- architecture intent gets lost after a few prompts
- tasks drift from milestone scope
- implementation edits lack clear plan context
- "done" is inferred implicitly instead of reviewed explicitly

Forge makes planning and progression explicit:
- ideas -> specs -> milestones -> tasks
- one active task at a time
- explicit, reviewable advancement

Forge is designed to make spec-driven development usable during real implementation, not just planning.

## What Makes Forge Different

Forge is not trying to fully automate software development.

It focuses on the missing middle layer:
- turning specs into executable workflow units
- keeping tasks aligned with architecture and milestones
- generating task-scoped prompts grounded in project context
- making progress explicit, stateful, and reviewable

## Core Workflow (Primary Direction)

```text
idea
  -> draft requirements / architecture / milestones (e.g. forge build)
  -> human review/edit
  -> milestone -> task expansion (.system/tasks/)
  -> optional human task edits
  -> prompt-task sync from milestone tasks
  -> Forge generates a task-scoped prompt artifact (prompt-generate)
  -> explicit start/handoff for implementation (prompt-task-start)
  -> human / Cursor implements and tests in the repo
  -> Forge records completion explicitly (prompt-task-complete)
```

Lifecycle transitions are **file-backed** and inspectable (e.g. `.system/prompt_workflow_history.jsonl`).

### Implemented vs in progress

Implemented:
- spec and milestone generation flows (`forge build --idea`, `--from-vision`, etc.)
- task expansion and milestone task files under `.system/tasks/`
- persistent prompt-task state with single active task (`prompt-task-sync`, `prompt-task-list`)
- explicit task activation, **start/handoff**, and completion (`prompt-task-activate`, `prompt-task-start`, `prompt-task-complete`)
- task-scoped prompt generation and artifacts (`prompt-generate` → `.system/prompts/`)
- append-only **workflow history** for main prompt-task lifecycle events

In progress:
- tighter integration between completion, validation, and follow-up prompts

## Key Concepts

- **Milestone**: planning chunk in `docs/milestones.md`.
- **Task**: executable unit derived from a milestone, stored in `.system/tasks/m<id>.json`.
- **Active task**: current prompt-workflow item; exactly one active task.
- **Prompt**: task-scoped, Cursor-ready prompt text persisted under `.system/prompts/` (`prompt-generate`).
- **State ownership**: Forge updates workflow state; task completion is explicit and command-driven.

## Current Status

Forge’s **primary** story is prompt-first: specs → tasks → prompts → explicit lifecycle. Optional **legacy** execution paths (reviewed plans, apply, gates) remain for teams that need them; they are not the default happy path.

- Prompt-task state: `.system/prompt_tasks.json`
- Prompt artifacts: `.system/prompts/`
- Workflow history: `.system/prompt_workflow_history.jsonl`
- Legacy `prompt-todo-*` CLI aliases remain temporarily for compatibility.

## Quick Start

### Install

```bash
git clone git@github.com:bucknercd/forge.git
cd forge
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Initialize a project

```bash
mkdir my-project && cd my-project
forge init
```

### Main happy path: build specs/milestones from an idea (LLM-backed)

Create `forge-policy.json`:

```json
{
  "planner": {
    "mode": "llm",
    "llm_client": "openai",
    "llm_model": "gpt-4o-mini"
  }
}
```

Set credentials:

```bash
export FORGE_OPENAI_API_KEY="sk-..."
# or
export OPENAI_API_KEY="sk-..."
```

Generate draft artifacts (LLM-backed; requires `forge-policy.json` and API credentials as above):

```bash
forge build --idea "Internal admin service with role-based access and audit logs"
# or, with vision in docs/vision.txt:
forge build --from-vision
```

`build` materializes specs and milestones and prepares tasks; on this branch it **stops before** reviewed-plan apply and autonomous code generation so you can edit artifacts and drive the prompt workflow explicitly.

Then review/edit:
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/milestones.md`

### Typical pivot workflow (commands in order)

```bash
forge init
forge build --idea "Your project idea"
# or: put vision in docs/vision.txt, then:
forge build --from-vision

forge task-expand --milestone 1
forge prompt-task-sync --milestone 1
forge prompt-task-list
forge prompt-generate --milestone 1 --task 1
forge prompt-task-start --id 1
# implement and test in Cursor or locally
forge prompt-task-complete --id 1
```

`init` is once per new project directory; `build` needs `forge-policy.json` and API credentials as above.

## Task-First Workflow Commands

### Milestone → tasks

```bash
forge task-expand --milestone 1
forge task-list --milestone 1
forge task-show --milestone 1 --task 1
```

### Prompt workflow (primary pivot UX)

```bash
forge prompt-task-sync --milestone 1
forge prompt-task-list
forge prompt-generate --milestone 1 --task 1
forge prompt-task-start --id 1
forge prompt-task-complete --id 1
```

Optional: `forge prompt-task-activate --id 1` sets the active task without the explicit “start/handoff” semantics of `prompt-task-start` (both update state; see workflow history for what ran).

Notes:
- Forge enforces one active prompt task at a time.
- **Start** (`prompt-task-start`) and **completion** (`prompt-task-complete`) are explicit Forge commands—not inferred from prompt generation or Cursor activity.
- Deprecated aliases (`prompt-todo-*`) still work temporarily.

## Legacy / Advanced Execution Paths

**Secondary.** Use these when you need heavier automation; day-to-day pivot work should stay on `build` + task + prompt commands above.

These flows are still supported but are not the primary product story:
- `task-preview`
- `task-apply-plan`
- `run-next`
- `workflow-guarded`
- `vertical-slice`

Use them when you need automation-heavy apply/gate orchestration. Prefer `build` + task-first prompt workflow for day-to-day development loops.

## Project Structure

- `docs/` - source-of-truth specs (`vision`, `requirements`, `architecture`, `milestones`, `decisions`)
- `forge/` - core engine and CLI
- `tests/` - Forge test suite
- `.system/tasks/` - milestone task breakdowns
- `.system/prompt_tasks.json` - prompt-task workflow state
- `.system/prompts/` - generated task-scoped prompt artifacts
- `.system/prompt_workflow_history.jsonl` - append-only prompt-task lifecycle events
- `.system/reviewed_plans/` - saved reviewed plans (legacy/advanced path)
- `.forge/runs/` - run event logs and artifacts
- `forge-policy.json` - planner and policy configuration

## Design Principles

- **Spec-first**: architecture and milestones are explicit files, not hidden prompts.
- **Task-first**: milestones are planning; tasks are execution granularity.
- **Deterministic where possible**: bounded actions, parseable rules, explicit state transitions.
- **Human-in-the-loop**: humans review architecture, task edits, and code diffs.
- **No silent completion**: Forge marks progress only through explicit commands.

## Contributing

Contributions are welcome, especially around:
- prompt quality and prompt-compiler behavior
- task expansion quality and workflow ergonomics
- validation and state-transition correctness

When reporting issues, include:
- commands run
- relevant CLI output
- relevant artifacts from `.forge/runs/` or `.system/`

When proposing changes, favor work that:
- preserves deterministic behavior where possible
- preserves explicit state transitions
- avoids hidden workflow changes

If your change alters workflow semantics, describe migration and operator impact clearly in the PR.

## License

MIT
