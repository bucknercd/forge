from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Union

from forge.design_manager import Milestone
from forge.execution import section_ops


@dataclass(frozen=True)
class RuleFileContains:
    target: Literal["requirements", "architecture", "decisions", "milestones"]
    substring: str


@dataclass(frozen=True)
class RuleSectionContains:
    target: Literal["requirements", "architecture", "decisions", "milestones"]
    section_heading: str
    substring: str


ForgeValidationRule = Union[RuleFileContains, RuleSectionContains]


def resolve_target_path(
    target: Literal["requirements", "architecture", "decisions", "milestones"],
    paths_mod,
) -> Path:
    mapping = {
        "requirements": paths_mod.REQUIREMENTS_FILE,
        "architecture": paths_mod.ARCHITECTURE_FILE,
        "decisions": paths_mod.DECISIONS_FILE,
        "milestones": paths_mod.MILESTONES_FILE,
    }
    return mapping[target]


def validate_rule(rule: ForgeValidationRule, paths_mod) -> tuple[bool, str]:
    path = resolve_target_path(rule.target, paths_mod)
    if not path.exists():
        return False, f"Expected file missing for validation: {path}"

    text = path.read_text(encoding="utf-8")

    if isinstance(rule, RuleFileContains):
        if rule.substring not in text:
            return False, f"file_contains failed: {path} missing substring {rule.substring!r}"
        return True, ""

    if isinstance(rule, RuleSectionContains):
        body = section_ops.read_section_body(text, rule.section_heading)
        if body is None:
            return (
                False,
                f"section_contains failed: section {rule.section_heading!r} not found in {path}",
            )
        if rule.substring not in body:
            return (
                False,
                f"section_contains failed: substring missing in section {rule.section_heading!r} of {path}",
            )
        return True, ""

    return False, "Unknown validation rule."


def validate_all_rules(
    rules: list[ForgeValidationRule], paths_mod
) -> tuple[bool, str]:
    for rule in rules:
        ok, reason = validate_rule(rule, paths_mod)
        if not ok:
            return False, reason
    return True, ""
