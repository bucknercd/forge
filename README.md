# Forge

Forge is a spec-driven CLI for turning product intent into reviewed plans, code changes, and validation gates with explicit control.

## Design Philosophy

Forge originally explored fully autonomous code generation, but this approach quickly ran into reliability issues.

The current direction (see pivot branch) treats the LLM as a non-deterministic planner rather than an executor. All generated plans are reviewed, validated, and applied through deterministic execution paths.

The goal is not full automation, but making spec-driven development more structured, auditable, and reliable when working with LLMs.

## Why Forge Exists

Modern LLM coding flows have a reliability gap:

- generated projects can look correct and still miss core logic
- tests can pass while behavior is still shallow
- autonomous edits can drift away from requirements

Forge exists to make this visible and enforceable. It is not "let the LLM go wild." It is a control and correctness layer around planning and apply.

## What Forge Does

Forge turns an idea or vision into executable engineering workflow:

- `vision` -> `requirements` -> `architecture` -> `milestones`
- task expansion from milestones
- reviewed plan generation per task
- deterministic apply
- post-apply validation and test gates

Core artifacts are plain files in your repo:

- `docs/vision.txt`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/milestones.md`
- `.system/tasks/m<id>.json`
- `.system/reviewed_plans/`

## Core Principles / Design Goals

- **Spec-first**: `docs/` stays the source of truth.
- **Task-scoped execution**: milestones are roadmap; tasks are executable units.
- **Reviewed plans**: apply happens from saved plans, not hidden model state.
- **Validation gates**: require explicit checks after apply.
- **Deterministic execution path**: given a reviewed plan, behavior is reproducible.
- **Anti-shallow safeguards**: classify and fail structural stubs that miss required behavior.

## Current Status

Forge is promising and actively evolving, but not fully end-to-end reliable for all project shapes yet.

- core loop works for many scenarios
- robustness and planner hardening are in progress
- some flows still need iterative fixes and tighter guardrails
- **Go (and other non-Python stacks):** LLM flows can **produce working code** (e.g. a server you `go run`), but **automated post-apply test gates for those stacks are not solid yet**—that’s a known gap, not something you misconfigured

This repository should be read as an in-progress systems project focused on correctness, control, and reproducibility.

## Simple Pipeline Overview

```text
idea / vision
  -> docs (vision, requirements, architecture, milestones)
  -> tasks (.system/tasks/m<id>.json)
  -> reviewed plan (m<id>-t<task>-<hash>)
  -> apply actions
  -> validation + optional test command
  -> repair loop when classification says "not done"
```

## Quick Start

### 1) Install

```bash
git clone git@github.com:bucknercd/forge.git
cd forge
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2) Run demo vertical slice (no API key required)

```bash
mkdir forge-demo && cd forge-demo
forge init
forge vertical-slice --demo
```

### 3) Inspect and continue

```bash
forge status
forge task-preview 1 --task 1 --save-plan
forge task-apply-plan <plan_id>
forge run-next
```

### Fresh Start / Reuse Repo

If you want to generate a new app idea in the same directory, clear derived execution state first:

```bash
forge reset --generated-only
# or
forge vertical-slice --fresh --idea "New app idea..."
# or
forge build --fresh --idea "New app idea..."
```

## Using an LLM

Forge supports OpenAI-backed planning/docs generation via policy.

Create `forge-policy.json` in project root:

```json
{
  "planner": {
    "mode": "llm",
    "llm_client": "openai",
    "llm_model": "gpt-4o"
  }
}
```

Set credentials in environment:

```bash
export FORGE_OPENAI_API_KEY="sk-..."
# or export OPENAI_API_KEY="sk-..."
```

Run with your own intent:

```bash
forge vertical-slice --idea "Small FastAPI service with a /health endpoint"
```

**Try a real greenfield app:** `forge build` is the same engine as `vertical-slice`. With policy + API key, one command can scaffold a whole slice (docs, tasks, plan, apply, gates). Example — **Go HTTP server on port 1234** (install **[Go](https://go.dev/dl/)** so you can run the generated code yourself):

```bash
mkdir gotest && cd gotest
forge init

cat > forge-policy.json <<'EOF'
{
  "planner": {
    "mode": "llm",
    "llm_client": "openai",
    "llm_model": "gpt-4o"
  },
  "task_execution": {
    "max_repair_attempts": 3
  }
}
EOF

export FORGE_OPENAI_API_KEY="sk-..."   # or OPENAI_API_KEY

forge build --idea 'build a Go HTTP server that serves hello world in HTML with headers and colors on / on localhost port 1234'
```

**What to expect:** Forge can **generate Go that builds and runs** (e.g. `go run ./src/server.go` or whatever paths the plan wrote—check **`docs/milestones.md`** and the apply log). **Automated post-apply test gates for Go are not a solved story yet**—they’re still Python- and pytest-shaped in practice, so the **end-to-end command may report failure even when your server is fine**. That’s a **known gap**; verify the app with **`go run …`** / **`go test ./...`** yourself. You can experiment with **`--gate-test-cmd 'go test ./...'`** or **`true`**; see **`.forge/runs/<run_id>/`** for gate output.

**Running Forge’s own tests** (this **Forge** repo, not your Go app): **`pip install -e .`**, then **`pytest`** from the forge checkout.

Vision-file flow (recommended for longer input):

```bash
forge vertical-slice --from-vision
# or
forge vertical-slice --vision-file ./docs/vision.txt
```

## Important Concepts

- **Milestones vs tasks**: milestones define roadmap intent; tasks are what planner/apply execute.
- **Reviewed plans**: task-scoped plans are saved under `.system/reviewed_plans/`.
- **Apply step**: runs canonical Forge actions (`write_file`, bounded edits, section edits, etc.).
- **Validation gates**: Forge Validation rules plus optional repo test command.
- **Vertical slice flow**: materialize docs, ensure tasks, save reviewed plan, apply, run gates.

## Why This Project Is Interesting

Forge is built with the same spec-driven / AI-assisted methodology it promotes.

That makes this repo both:

- a practical CLI for controlled LLM-assisted execution
- a testbed for spec-driven development itself

If you care about DevTools, platform engineering, AI infra safety, or reproducible automation, Forge is a concrete systems problem: how to keep model-assisted development useful without giving up control.

## Common Commands

End-to-end:

```bash
forge vertical-slice --demo
forge vertical-slice --idea "Your short idea"
forge build --idea "Go HTTP server on :1234 with styled HTML on /"   # alias; needs policy + API key
forge vertical-slice --from-vision
forge vertical-slice --vision-file ./notes/vision.txt
```

Task-first workflow:

```bash
forge task-expand --milestone 1
forge task-list --milestone 1
forge task-show --milestone 1 --task 1
forge task-preview 1 --task 1
forge task-preview 1 --task 1 --save-plan
forge task-apply-plan m1-t1-<hash12>
forge run-next
```

Guarded workflow:

```bash
forge workflow-guarded --milestone-id 1 --synthesize --apply-plan --gate-test-cmd "pytest"
```
## Contributing / Feedback

Feedback, issues, and discussion are highly encouraged.

If you find a failure mode, please open an issue with:
- command used
- relevant run output
- artifacts from `.forge/runs/` and `.system/results/`

PRs are not the primary contribution path right now.

If you want to contribute code, please open an issue first to discuss the change. This helps keep the system aligned with its design goals (determinism, reproducibility, and controlled execution).

## License

MIT
# Forge

Forge is a **spec-driven CLI** that turns **ideas into milestones into code**—**the coherent, validated code that working systems are built from**.

Forge is a **two-layer system**:

1. **Milestones (roadmap)** — live in **`docs/milestones.md`**: intent, scope, **Forge Actions**, and **Forge Validation** for the whole slice. They define *what* to achieve, not the step you execute next in the engine.
2. **Tasks (execution units)** — live in **`.system/tasks/m<id>.json`**: small, ordered, reviewable steps derived from a milestone. **Only tasks are executed:** preview, reviewed plans, and apply always go through a **task id** (`m<id>-t<task>-<hash>` plans).

Between those layers, **task expansion** turns milestone Forge Actions into 2–6 tasks (deterministic split) or a **single compatibility task** when splitting is not possible. Expansion runs **automatically** the first time you preview, save a plan, run **`run-next`**, **`vertical-slice`**, or **`workflow-guarded`** (you’ll see a notice on **stderr** if tasks were missing). You can still run **`forge task-expand`** manually or with **`--force`** to refresh JSON from the current milestone text.

You start with intent—a short phrase, a vision file, or the demo. Forge (optionally with an LLM) materializes **`docs/`** specs and milestones. A **planner** builds a plan for the **selected task**; Forge **applies** it under **gates**. The loop repeats until the system **holds up under checks**.

**In one sentence:** *idea → vision & specs → milestones → **tasks** → reviewed plan → apply → validation → a working system.*

**CLI:** Milestones are **roadmap-only** (no first-class “execute this milestone” command). Execution is **task-first** (`task-preview`, `task-apply-plan`, `run-next`, `vertical-slice`, `workflow-guarded`, …). For a transition period, older names (`milestone-preview`, `milestone-apply-plan`, `execute-next`, plus deprecated `milestone-execute` / `milestone-retry`) still work: Forge prints a **stderr** deprecation notice and routes to the same task behavior.

### Simple CLI shortcuts (orchestration layer)

Higher-level commands wrap the same engine; granular subcommands stay available:

| Command | Role |
|--------|------|
| **`forge start`** | `init` if needed, then print a short guided workflow. |
| **`forge build`** | **`vertical-slice`**: default **demo** bundle; use **`--idea`**, **`--vision-file`**, or **`--from-vision`** for LLM (with **`--no-demo`** when forcing non-demo). |
| **`forge fix`** | Alias for **`run-next`** (next task / repair loop). |
| **`forge status`** | Repo readiness + milestone state + **next milestone / task** hint. |
| **`forge doctor`** | Layout, **`forge-policy.json`**, planner mode, **`OPENAI_API_KEY`** hint. |
| **`forge logs`** | Recent **`run-history`** + newest **`.forge/runs/`** dirs. |

**Repair loop:** failures are **classified** (e.g. `syntax_fix`, `behavior_fix`, `format_fix`, `no_op_repair`) into structured metadata under **`.system/task_feedback/`**; the next LLM planner prompt gets a **mode-specific** instruction block (not a single generic retry paragraph). **No-op:** if the **previous** failure was **apply** and the new reviewed **plan hash** is unchanged, Forge stops early and asks for human review (gate-only failures may still re-apply the same plan so flaky or mocked gates can progress).

---

## The pipeline

```text
Your idea (CLI text, vision file, or demo)
        │
        ▼
docs/   vision.txt · requirements.md · architecture.md · milestones.md
        │
        ▼
Milestones   (roadmap: objectives + Forge Actions + Forge Validation)
        │
        ▼
Task expansion (automatic or `forge task-expand`) → .system/tasks/m<id>.json
        │
        ▼
Task selection (--task <n>, or next pending task for run-next / vertical-slice)
        │
        ▼
Plan         (reviewed, saved under .system/reviewed_plans/, id m<id>-t<task>-<hash>)
        │
        ▼
Apply        (write_file, bounded edits, append_section, …)
        │
        ▼
Gates        (Forge Validation + optional repo test command)
        │
        ▼
Working system — code + updated specs, validated
```

**`forge vertical-slice`** materializes docs, **ensures tasks** for milestone **1**, saves a reviewed plan for the **next pending task**, applies it, and runs gates. **`forge task-preview`** without **`--task`** lists tasks and asks you to pick one; with **`--task`** it previews that execution unit. **`forge run-next`** runs the **next roadmap milestone’s next pending task** (multi-task milestones may need several **`run-next`** runs). See **[Milestones vs tasks](#milestones-vs-tasks-two-layer-planning)** and **[Why tasks are required](#why-tasks-are-required)**.

### Artifact tests & bounded repair (unified execution)

These commands share the **same task-scoped repair orchestration** (via `Executor.run_task_apply_with_repair_loop`):

- **`forge run-next`**
- **`forge task-apply-plan <plan_id>`** (first attempt applies **that** reviewed plan; later attempts save new `m<id>-t<task>-<hash>` plans for the same task)
- **`forge vertical-slice`** (apply stage)
- **`forge workflow-guarded`** when it reaches the apply step

The loop:

1. **Save** a reviewed plan for the task when needed (`run-next` and retries always save; **task-apply-plan / vertical-slice / workflow** reuse the plan id from the prior preview/save step on the **first** attempt only).
2. **Apply** implementation actions (post-apply gates are **deferred** and run in the batch below).
3. **Generate** (when enabled) a **targeted pytest file** under `tests/forge_generated/` from the task’s Forge Validation lines and `write_file` targets—**skipped with an explicit reason** when no heuristic applies.
4. Run **Forge milestone validation** when enabled (`run-next` always runs it; **`task-apply-plan`** / workflow / vertical-slice follow **`reviewed_plan_apply.run_validation_gate`** and CLI `--gate-validate` / `--no-gate-validate`), then **pytest on the generated file** (if any), then optional **`reviewed_plan_apply.test_command`**.
5. **On success** → mark the task complete. **On failure** → persist structured feedback under **`.system/task_feedback/`** and **re-plan the same task**. **Deterministic** planner → **one** attempt; **LLM** mode uses feedback until **`task_execution.max_repair_attempts`** (default **3**, cap **20**). **`run-next`** still updates roadmap **retry/failed** state on exhaustion; **task-apply-plan** / **vertical-slice** / **workflow** do not move the milestone state machine on failure (the task simply stays incomplete).

Configure in **`forge-policy.json`**:

```json
{
  "task_execution": {
    "artifact_test_generation": true,
    "max_repair_attempts": 3
  }
}
```

---

## Quick Start (vertical slice)

Reproduce the full loop **vision → requirements/architecture → milestones → plan → apply → validation** without writing policy by hand using the built-in demo:

**LLM vs demo:** `--demo` needs **no API key** and no `forge-policy.json`. Anything that generates docs from your idea (`--idea`, `--from-vision`, `--vision-file`) needs an **LLM client** in policy plus credentials in the environment—see **[Using an LLM (OpenAI)](#using-an-llm-openai)** below.

```bash
mkdir forge-demo && cd forge-demo
forge init
forge vertical-slice --demo
```

**What happens**

1. Writes `docs/vision.txt`, `docs/requirements.md`, `docs/architecture.md`, and `docs/milestones.md` with a tiny **CLI todo** example.
2. **Expands tasks** for milestone 1 (if needed), then builds an execution plan for the **next pending task** from `.system/tasks/m1.json` (deterministic planner by default), including `write_file examples/todo_cli.py | …` when that task’s actions say so.
3. Saves a **task-scoped** reviewed plan under `.system/reviewed_plans/` (plan id **`m1-t<task>-<hash>`**).
4. Applies the plan (creates `examples/todo_cli.py`, appends to requirements, updates milestone markers in `docs/milestones.md` when the task includes them).
5. Runs **Forge Validation** (`path_file_contains`, `file_contains`) and the repo test gate **`python examples/todo_cli.py`** (demo default).

**Progress output** is driven by a small **event bus** (not ad hoc `print` / logging): you’ll see phases (materialize, plan, apply, validation), each applied action (especially file paths), and gate results. It ends with **`Overall: success`** or **`Overall: failure`**.

Each run also writes an inspectable log under **`.forge/runs/<run_id>/`**:

- `run_meta.json` — command, flags, milestone id  
- `events.jsonl` — one JSON object per line (`type`, `ts`, `run_id`, `data`)

Use **`--verbose`** for a bit more detail (e.g. phase summaries). Use **`--json`** for a single machine-readable blob (includes the same `events` list plus `run_log_dir` / `events_path`).

Then try:

```bash
python examples/todo_cli.py --add "buy milk"
```

which should print a line like `Added todo: buy milk`.

**JSON trace**

```bash
forge vertical-slice --demo --json
```

### Using an LLM (OpenAI)

Forge’s supported remote provider today is **OpenAI** (`planner.llm_client`: `"openai"`). Other `llm_client` values may be added later; for now this is what you use for real `--idea` / vision-file flows. **`stub`** is for offline tests and does not return usable vertical-slice JSON for real projects.

1. **Create `forge-policy.json`** in your project root (same directory you run `forge` from). `forge init` does **not** create this file—you add it when you want LLM features.

   Minimal example for vertical slice and LLM-backed planning:

   ```json
   {
     "planner": {
       "mode": "llm",
       "llm_client": "openai",
       "llm_model": "gpt-4o-mini"
     }
   }
   ```

   - **`llm_model`** is optional; if omitted, Forge defaults to **`gpt-4o-mini`**.
   - **Do not put API keys in this file.** Keys belong only in the environment.

2. **Set your OpenAI API key** in the shell (or your IDE/CI secrets) before running Forge:

   ```bash
   export FORGE_OPENAI_API_KEY="sk-..."   # Forge-specific (recommended)
   # or
   export OPENAI_API_KEY="sk-..."
   ```

   Optional: **`FORGE_OPENAI_BASE_URL`** — override the API base URL (defaults to OpenAI’s endpoint; useful for compatible proxies).

3. **Run vertical slice** with an idea:

   ```bash
   forge vertical-slice --idea "Small FastAPI service with a /health route"
   ```

   Use `--gate-test-cmd 'pytest -q'` (or similar) to match whatever the LLM milestone expects.

4. **Optional copy-paste: Go HTTP server (`forge build`)** — same as `vertical-slice`, different subcommand. If you pass `--idea`, you do **not** need `--no-demo` (the demo is skipped automatically).

   ```bash
   mkdir gotest && cd gotest
   forge init

   cat > forge-policy.json <<'EOF'
   {
     "planner": {
       "mode": "llm",
       "llm_client": "openai",
       "llm_model": "gpt-4o"
     },
     "task_execution": {
       "max_repair_attempts": 3
     }
   }
   EOF

   export FORGE_OPENAI_API_KEY="sk-..."   # or OPENAI_API_KEY

   forge build --idea 'build a Go HTTP server that serves hello world in HTML with headers and colors on / on localhost port 1234'
   ```

   **Prerequisites:** Go on `PATH`. The LLM may place `main` under `src/`, `cmd/`, etc.—follow **`docs/milestones.md`** or the apply output. If the code applied cleanly, try **`http://127.0.0.1:1234/`** after **`go run …`** (path depends on the plan).

   **Known limitation (we’re aware):** **Generated Go can work**; **integrated automated tests / post-apply gates for Go are not reliable yet** (milestones and defaults still skew toward Python/pytest). So **`forge build` may finish apply with good source tree but still fail the overall run** on gates—that’s expected until this improves. **Validate by hand** with **`go run …`** and **`go test ./...`**; optionally override **`--gate-test-cmd`**. **Forge’s own unit tests** are Python-only: from **this** repository, **`pip install -e .`** then **`pytest`**.

**Voice → file → Forge (long-form vision)**

For longer ideas, dictation, or iteration in an editor, put the vision in a file instead of the CLI. Forge uses that text as the **source of truth** for `docs/vision.txt` and asks the LLM only for requirements, architecture, and milestones (vision is **not** regenerated).

1. Paste or write your vision into `docs/vision.txt` (after `forge init`).
2. Run:

```bash
forge vertical-slice --from-vision
```

Or use any path:

```bash
forge vertical-slice --vision-file path/to/my-vision.txt
```

**Precedence** if you pass more than one input: `--idea` wins, then `--vision-file`, then `--from-vision`. Do not combine `--demo` with those flags. Forge fails with a clear message if the vision file is missing or empty (whitespace-only counts as empty).

| Mode | What you provide | What Forge does with vision |
|------|------------------|-----------------------------|
| `--demo` | Nothing (built-in todo example) | Writes all docs deterministically; no LLM |
| `--idea "…"` | Short text on the CLI | LLM generates vision + requirements + architecture + milestones |
| `--vision-file` / `--from-vision` | Long text in a file | **Your file is the vision**; LLM generates only requirements, architecture, milestones |

All non-demo modes need **`planner.llm_client`** set in `forge-policy.json` (typically **`openai`** plus an API key in the environment, as above—or **`stub`** only for automated tests).

**Bounded file writes**

- Forge action: `write_file <rel_path> | <body>` (use `\n` in the body for newlines).  
  Allowed prefixes: `examples/`, `src/`, `scripts/`, `tests/`.
- Validation: `path_file_contains <rel_path> <substring>` (substring is the rest of the line). Wrap the substring in `'...'` or `"..."` when it would be token-split by whitespace; outer quotes are stripped and are **not** part of the search text.

**Bounded edits vs `write_file`**

Use **`write_file`** to create or replace a whole file (good for first-cut scaffolding). To **evolve** existing code under `examples/`, `src/`, `scripts/`, or `tests/`, prefer bounded actions: smaller diffs, clearer review, safe failure when a match is not unique.

Payloads use **` @@FORGE@@ `** (spaces matter) between parts; use `\n` in parts as usual. Files are normalized to `\n` before matching.

```text
# Default: substring must match exactly once (non-overlapping). Otherwise apply fails.
insert_after_in_file examples/app.py | return 0 @@FORGE@@ \n    log("ok")\n

# Match a full line (after newline normalization); still requires uniqueness unless you opt out:
replace_text_in_file examples/app.py |     return None @@FORGE@@     return 42 | line_match=true

# Nth match when multiple exist (must_be_unique=false):
insert_before_in_file examples/t.py | import os @@FORGE@@ from pathlib import Path\n | must_be_unique=false occurrence=2

# Line-range patch (1-based inclusive lines); fails if range is out of bounds:
replace_lines_in_file examples/app.py | 12 @@FORGE@@ 18 @@FORGE@@ def refactored():\n    return True\n

# Block replace (start marker unique by default; end is first substring after start region):
replace_block_in_file examples/config.yaml | --- @@FORGE@@ ... @@FORGE@@ ---\nnew: block\n
```

Optional trailing segment: ` | occurrence=2 must_be_unique=false line_match=true` (space-separated `key=value`; not used with `replace_lines_in_file`).

**Preview / diffs**: unified diffs use **3 lines of context** and a `# forge-action: …` header so you can see which action produced each change.

**Safety**: **0** matches, **out-of-range** lines, or (with default `must_be_unique=true`) **multiple** matches → **fail** with no partial write. Dry-run/preview still shows the diff when the action would succeed.

---

## Concepts

**Specs (`docs/`)** are the source of truth: vision, requirements, architecture, decisions, and milestones. You can author them by hand, or let **`forge vertical-slice`** (with LLM) populate them from an idea or a vision file.

**Milestones** live in `docs/milestones.md` as Markdown sections. Each milestone has narrative fields (objective, scope, validation), optional **`- **Summary**:`** for a short high-level blurb, plus machine-readable lines:

- **Forge Actions** — declarative edits (`write_file`, `append_section`, bounded patches, …) that the executor applies in order.
- **Forge Validation** — checks (`path_file_contains`, `file_contains`, …) that must pass after apply.

The **planner** (deterministic or LLM-backed, per `forge-policy.json`) always reads a **milestone-shaped execution unit** produced from a **task** under `.system/tasks/m<id>.json` via `task_to_execution_milestone(...)` (same roadmap **milestone id** for `mark_milestone_completed` and docs). **New** reviewed plans are always **task-scoped** (`m<id>-t<task>-<hash>`). **Legacy** reviewed plans saved before task enforcement may omit `task_id`; **`task-apply-plan`** can still apply them using the milestone definition from `docs/milestones.md` until you re-save from a task.

**Execution** is deterministic: Forge does what the saved plan says, then runs **gates**. Failure stops the run with a clear reason; you fix specs, milestones, or code and try again—there is no hidden auto-retry in the engine itself (orchestration like `workflow-guarded` can combine multiple steps).

### Milestones vs tasks (two-layer planning)

**Milestones** live in `docs/milestones.md`: roadmap intent, Forge Actions, and Forge Validation for the whole slice. They are **not** passed directly to the planner/executor.

**Tasks** are the **only** execution units: concrete, ordered steps in **`.system/tasks/m<milestone_id>.json`**. Preview, **`--save-plan`**, **`run-next`**, **`vertical-slice`**, and **`workflow-guarded`** all resolve a **task id** (explicit **`--task`**, or the **next pending task** for automated flows). Roadmap **`mark_milestone_completed`** still refers to the **milestone id** in `docs/milestones.md`.

- **Auto-expansion** — If tasks are missing, Forge runs the same logic as **`forge task-expand --milestone <id>`** (notices on **stderr**). If a multi-task split is invalid, Forge uses a **single compatibility task** that mirrors the whole milestone and logs a **compatibility-mode** warning (never a silent raw-milestone execute).
- **`forge task-expand --milestone <id>`** — (Re)materialize tasks: **2–6** via deterministic split when possible; optional **LLM JSON** expansion when a non-stub OpenAI client is configured; else **compatibility** fallback. Use **`--force`** to replace existing JSON from the current milestone text.
- **`forge task-list` / `forge task-show`** — Inspect tasks (**`--json`** supported).
- **`forge task-preview <id>`** — Without **`--task`**, Forge prints the task list and tells you to pass **`--task <n>`**. With **`--task`**, previews that task. **`--save-plan`** with an explicit milestone id **requires** **`--task`**.
- **`forge task-preview` (no id)** — Previews the **next eligible milestone’s next pending task** (deterministic planner only for the no-id save path, as before).
- **`forge task-apply-plan <plan_id>`** — Apply uses the **`task_id`** stored in the reviewed plan when present.

**Note:** Post-apply **milestone_validation** still consults **`docs/milestones.md`** for that milestone id. Split tasks often **duplicate** milestone Forge Validation on each slice that has Forge Actions; full milestone gates may only pass after the **last** task (or use **`--no-gate-validate`** on intermediate applies if your policy allows).

### Why tasks are required

- **Scope control** — A whole milestone is usually too large for one review/apply; tasks force a bounded slice of Forge Actions.
- **Determinism & traceability** — Reviewed plan ids include **`task_id`** and a hash of `.system/tasks/m<id>.json`, so execution maps cleanly to a stored breakdown.
- **Ordering** — `depends_on` encodes safe sequencing (e.g. work before `mark_milestone_completed`).
- **Policy** — Forge enforces decomposition before execution so operators pick (or flow through) an explicit unit of work, rather than an ambiguous “whole milestone” apply.

---

## Installation

```bash
git clone git@github.com:bucknercd/forge.git
cd forge
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Common commands

**End-to-end (one command)**

```bash
forge vertical-slice --demo
forge vertical-slice --idea "Your short idea"
forge build --idea "Go HTTP server on :1234; styled HTML on /"   # same as vertical-slice + --idea
forge vertical-slice --from-vision          # uses docs/vision.txt
forge vertical-slice --vision-file ./notes/vision.txt
```

**Incremental (existing repo)**

```bash
forge status
forge milestone-list
forge milestone-next
forge task-preview 1                  # lists tasks; add --task <n> to preview
forge task-preview 1 --task 1 --save-plan   # persist task-scoped reviewed plan
forge task-apply-plan <plan_id>       # apply saved plan + gates
forge run-next                         # next roadmap milestone’s next pending task
```

**Tasks (under each milestone)**

Tasks are **created automatically** when needed; use **`forge task-expand`** to refresh or inspect. Walk tasks **in order** when they have **`depends_on`**.

```bash
forge task-expand --milestone 1            # 2–6 tasks by default (deterministic split)
forge task-expand --milestone 1 --force      # regenerate task JSON from milestones.md
forge task-list --milestone 1              # id, title, objective, dependencies
forge task-show --milestone 1 --task 2       # any task id from the list
forge task-preview 1 --task 2
forge task-preview 1 --task 2 --save-plan
forge task-apply-plan m1-t2-<hash12>  # plan id matches saved --task
```

**Milestone generation (LLM)** — same as `milestone-synthesize`:

```bash
forge milestone-generate --count 3
```

---

## Enable LLM

Use the same **`forge-policy.json`** and **OpenAI environment variables** as in [Quick Start → Using an LLM (OpenAI)](#using-an-llm-openai). Then you can use LLM mode outside vertical slice, for example:

```bash
forge task-preview 1 --task 1 --planner llm
forge milestone-synthesize
```

With a **non-stub OpenAI** client in policy, **`forge task-expand`** may also try an **optional LLM** pass to propose 2–6 tasks; output must pass the same validation as the deterministic splitter, or Forge keeps deterministic / compatibility results.

---

## Guarded Workflow

```bash
forge workflow-guarded \
  --milestone-id 1 \
  --synthesize \
  --apply-plan \
  --gate-test-cmd "pytest"
```

Chains optional **milestone synthesis** (LLM), **task expansion** (if needed), **preview/save plan** for the **next pending task** on the chosen milestone, and **apply with gates**. Use `--accept-synthesized` / `--synthesis-id` when you want synthesized proposals merged into `docs/milestones.md` (see `forge workflow-guarded --help`).

---

## Validation Gates

After apply, Forge can run:

* **Forge Validation** rules — **new** reviewed plans are built from a **task** (often with Forge Validation lines copied from the milestone). **Milestone-level** post-apply checks still consult **`docs/milestones.md`** for that id. **Legacy** plans without **`task_id`** still apply using the milestone definition in docs until re-saved.
* **Repository test command** (e.g. `pytest`), with timeout and captured output limits

Example (apply an existing reviewed plan by id):

```bash
forge task-apply-plan \
  <plan_id> \
  --gate-test-cmd "pytest" \
  --gate-test-timeout-seconds 60
```

---

## Project Layout

* `docs/` — specs (source of truth): vision, requirements, architecture, decisions, milestones
* `forge/` — engine (CLI, planner, executor, validation)
* `tests/` — Forge’s own test suite (your app tests live where your milestones put them)
* `.system/` — reviewed plans (**`reviewed_plans/`**), **milestone task breakdowns (`tasks/m<id>.json`)**, run history, etc.
* `.forge/` — per-run logs (`runs/<run_id>/events.jsonl`, `run_meta.json`)
* `forge-policy.json` — planner mode, LLM client, apply/gate defaults (repo root)

---

## Design principles

* **Spec-driven** — `docs/` define intent and executable milestones
* **LLM-assisted** — optional for drafting specs, milestones, and LLM-backed plans; `--demo` and deterministic planners stay predictable
* **Deterministic execution** — given a saved plan, apply behavior is reproducible
* **Validation around apply** — Forge Validation + optional test command
* **Explicit state** — reviewed plans, **per-milestone task JSON** (`.system/tasks/`), run history, and run logs on disk

---

## Summary

Forge is a **spec-driven path from ideas to code to systems**: specs and milestones stay human- and machine-readable, the LLM can help draft them when you want, and Forge **executes and validates** through **tasks** so what lands in the repo is **real code** that **composes into a working system**—aligned with what you reviewed and proven by gates. **Milestones** stay the roadmap; **tasks** are the only executable slice the engine plans and applies.

---

## License

MIT
