# Forge

**Forge** is a file-based CLI for turning high-level ideas into structured design artifacts and validated, milestone-driven execution. State lives on disk—no database, no frameworks.

## Features

- **Design artifacts** under `docs/`: vision, requirements, architecture, decisions, milestones
- **Runtime state** under `.system/`: milestone state, structured results, run history
- **Dependency-aware milestones**, deterministic **artifact actions** (no shell / no network), retries, and append-only audit trails

## Requirements

- Python **3.12+**
- Standard library only at runtime (see `pyproject.toml`)

## Install

From the repository root:

```bash
git clone <repository-url> forge
cd forge
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

This installs the `forge` console script (`forge.cli:main`).

## Quick start

Get from zero to first result in ~5 minutes.

### Start-to-finish command flow

Deterministic path (default):

```bash
# 1) create project + initialize Forge
mkdir my-project && cd my-project
forge init

# 2) edit docs/milestones.md (use the minimal example below)

# 3) preview (safe dry-run)
forge milestone-preview 1

# 4) save reviewed plan and copy plan_id
forge milestone-preview 1 --save-plan --json

# 5) apply reviewed plan
forge milestone-apply-plan <plan_id>

# 6) inspect results
forge status
```

LLM path (OpenAI):

```bash
# 1) set API key
export OPENAI_API_KEY="your_api_key_here"

# 2) enable LLM planner
cat > forge-policy.json <<'EOF'
{
  "planner": {
    "mode": "llm",
    "llm_client": "openai",
    "llm_model": "gpt-4o-mini"
  }
}
EOF

# 3) generate reviewed plan with LLM
forge milestone-preview 1 --planner llm --save-plan --json

# 4) apply reviewed plan
forge milestone-apply-plan <plan_id>
```

### 1) Initialize a project

```bash
mkdir my-project && cd my-project
forge init
```

If no `forge-policy.json` is present, Forge defaults to deterministic planning.

### 2) Add one minimal milestone

Open `docs/milestones.md` and replace it with:

```markdown
# Milestones

## Milestone 1: First Forge run
- **Objective**: Add one visible requirement note.
- **Scope**: Update requirements overview and mark milestone complete.
- **Validation**: The marker text exists in requirements.
- **Forge Actions**:
  - append_section requirements Overview | FORGE_FIRST_RUN_OK
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements FORGE_FIRST_RUN_OK
```

### 3) Preview safely (no file writes)

```bash
forge milestone-preview 1
```

### 4) Save + apply via reviewed plan workflow

```bash
forge milestone-preview 1 --save-plan --json
# copy plan_id from output
forge milestone-apply-plan <plan_id>
```

That is the fastest path to real ROI: you can see a proposed plan, review it, and apply it safely.

### What `forge init` creates

| Path | Purpose |
|------|---------|
| `docs/` | Design documents |
| `.system/` | Runtime state and logs |
| `artifacts/` | Optional generated outputs |

Baseline files (with starter templates where applicable):

- `docs/vision.txt`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/milestones.md`
- `.system/run_history.log`

Existing files are **not** overwritten.

### TL;DR (LLM mode)

```bash
export OPENAI_API_KEY="your_api_key_here"
echo '{"planner":{"mode":"llm","llm_client":"openai"}}' > forge-policy.json
forge milestone-preview 1 --planner llm --save-plan
```

## Using Forge with an LLM (OpenAI)

Forge can generate execution plans with a real LLM instead of deterministic `Forge Actions`.

### 1) Set your API key (required)

Mac/Linux:

```bash
export OPENAI_API_KEY="your_api_key_here"
```

Windows (PowerShell):

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

You can also use:

```bash
export FORGE_OPENAI_API_KEY="your_api_key_here"
```

Do **not** put API keys in `forge-policy.json`.

### 2) Enable LLM planner

Create or edit `forge-policy.json` in your project root:

```json
{
  "planner": {
    "mode": "llm",
    "llm_client": "openai",
    "llm_model": "gpt-4o-mini"
  }
}
```

### 3) Generate a plan (safe workflow)

```bash
forge milestone-preview 1 --planner llm --save-plan
```

This will:

- call the LLM
- generate a plan
- save a reviewed plan artifact

### 4) Apply the reviewed plan

```bash
forge milestone-apply-plan <plan_id>
```

Forge does not apply raw LLM output directly. Plans are normalized into Forge execution plans and then applied through the reviewed-plan workflow.

### 5) Optional: enforce reviewed-plan workflow for non-deterministic planners

```json
{
  "planner": {
    "mode": "llm",
    "llm_client": "openai",
    "require_review_for_nondeterministic": true
  }
}
```

Now this fails:

```bash
forge milestone-preview 1 --planner llm
```

And this succeeds:

```bash
forge milestone-preview 1 --planner llm --save-plan
```

### Verify you are using a real LLM

Quick check: intentionally break your API key, then run a preview.

```bash
export OPENAI_API_KEY=invalid
forge milestone-preview 1 --planner llm
```

- If you see an API/provider error, a real LLM client is being used.
- If it still succeeds offline, you are likely using the `stub` client.

### How it works (simple)

- `deterministic` mode uses milestone `Forge Actions`.
- `llm` mode generates a plan from:
  - milestone objective/scope/validation
  - `docs/requirements.md`
  - `docs/architecture.md`
  - `docs/decisions.md`
- All LLM outputs are parsed, validated, and normalized into the same internal execution plan format used by preview/review/apply.

## Core usage

### Project readiness

```bash
forge status
```

Reports a **project state** such as:

- **not_initialized** — run `forge init`
- **initialized_incomplete** — templates or empty docs need real content
- **ready** — minimal structure and content look usable

### Milestones (reference format)

Edit `docs/milestones.md`. Each milestone should use a heading like:

```markdown
## Milestone 1: Your title
- **Objective**: …
- **Scope**: …
- **Validation**: …
```

**Execution fields** (required for `forge execute-next` / `forge milestone-execute`):

```markdown
- **Forge Actions**:
  - append_section requirements Overview | Your marker text or paragraph
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements YOUR_MARKER
```

Supported action verbs (first token): `append_section`, `replace_section`, `add_decision`, `mark_milestone_completed`.  
Targets: `requirements`, `architecture`, `decisions`, `milestones` (mapped to files under `docs/`).

Results are written to `.system/results/milestone_<id>.json`, including `execution_plan`, `files_changed`, `artifact_summary`, and per-action records in `actions_applied` (`outcome`: `changed` | `skipped` | `failed`, optional bounded `diff` unified text when a file actually changes). Structured JSONL in `.system/run_history.log` may include `artifact_summary` on milestone attempts for a quick read of what changed. Successful runs also append a summary entry to `docs/decisions.md` unless the plan includes `add_decision`.

#### Authoring tips

- Use indented list items under `Forge Actions` / `Forge Validation` (`  - ...`).
- Keep action format strict: `append_section <target> <Section Heading> | <body>`.
- Keep validation format strict: `file_contains <target> <substring>` or `section_contains <target> <Section Heading> <substring>`.
- Parse diagnostics include milestone + source line (for example: `Milestone 3 action parse error: forge action line 42: ...`).

Example (valid):

```markdown
## Milestone 2: Capture API requirements
- **Objective**: Add API requirements section.
- **Scope**: Update requirements and mark completion.
- **Validation**: Ensure API text exists.
- **Forge Actions**:
  - append_section requirements API | - Define REST endpoints for v1.
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements Define REST endpoints for v1.
```

### Common commands

```bash
forge milestone-sync-state   # reconcile .system/milestone_state.json with milestones.md
forge milestone-next         # show next eligible milestone
forge milestone-preview      # dry-run preview for next eligible milestone
forge milestone-preview 2    # dry-run preview for a specific milestone
forge execute-next           # run the next eligible milestone (orchestration)
```

Other commands (`milestone-list`, `milestone-show`, `milestone-execute`, etc.) are available; run `forge --help` after install.

### Planner policy (`forge-policy.json`)

Optional `planner` section selects how `milestone-preview` / reviewed-plan generation builds an execution plan:

| Field | Values | Notes |
|-------|--------|--------|
| `mode` | `deterministic` (default), `llm` | Deterministic uses milestone `Forge Actions` only. |
| `llm_client` | `stub`, `openai` | Required when `mode` is `llm`. |
| `llm_model` | string (optional) | Non-secret model id for provider clients (e.g. OpenAI); defaults internally when omitted. |
| `require_review_for_nondeterministic` | `true`, `false` (default) | When `true`, non-deterministic planners must use `--save-plan` reviewed workflow. |

**Secrets never belong in this file.** For `llm_client: openai`, set API credentials via environment:

- `FORGE_OPENAI_API_KEY` or `OPENAI_API_KEY`
- Optional: `FORGE_OPENAI_BASE_URL` (defaults to `https://api.openai.com/v1`)

Example (offline stub):

```json
{
  "planner": {
    "mode": "llm",
    "llm_client": "stub"
  }
}
```

## Where things live

```
docs/                 # Vision, requirements, architecture, decisions, milestones
.system/              # milestone_state.json, results/*.json, run_history.log
artifacts/            # Reserved for generated outputs
forge/                # Package source
tests/                # Pytest suite
```

## Audit trails

- **Decisions** — append-only entries in `docs/decisions.md` (e.g. after successful milestone completion).
- **Run history** — JSON Lines in `.system/run_history.log` (structured attempt records; append-only).

## Development

```bash
source .venv/bin/activate
python -m pytest
```

## License

MIT
