# Forge

**Forge** is a file-based CLI that helps you plan and execute design milestones with strong guardrails: review-first artifacts, stale checks, optional gates, and deterministic apply behavior.

## What You Get

- Deterministic artifact-driven execution (`docs/requirements.md`, `docs/architecture.md`, `docs/decisions.md`, `docs/milestones.md`)
- Reviewed-plan workflow (`preview` -> `save` -> `apply`) with stale protection
- Optional LLM planning and milestone synthesis (OpenAI or stub)
- Policy-based review enforcement for non-deterministic plans
- Clear provenance and warnings in human and JSON outputs
- Fully file-based state under `.system/` (no DB)

## Requirements

- Python **3.12+**
- Runtime dependencies: standard library only

## Install

```bash
git clone <repository-url> forge
cd forge
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

## Fast Start (Deterministic Default)

If no `forge-policy.json` exists, Forge uses deterministic planning.

```bash
# 1) Create + initialize a project
mkdir my-project && cd my-project
forge init

# 2) Replace docs/milestones.md with one minimal milestone
cat > docs/milestones.md <<'EOF'
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
EOF

# 3) Preview safely (no writes)
forge milestone-preview 1

# 4) Save reviewed plan
forge milestone-preview 1 --save-plan --json
# copy plan_id from output

# 5) Apply reviewed plan
forge milestone-apply-plan <plan_id>
```

## LLM Planning (OpenAI) in 60 Seconds

```bash
export OPENAI_API_KEY="your_api_key_here"
cat > forge-policy.json <<'EOF'
{
  "planner": {
    "mode": "llm",
    "llm_client": "openai",
    "llm_model": "gpt-4o-mini"
  }
}
EOF

forge milestone-preview 1 --planner llm --save-plan --json
# copy plan_id from output
forge milestone-apply-plan <plan_id>
```

You can also use `FORGE_OPENAI_API_KEY`.  
Do **not** put API keys in `forge-policy.json`.

## Milestone Synthesis (Review-First)

Synthesis proposes new milestones from repository design context (`requirements`, `architecture`, `decisions`, current `milestones`) and saves a reviewed artifact first.

```bash
# 1) Synthesize proposal artifact
forge milestone-synthesize --count 3 --json
# copy synthesis_id

# 2) Review artifact
forge milestone-synthesis-show <synthesis_id>

# 3) Accept into docs/milestones.md
forge milestone-synthesis-accept <synthesis_id>
```

Notes:
- Synthesis does **not** write `docs/milestones.md` during generation.
- Accept step performs stale checks before merge.
- Soft `quality_warnings` (vagueness/redundancy) are surfaced in CLI/JSON/artifacts.

## One-Command Guarded Workflow

Use `workflow-guarded` to run explicit phases end-to-end while keeping intermediate artifacts and failure points visible.

Example:

```bash
forge workflow-guarded \
  --synthesize \
  --accept-synthesized \
  --milestone-id 1 \
  --planner llm \
  --apply-plan \
  --gate-validate \
  --json
```

This still preserves safety:
- synthesis artifact is created first
- acceptance is explicit
- reviewed plan is saved before apply
- policy enforcement and gates remain active

## End-to-End Workflows

Use these playbooks when you want a full, explicit path from start to finish.

### A) Deterministic Workflow (Default)

```bash
# 1) init
mkdir my-project && cd my-project
forge init

# 2) author milestone(s) in docs/milestones.md

# 3) preview (no writes)
forge milestone-preview 1

# 4) save reviewed plan and get plan_id
forge milestone-preview 1 --save-plan --json

# 5) apply plan
forge milestone-apply-plan <plan_id>

# 6) optional verification
forge status
forge milestone-show 1
```

### B) LLM Planning Workflow (Review-First)

```bash
# 1) set API key
export OPENAI_API_KEY="your_api_key_here"

# 2) configure planner
cat > forge-policy.json <<'EOF'
{
  "planner": {
    "mode": "llm",
    "llm_client": "openai",
    "llm_model": "gpt-4o-mini"
  }
}
EOF

# 3) preview + save reviewed plan (safe)
forge milestone-preview 1 --planner llm --save-plan --json

# 4) apply reviewed plan
forge milestone-apply-plan <plan_id>
```

### C) Milestone Synthesis Workflow

```bash
# 1) synthesize milestone proposals
forge milestone-synthesize --count 3 --json

# 2) inspect synthesized artifact
forge milestone-synthesis-show <synthesis_id>

# 3) accept synthesized milestones into docs/milestones.md
forge milestone-synthesis-accept <synthesis_id>

# 4) run normal planning/apply flow for newly accepted milestones
forge milestone-preview 2 --save-plan --json
forge milestone-apply-plan <plan_id>
```

### D) Guarded Orchestration Workflow (Single Command)

```bash
forge workflow-guarded \
  --synthesize \
  --accept-synthesized \
  --milestone-id 1 \
  --planner llm \
  --apply-plan \
  --gate-validate \
  --gate-test-cmd "python -m pytest -q" \
  --json
```

This runs explicit phases in order and returns per-stage results (`synthesize`, `accept_synthesized`, `preview_save_plan`, `apply_plan`) with clear failure points.

### E) Full Concrete Example (Copy/Paste)

```bash
# clean start
mkdir forge-demo && cd forge-demo
forge init

# write one deterministic milestone
cat > docs/milestones.md <<'EOF'
# Milestones

## Milestone 1: Add first requirement marker
- **Objective**: Add a visible marker to requirements overview.
- **Scope**: Update requirements overview and mark milestone complete.
- **Validation**: Marker exists in requirements.
- **Forge Actions**:
  - append_section requirements Overview | FORGE_DEMO_OK
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements FORGE_DEMO_OK
EOF

# preview and save reviewed plan
forge milestone-preview 1 --save-plan --json

# apply reviewed plan (replace with the returned plan_id)
forge milestone-apply-plan <plan_id>

# verify result artifact and status
forge status
```

Expected outcome:
- requirements file updated with `FORGE_DEMO_OK`
- reviewed plan artifact in `.system/reviewed_plans/`
- apply result artifact in `.system/results/`

## Policy (`forge-policy.json`)

### Planner policy

| Field | Values | Notes |
|---|---|---|
| `mode` | `deterministic` (default), `llm` | Planner mode for preview/save flows |
| `llm_client` | `stub`, `openai` | Required for `mode: llm` |
| `llm_model` | string (optional) | Model ID for provider-backed clients |
| `require_review_for_nondeterministic` | `true` / `false` (default) | If true, non-deterministic preview requires `--save-plan` |

Example:

```json
{
  "planner": {
    "mode": "llm",
    "llm_client": "openai",
    "require_review_for_nondeterministic": true
  }
}
```

### Reviewed-apply defaults

`reviewed_plan_apply` policy supports defaults for post-apply gates (`run_validation_gate`, `test_command`, `test_timeout_seconds`, `test_output_max_chars`).

## Command Reference (Most Used)

```bash
# project and diagnostics
forge init
forge status
forge milestone-sync-state

# milestones
forge milestone-list
forge milestone-show 1
forge milestone-next

# deterministic/LLM planning
forge milestone-preview 1
forge milestone-preview 1 --planner llm --save-plan --json
forge milestone-apply-plan <plan_id>

# optional gates on apply
forge milestone-apply-plan <plan_id> --gate-validate
forge milestone-apply-plan <plan_id> --gate-test-cmd "python -m pytest -q"

# synthesis
forge milestone-synthesize --count 3 --json
forge milestone-synthesis-show <synthesis_id>
forge milestone-synthesis-accept <synthesis_id>

# orchestrated explicit flow
forge workflow-guarded --milestone-id 1 --planner deterministic --apply-plan
```

Run `forge --help` for full CLI options.

## Milestone Format (Reference)

```markdown
## Milestone 1: Title
- **Objective**: Clear outcome.
- **Scope**: Boundaries of change.
- **Validation**: Observable check.
- **Forge Actions**:
  - append_section requirements Overview | Marker text
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements Marker text
```

Supported action verbs: `append_section`, `replace_section`, `add_decision`, `mark_milestone_completed`  
Targets: `requirements`, `architecture`, `decisions`, `milestones`

## Where State Lives

```text
docs/                      # Design artifacts
.system/reviewed_plans/    # Reviewed execution plans
.system/reviewed_milestones/ # Reviewed synthesized milestones
.system/results/           # Result artifacts
.system/run_history.log    # JSONL run history
```

## Development

```bash
source .venv/bin/activate
python -m pytest
```

## License

MIT
