from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Union

from forge.design_manager import Milestone
from forge.execution import section_ops
from forge.execution.safe_paths import resolve_safe_project_path


@dataclass(frozen=True)
class RuleFileContains:
    target: Literal["requirements", "architecture", "decisions", "milestones"]
    substring: str
    substring_input: str | None = None
    substring_quote_style: Literal["none", "single", "double"] = "none"


@dataclass(frozen=True)
class RulePathFileContains:
    """Validate substring presence in a repo-relative file (bounded paths)."""

    rel_path: str
    substring: str
    substring_input: str | None = None
    substring_quote_style: Literal["none", "single", "double"] = "none"


@dataclass(frozen=True)
class RuleSectionContains:
    target: Literal["requirements", "architecture", "decisions", "milestones"]
    section_heading: str
    substring: str
    substring_input: str | None = None
    substring_quote_style: Literal["none", "single", "double"] = "none"


ForgeValidationRule = Union[RuleFileContains, RulePathFileContains, RuleSectionContains]


def _validation_substring_diag(rule: ForgeValidationRule) -> str:
    """Human-readable parse/unquote context for validation failures."""
    if isinstance(rule, RulePathFileContains):
        bits = [
            f"rel_path={rule.rel_path!r}",
            f"needle={rule.substring!r}",
            f"unquote_applied={'yes' if rule.substring_quote_style != 'none' else 'no'}",
        ]
        if rule.substring_input is not None:
            bits.append(f"raw_substring_field={rule.substring_input!r}")
        return "; ".join(bits)
    if isinstance(rule, RuleFileContains):
        bits = [
            f"target={rule.target!r}",
            f"needle={rule.substring!r}",
            f"unquote_applied={'yes' if rule.substring_quote_style != 'none' else 'no'}",
        ]
        if rule.substring_input is not None:
            bits.append(f"raw_substring_field={rule.substring_input!r}")
        return "; ".join(bits)
    if isinstance(rule, RuleSectionContains):
        bits = [
            f"target={rule.target!r}",
            f"section={rule.section_heading!r}",
            f"needle={rule.substring!r}",
            f"unquote_applied={'yes' if rule.substring_quote_style != 'none' else 'no'}",
        ]
        if rule.substring_input is not None:
            bits.append(f"raw_substring_field={rule.substring_input!r}")
        return "; ".join(bits)
    return ""


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
    if isinstance(rule, RulePathFileContains):
        try:
            path = resolve_safe_project_path(rule.rel_path, paths_mod.BASE_DIR)
        except ValueError as exc:
            return False, f"path_file_contains failed: {exc}"
        if not path.exists():
            return False, f"path_file_contains failed: missing file {path}"
        text = path.read_text(encoding="utf-8")
        if rule.substring not in text:
            return (
                False,
                f"path_file_contains failed: {path} missing substring {rule.substring!r} "
                f"({_validation_substring_diag(rule)})",
            )
        return True, ""

    path = resolve_target_path(rule.target, paths_mod)
    if not path.exists():
        return False, f"Expected file missing for validation: {path}"

    text = path.read_text(encoding="utf-8")

    if isinstance(rule, RuleFileContains):
        if rule.substring not in text:
            return (
                False,
                f"file_contains failed: {path} missing substring {rule.substring!r} "
                f"({_validation_substring_diag(rule)})",
            )
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
                f"section_contains failed: substring missing in section {rule.section_heading!r} of {path} "
                f"({_validation_substring_diag(rule)})",
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
