from __future__ import annotations

import json

from forge.execution.parse import parse_forge_validation_line
from forge.paths import Paths
from forge.validator import Validator
from forge.validation_normalize import normalize_validation_rule, sanitize_validation_rules
from forge.executor import Executor
from tests.forge_test_project import configure_project


def test_normalize_validation_rule_natural_language_to_canonical():
    raw = "src/logcheck.py contains a function to read files"
    out = normalize_validation_rule(raw)
    assert out == "path_file_contains src/logcheck.py def"


def test_sanitize_validation_rules_drops_unconvertible():
    out, warnings = sanitize_validation_rules(
        ["src/logcheck.py validates behavior thoroughly"], log_warnings=False
    )
    assert out == []
    assert any("Dropped invalid validation" in w for w in warnings)


def test_sanitize_validation_rules_parser_sees_only_canonical_parseable():
    out, _warnings = sanitize_validation_rules(
        [
            "src/logcheck.py contains a function to read files",
            "src/logcheck.py filters out INFO and DEBUG messages",
            "this cannot be converted",
        ],
        log_warnings=False,
    )
    assert out == [
        "path_file_contains src/logcheck.py def",
        "path_file_contains src/logcheck.py ERROR",
    ]
    # Parser should only see canonical rules.
    for rule in out:
        parse_forge_validation_line(rule, line_no=1)


def test_milestone_validation_natural_language_rule_no_parse_error(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Normalize Validation
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | READY
- **Forge Validation**:
  - src/logcheck.py contains a function to read files
""",
    )
    # Execute once to produce artifact/result file.
    Executor.execute_milestone(1)
    with (Paths.SYSTEM_DIR / "results" / "milestone_1.json").open("r", encoding="utf-8") as fh:
        result = json.load(fh)
    # Ensure the failure mode is not validation parse errors.
    assert "validation_error" not in result or "Invalid Forge Validation" not in str(
        result.get("validation_error", "")
    )
    ok, reason = Validator.validate_milestone_with_report(1)
    assert not ok
    assert "Invalid Forge Validation" not in reason

