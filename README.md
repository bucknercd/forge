# Forge

Forge is a **spec-driven CLI** that turns **ideas into milestones into code**—**the coherent, validated code that working systems are built from**.

Forge is a **two-layer system**:

1. **Milestones (roadmap)** — live in **`docs/milestones.md`**: intent, scope, **Forge Actions**, and **Forge Validation** for the whole slice. They define *what* to achieve, not the step you execute next in the engine.
2. **Tasks (execution units)** — live in **`.system/tasks/m<id>.json`**: small, ordered, reviewable steps derived from a milestone. **Only tasks are executed:** preview, reviewed plans, and apply always go through a **task id** (`m<id>-t<task>-<hash>` plans).

Between those layers, **task expansion** turns milestone Forge Actions into 2–6 tasks (deterministic split) or a **single compatibility task** when splitting is not possible. Expansion runs **automatically** the first time you preview, save a plan, run **`execute-next`**, **`vertical-slice`**, or **`workflow-guarded`** (you’ll see a notice on **stderr** if tasks were missing). You can still run **`forge task-expand`** manually or with **`--force`** to refresh JSON from the current milestone text.

You start with intent—a short phrase, a vision file, or the demo. Forge (optionally with an LLM) materializes **`docs/`** specs and milestones. A **planner** builds a plan for the **selected task**; Forge **applies** it under **gates**. The loop repeats until the system **holds up under checks**.

**In one sentence:** *idea → vision & specs → milestones → **tasks** → reviewed plan → apply → validation → a working system.*

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
Task selection (--task <n>, or next pending task for execute-next / vertical-slice)
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

**`forge vertical-slice`** materializes docs, **ensures tasks** for milestone **1**, saves a reviewed plan for the **next pending task**, applies it, and runs gates. **`forge milestone-preview`** without **`--task`** lists tasks and asks you to pick one; with **`--task`** it previews that execution unit. **`forge execute-next`** runs the **next milestone’s next pending task** (multi-task milestones may need several **`execute-next`** runs). See **[Milestones vs tasks](#milestones-vs-tasks-two-layer-planning)** and **[Why tasks are required](#why-tasks-are-required)**.

### Artifact tests & bounded repair (unified execution)

These commands share the **same task-scoped repair orchestration** (via `Executor.run_task_apply_with_repair_loop`):

- **`forge execute-next`**
- **`forge milestone-apply-plan <plan_id>`** (first attempt applies **that** reviewed plan; later attempts save new `m<id>-t<task>-<hash>` plans for the same task)
- **`forge vertical-slice`** (apply stage)
- **`forge workflow-guarded`** when it reaches the apply step

The loop:

1. **Save** a reviewed plan for the task when needed (`execute-next` and retries always save; **apply-plan / vertical-slice / workflow** reuse the plan id from the prior preview/save step on the **first** attempt only).
2. **Apply** implementation actions (post-apply gates are **deferred** and run in the batch below).
3. **Generate** (when enabled) a **targeted pytest file** under `tests/forge_generated/` from the task’s Forge Validation lines and `write_file` targets—**skipped with an explicit reason** when no heuristic applies.
4. Run **Forge milestone validation** when enabled (`execute-next` always runs it; **`milestone-apply-plan`** / workflow / vertical-slice follow **`reviewed_plan_apply.run_validation_gate`** and CLI `--gate-validate` / `--no-gate-validate`), then **pytest on the generated file** (if any), then optional **`reviewed_plan_apply.test_command`**.
5. **On success** → mark the task complete. **On failure** → persist structured feedback under **`.system/task_feedback/`** and **re-plan the same task**. **Deterministic** planner → **one** attempt; **LLM** mode uses feedback until **`task_execution.max_repair_attempts`** (default **3**, cap **20**). **`execute-next`** still updates roadmap **retry/failed** state on exhaustion; **apply-plan** / **vertical-slice** / **workflow** do not move the milestone state machine on failure (the task simply stays incomplete).

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
- Validation: `path_file_contains <rel_path> <substring>` (substring is the rest of the line).

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

The **planner** (deterministic or LLM-backed, per `forge-policy.json`) always reads a **milestone-shaped execution unit** produced from a **task** under `.system/tasks/m<id>.json` via `task_to_execution_milestone(...)` (same roadmap **milestone id** for `mark_milestone_completed` and docs). **New** reviewed plans are always **task-scoped** (`m<id>-t<task>-<hash>`). **Legacy** reviewed plans saved before task enforcement may omit `task_id`; **`milestone-apply-plan`** can still apply them using the milestone definition from `docs/milestones.md` until you re-save from a task.

**Execution** is deterministic: Forge does what the saved plan says, then runs **gates**. Failure stops the run with a clear reason; you fix specs, milestones, or code and try again—there is no hidden auto-retry in the engine itself (orchestration like `workflow-guarded` can combine multiple steps).

### Milestones vs tasks (two-layer planning)

**Milestones** live in `docs/milestones.md`: roadmap intent, Forge Actions, and Forge Validation for the whole slice. They are **not** passed directly to the planner/executor.

**Tasks** are the **only** execution units: concrete, ordered steps in **`.system/tasks/m<milestone_id>.json`**. Preview, **`--save-plan`**, **`execute-next`**, **`vertical-slice`**, and **`workflow-guarded`** all resolve a **task id** (explicit **`--task`**, or the **next pending task** for automated flows). Roadmap **`mark_milestone_completed`** still refers to the **milestone id** in `docs/milestones.md`.

- **Auto-expansion** — If tasks are missing, Forge runs the same logic as **`forge task-expand --milestone <id>`** (notices on **stderr**). If a multi-task split is invalid, Forge uses a **single compatibility task** that mirrors the whole milestone and logs a **compatibility-mode** warning (never a silent raw-milestone execute).
- **`forge task-expand --milestone <id>`** — (Re)materialize tasks: **2–6** via deterministic split when possible; optional **LLM JSON** expansion when a non-stub OpenAI client is configured; else **compatibility** fallback. Use **`--force`** to replace existing JSON from the current milestone text.
- **`forge task-list` / `forge task-show`** — Inspect tasks (**`--json`** supported).
- **`forge milestone-preview <id>`** — Without **`--task`**, Forge prints the task list and tells you to pass **`--task <n>`**. With **`--task`**, previews that task. **`--save-plan`** with an explicit milestone id **requires** **`--task`**.
- **`forge milestone-preview` (no id)** — Previews the **next eligible milestone’s next pending task** (deterministic planner only for the no-id save path, as before).
- **`forge milestone-apply-plan <plan_id>`** — Unchanged; apply uses the **`task_id`** stored in the reviewed plan when present.

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
forge vertical-slice --from-vision          # uses docs/vision.txt
forge vertical-slice --vision-file ./notes/vision.txt
```

**Incremental (existing repo)**

```bash
forge status
forge milestone-list
forge milestone-next
forge milestone-preview 1                  # lists tasks; add --task <n> to preview
forge milestone-preview 1 --task 1 --save-plan   # persist task-scoped reviewed plan
forge milestone-apply-plan <plan_id>       # apply saved plan + gates
forge execute-next                         # next milestone’s next pending task
```

**Tasks (under each milestone)**

Tasks are **created automatically** when needed; use **`forge task-expand`** to refresh or inspect. Walk tasks **in order** when they have **`depends_on`**.

```bash
forge task-expand --milestone 1            # 2–6 tasks by default (deterministic split)
forge task-expand --milestone 1 --force      # regenerate task JSON from milestones.md
forge task-list --milestone 1              # id, title, objective, dependencies
forge task-show --milestone 1 --task 2       # any task id from the list
forge milestone-preview 1 --task 2
forge milestone-preview 1 --task 2 --save-plan
forge milestone-apply-plan m1-t2-<hash12>  # plan id matches saved --task
```

**Milestone generation (LLM)** — same as `milestone-synthesize`:

```bash
forge milestone-generate --count 3
```

---

## Enable LLM

Use the same **`forge-policy.json`** and **OpenAI environment variables** as in [Quick Start → Using an LLM (OpenAI)](#using-an-llm-openai). Then you can use LLM mode outside vertical slice, for example:

```bash
forge milestone-preview 1 --task 1 --planner llm
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
forge milestone-apply-plan \
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
