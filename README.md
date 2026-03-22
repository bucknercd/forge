# Forge

Forge is a **spec-driven CLI** that turns **ideas into milestones into code**—**the coherent, validated code that working systems are built from**.

You start with intent—a short phrase on the command line, a long vision in a file, or the built-in demo. Forge (optionally with an LLM) turns that into **`docs/` specs** and **`docs/milestones.md`**: structured milestones whose **Forge Actions** describe concrete file edits and whose **Forge Validation** rules define how to check the result. A **planner** turns the next milestone into an **execution plan**; Forge **applies** it under **gates** (validation rules + optional test command). The loop repeats until the pieces **fit together as a system** you can trust—not just files on disk, but **behavior that holds up under checks**.

**In one sentence:** *idea → vision & specs → milestones → plan → applied code → validation → a working system.*

---

## The pipeline

```text
Your idea (CLI text, vision file, or demo)
        │
        ▼
docs/   vision.txt · requirements.md · architecture.md · milestones.md
        │
        ▼
Milestones   (markdown: objectives + Forge Actions + Forge Validation)
        │
        ▼
Plan         (reviewed, saved under .system/reviewed_plans/)
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

**Optional task mode (finer slices):** `forge task-expand` turns each roadmap milestone into **2–6 ordered tasks** in **`.system/tasks/m<id>.json`** (or **one compatibility task** if expansion can’t split safely). You then run **`milestone-preview` / `--save-plan` with `--task <n>`** so each **saved plan** and **apply** targets that task’s Forge Actions/Validation while still using the same milestone id in `docs/milestones.md`. See **[Milestones vs tasks](#milestones-vs-tasks-two-layer-planning)**.

**`forge vertical-slice`** runs the full slice in one go: materialize or refresh docs from the idea → preview/save plan for milestone 1 → apply → gates (milestone-wide, not task JSON). **`forge milestone-*`** commands let you walk the same path step by step on an existing repo; add **`task-expand` + `--task`** when you want execution broken into reviewable steps.

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
2. Builds an execution plan from milestone **Forge Actions** (deterministic by default), including `write_file examples/todo_cli.py | …`.
3. Saves a reviewed plan under `.system/reviewed_plans/`.
4. Applies the plan (creates `examples/todo_cli.py`, appends to requirements, updates milestone status in `docs/milestones.md`).
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

The **planner** (deterministic or LLM-backed, per `forge-policy.json`) reads a **milestone-shaped execution unit** and produces a concrete **plan**. That unit is normally the milestone parsed from `docs/milestones.md`; if you use **task mode**, it is the **task** from `.system/tasks/m<id>.json` (still the same milestone **id** for `mark_milestone_completed` and docs). Important plans are **reviewed and saved** before apply so execution is traceable; plan ids include **`m<id>-t<task>-<hash>`** when scoped to a task.

**Execution** is deterministic: Forge does what the saved plan says, then runs **gates**. Failure stops the run with a clear reason; you fix specs, milestones, or code and try again—there is no hidden auto-retry in the engine itself (orchestration like `workflow-guarded` can combine multiple steps).

### Milestones vs tasks (two-layer planning)

**Milestones** live in `docs/milestones.md`: roadmap intent, Forge Actions, and Forge Validation for the whole slice. **Tasks** are the **execution unit** for planning and apply when you use task mode: concrete, ordered steps stored as JSON under **`.system/tasks/m<milestone_id>.json`** (easy to diff and edit). Preview/save/apply use the selected task’s actions/validation while still targeting the same milestone id (e.g. `mark_milestone_completed`).

- **`forge task-expand --milestone <id>`** — generates **2–6 tasks** when possible using a **deterministic split** of Forge Actions (work slices first, `mark_milestone_completed` + milestone Forge Validation on the **last** task; or multiple work-only tasks when there is no completion marker). If a real OpenAI client is configured in policy, Forge may try an **optional LLM JSON expansion** that must pass the same checks; otherwise it stays deterministic. If expansion cannot produce a valid multi-task list, Forge falls back to a **single compatibility task** that mirrors the milestone (same behavior as early task mode).
- **`forge task-list --milestone <id>`** — human-readable lines: task **id**, **title**, short **objective**, **depends_on**. **`forge task-show --milestone <id> --task <n>`** — full detail (both support **`--json`**).
- **`--force`** on **`task-expand`** replaces an existing `.system/tasks/m<id>.json` from the **current** milestone text (default is to keep existing tasks).
- **`forge milestone-preview <id> --task <n>`** — preview a plan built from that task (same planner rules as milestone preview).
- **`forge milestone-preview <id> --task <n> --save-plan`** — save a reviewed plan; plan ids look like **`m<id>-t<task>-<hash>`**. Apply with **`forge milestone-apply-plan <plan_id>`** (unchanged command; no bypass of review or gates).

**Compatibility:** If you never run `task-expand`, behavior stays **milestone-only** (`milestone-preview` / `milestone-apply-plan` as today). After `task-expand`, prefer **task-scoped** preview/save for execution-level review; milestone-level preview still reflects the full `docs/milestones.md` block.

**Note:** Post-apply **milestone_validation** still reads **Forge Validation** from `docs/milestones.md` for that milestone id. Split tasks **duplicate** the milestone’s Forge Validation on each slice that has Forge Actions so previews and gates stay well-formed; full milestone checks may only pass after the **last** task (or use `--no-gate-validate` on intermediate applies if your policy allows).

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
forge milestone-preview 1                  # optional: milestone id
forge milestone-preview 1 --save-plan      # persist reviewed plan
forge milestone-apply-plan <plan_id>       # apply saved plan + gates
forge execute-next
```

For **smaller execution chunks**, run **`forge task-expand`** first, then use **`milestone-preview <id> --task <n>`** (see below).

**Tasks (optional, under a milestone)**

After **`task-expand`**, walk tasks **in order** when they have **`depends_on`** (later tasks assume earlier ones are done).

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
forge milestone-preview 1 --planner llm
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

Chains optional **milestone synthesis** (LLM), **preview/save plan** for a milestone, and **apply with gates**. Use `--accept-synthesized` / `--synthesis-id` when you want synthesized proposals merged into `docs/milestones.md` (see `forge workflow-guarded --help`). It does **not** run **`task-expand`**; use **`forge task-expand`** and **`--task`** on **`milestone-preview`** / **`milestone-apply-plan`** when you want multi-task slices.

---

## Validation Gates

After apply, Forge can run:

* **Forge Validation** rules — for **milestone-only** plans, from `docs/milestones.md`; for **task** plans, rules are still evaluated the same way, but the **saved plan** was built from that task’s Forge Validation lines (often a copy of the milestone’s rules on each slice). **Milestone-level** post-apply checks still consult **`docs/milestones.md`** for that id.
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
* **Explicit state** — reviewed plans, optional **per-milestone task JSON**, run history, and run logs on disk

---

## Summary

Forge is a **spec-driven path from ideas to code to systems**: specs and milestones stay human- and machine-readable, the LLM can help draft them when you want, and Forge **executes and validates** so what lands in the repo is **real code** that **composes into a working system**—aligned with what you reviewed and proven by gates. **Task mode** splits milestones into **ordered, review-sized steps** in `.system/tasks/` without changing the execution engine: each step still becomes a reviewed plan and apply with the same gates semantics.

---

## License

MIT
