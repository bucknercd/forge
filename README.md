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
  -> inspect with forge status / milestone-list / milestone-show
  -> milestone -> task expansion (forge task-expand → .system/tasks/)
  -> optional human task edits
  -> link workflow state and start a task (see Advanced: prompt-task-sync / prompt-task-start)
  -> Forge generates a task-scoped prompt artifact (forge prompt-generate)
  -> human / Cursor implements and tests in the repo
  -> Forge records completion explicitly (forge task-complete, or prompt-task-complete --id)
```

Lifecycle transitions are **file-backed** and inspectable (e.g. `.system/prompt_workflow_history.jsonl`).

### Implemented vs in progress

Implemented:
- spec and milestone generation flows (`forge build --idea`, `--from-vision`, etc.)
- **user-facing workflow UX**: `forge doctor`, `forge status`, `forge milestone-list`, `forge milestone-show`, `forge task-complete`
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

Forge is designed to be **easy to start**, **easy to inspect** (`forge status`), and **easy to pick up the next day**—the CLI tells you the suggested next step when it can.

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

### First-run workflow (recommended)

```bash
forge init
forge doctor
forge build --from-vision
forge status
forge milestone-list
forge milestone-show --milestone 1
```

- **`forge doctor`** checks project layout, `forge-policy.json`, and (when relevant) LLM environment variables—use it after `init` or when something looks wrong.
- **`forge status`** summarizes where you are: milestone focus, active task (if any), overall task progress, and a **suggested next command** when possible.

For **`forge build --from-vision`**, put your product vision in `docs/vision.txt` first. With **`forge build --idea "..."`**, you can skip a separate vision file. Both paths need LLM policy and credentials (below).

### LLM policy and credentials (for `forge build`)

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

Then:

```bash
forge build --idea "Internal admin service with role-based access and audit logs"
# or, with vision in docs/vision.txt:
forge build --from-vision
```

`build` materializes specs and milestones; on this branch it **stops before** reviewed-plan apply and autonomous code generation so you can edit artifacts and drive the workflow explicitly.

Review/edit:
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/milestones.md`

### First milestone: expand tasks and inspect

```bash
forge task-expand --milestone 1
forge task-list --milestone 1
forge status
```

The first time you work tasks for a milestone, `forge status` will usually point you at **linking** expanded tasks into workflow state and **starting** one task (see **Advanced / compatibility: prompt-task layer**). After that, day-to-day work is mostly **`status` → implement in Cursor → `task-complete`**.

## Day-to-day workflow

Normal loop:

> **`status`** → inspect milestones/tasks → **expand** when needed → work in **Cursor** (or locally) → **`task-complete`** → repeat.

Example session:

```bash
forge status
forge task-complete
forge milestone-list
forge task-expand --milestone 3
forge task-list --milestone 3
forge status
```

When you need a compiled prompt for the editor:

```bash
forge prompt-generate --milestone 3 --task 1
```

If **`forge task-complete`** reports **no active task**, run **`forge status`** and follow the hint—typically you need **`forge prompt-task-sync`** and **`forge prompt-task-start`** once per milestone (documented under Advanced). To complete a specific workflow row without using the active task, use **`forge prompt-task-complete --id <id>`**.

## Primary commands (day-to-day)

| Command | Purpose |
|--------|---------|
| `forge doctor` | Validate layout, policy, and environment after setup or when debugging. |
| `forge build` | Generate/update vision, requirements, architecture, milestones (LLM or demo paths). |
| `forge status` | **Where am I?** Milestone focus, active task, progress, suggested next step. |
| `forge milestone-list` | All milestones with **workflow** status (derived from tasks + prompt-task state). |
| `forge milestone-show --milestone N` | One milestone: fields, workflow status, task table. |
| `forge task-expand --milestone N` | Create/refresh `.system/tasks/` from `docs/milestones.md`. |
| `forge task-list --milestone N` | List expanded tasks (with workflow link when synced). |
| `forge task-show --milestone N --task K` | Full detail for one expanded task. |
| `forge task-complete` | Complete the **active** workflow task (friendly entrypoint). |
| `forge prompt-generate --milestone N --task K` | Write a task-scoped prompt under `.system/prompts/`. |

See also **`forge logs`** for recent run history under `.forge/runs/`.

Use **`forge help`** for a short curated command list; **`forge help all`** lists legacy and automation commands.

## Advanced / compatibility: prompt-task layer

These commands operate on the same on-disk workflow state as `task-complete`; they are **lower-level** and useful for automation or when you need an explicit ID.

| Command | Purpose |
|--------|---------|
| `forge prompt-task-sync --milestone N` | Copy expanded tasks into `.system/prompt_tasks.json`. |
| `forge prompt-task-start --id ID` | Hand off / start a task (logs workflow history). |
| `forge prompt-task-complete --id ID` | Complete a specific prompt-task id. |
| `forge prompt-task-list` | Raw list of prompt-task rows and active id. |
| `forge prompt-task-activate --id ID` | Set active task without the same handoff semantics as `prompt-task-start`. |

Deprecated aliases (`prompt-todo-*`) still work temporarily.

Forge enforces **one active task** at a time. **Start** and **completion** are never inferred from edits in the repo or from running `prompt-generate` alone.

## Legacy / advanced execution paths

**Secondary.** Heavier automation and older orchestration—not the default pivot loop.

- `task-preview`
- `task-apply-plan`
- `run-next`
- `workflow-guarded`
- `vertical-slice`

Use these when you need apply/gate automation. Prefer **`build` + `status` + milestone/task commands + `task-complete`** for everyday work.

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
