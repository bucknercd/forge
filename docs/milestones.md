# Milestones

## Milestone 1: Bootstrap Repository
- **Objective**: Create the initial repository structure and documentation.
- **Scope**: Define the repo structure, draft documentation, and set up Python dependencies.
- **Validation**: Ensure all documentation is complete and Python environment is functional.

## Milestone 2: Vision Loader
- **Objective**: Implement the ability to load and persist a project vision.
- **Scope**: Support reading and writing the `vision.txt` file.
- **Validation**: Verify that the vision can be loaded, edited, and saved.

## Milestone 3: Design Manager
- **Objective**: Implement the ability to maintain system design documents.
- **Scope**: Support CRUD operations for `requirements.md`, `architecture.md`, `decisions.md`, and `milestones.md`.
- **Validation**: Verify that design documents can be created, updated, and persisted.

## Milestone 4: Decision Tracker
- **Objective**: Implement the ability to record and track decisions.
- **Scope**: Support appending decisions to `decisions.md`.
- **Validation**: Verify that decisions are correctly recorded and persisted.

## Milestone 5: Milestone Generator
- **Objective**: Implement the ability to generate bounded milestones.
- **Scope**: Support creating milestones based on design artifacts.
- **Validation**: Verify that milestones are correctly generated and persisted.

## Milestone 6: Run History Manager
- **Objective**: Implement the ability to store a history of runs.
- **Scope**: Support appending run history to a log file.
- **Validation**: Verify that run history is correctly recorded and persisted.

## Milestone 7: Bounded file edit actions
- **Objective**: Support safer, reviewable edits to allowed project files without always using full-file `write_file`.
- **Scope**: Deterministic Forge Actions `insert_after_in_file`, `insert_before_in_file`, `replace_text_in_file`, and `replace_block_in_file` on paths under `examples/`, `src/`, `scripts/`, or `tests/`; substring matching must be unique (non-overlapping count exactly one) or the action fails; preserve preview/dry-run diffs; keep `write_file` for bootstrap scenarios.
- **Validation**: Milestone Forge Validation may use `path_file_contains` (and existing design-doc rules) to assert post-conditions; integration tests cover success, zero-match, and ambiguous-match failures.
