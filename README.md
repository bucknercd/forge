# Forge

Forge is a spec-driven, prompt-first development engine for AI-assisted software engineering.
It turns ideas into structured architecture and milestone drafts, expands them into executable tasks, and prepares Cursor-ready prompts for active tasks while keeping humans in control of design and code review.

## What Forge Is

Forge is a workflow and state layer for AI-assisted development, not an autonomous coding agent.

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
  -> draft requirements/architecture/milestones
  -> human review/edit
  -> milestone -> task expansion
  -> optional human task edits
  -> active task selected
  -> Forge generates prompt for active task (in progress)
  -> human reviews code diff
  -> Forge marks task complete
```

### Implemented vs in progress

Implemented:
- spec and milestone generation flows
- task expansion and task-first execution model
- persistent prompt-task state with single active task
- explicit task activation/completion commands

In progress:
- first-class prompt compiler from active task to Cursor-ready prompt artifact
- tighter prompt workflow integration around completion/validation

## Key Concepts

- **Milestone**: planning chunk in `docs/milestones.md`.
- **Task**: executable unit derived from a milestone, stored in `.system/tasks/m<id>.json`.
- **Active task**: current prompt-workflow item; exactly one active task.
- **Prompt**: task-scoped, Cursor-ready prompt context for coding tools (compiler is in progress).
- **State ownership**: Forge updates workflow state; task completion is explicit and command-driven.

## Current Status

Forge is transitioning from execution-first orchestration to prompt-first workflow ownership.

- Task-first terminology and state model are in place.
- Prompt-task state is persisted under `.system/prompt_tasks.json`.
- Legacy `prompt-todo-*` aliases remain temporarily for compatibility.
- Apply/reviewed-plan flows still exist as advanced paths.

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

Generate draft artifacts:

```bash
forge build --idea "Internal admin service with role-based access and audit logs"
```

`build` is the preferred high-level entrypoint and currently wraps Forge's existing vertical-slice plumbing.

Then review/edit:
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/milestones.md`

## Task-First Workflow Commands

### Milestone -> task expansion

```bash
forge task-expand --milestone 1
forge task-list --milestone 1
forge task-show --milestone 1 --task 1
```

### Prompt-task state (primary pivot UX)

```bash
forge prompt-task-sync --milestone 1
forge prompt-task-list
forge prompt-task-activate --id 1
forge prompt-task-complete --id 1
```

Notes:
- Forge enforces one active prompt task at a time.
- Completion is explicit (`prompt-task-complete`), not implicit.
- Deprecated aliases (`prompt-todo-*`) still work temporarily.

## Legacy / Advanced Execution Paths

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
