from __future__ import annotations

import json
from dataclasses import dataclass, field

from forge.design_manager import Milestone

from forge.execution.models import ExecutionPlan
from forge.execution.parse import parse_forge_action_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.llm import LLMClient
from forge.paths import Paths
from forge.planner_normalize import (
    normalize_llm_planner_action_line,
    persist_llm_planner_raw_on_failure,
)


class Planner:
    mode = "deterministic"
    stable_for_recheck = True

    def build_plan(
        self, milestone: Milestone, *, repair_context: dict | None = None
    ) -> ExecutionPlan:
        raise NotImplementedError

    def metadata(self) -> dict:
        return {
            "mode": self.mode,
            "is_nondeterministic": not bool(self.stable_for_recheck),
            "llm_client": None,
            "llm_model": None,
        }


class DeterministicPlanner(Planner):
    mode = "deterministic"
    stable_for_recheck = True

    def build_plan(
        self, milestone: Milestone, *, repair_context: dict | None = None
    ) -> ExecutionPlan:
        _ = repair_context  # deterministic plans ignore prior failure context
        return ExecutionPlanBuilder.build(milestone)


@dataclass
class LLMPlanner(Planner):
    llm_client: LLMClient
    mode: str = "llm"
    stable_for_recheck: bool = False
    fallback_to_milestone_actions: bool = True
    last_normalization_notes: list[str] = field(default_factory=list)

    def build_plan(
        self, milestone: Milestone, *, repair_context: dict | None = None
    ) -> ExecutionPlan:
        self.last_normalization_notes = []
        prompt = _build_llm_plan_prompt(milestone)
        if repair_context:
            from forge.task_feedback import repair_context_to_prompt_appendix

            prompt += repair_context_to_prompt_appendix(repair_context)
        raw = ""
        try:
            raw = self.llm_client.generate(prompt)
            actions_raw = _parse_llm_actions(
                raw,
                fallback_actions=milestone.forge_actions if self.fallback_to_milestone_actions else None,
            )
            if not actions_raw:
                raise ValueError("LLM planner output produced an empty actions list.")

            actions = []
            for idx, item in enumerate(actions_raw, start=1):
                if not isinstance(item, str):
                    raise ValueError(f"LLM planner action {idx} must be a string.")
                if not item.strip():
                    raise ValueError(f"LLM planner action {idx} must be non-empty.")
                try:
                    normalized, notes = normalize_llm_planner_action_line(item)
                    for n in notes:
                        self.last_normalization_notes.append(f"action {idx}: {n}")
                    actions.append(parse_forge_action_line(normalized, milestone))
                except ValueError as exc:
                    raise ValueError(f"LLM planner action {idx} invalid: {exc}") from exc
            return ExecutionPlan(milestone_id=milestone.id, actions=actions)
        except ValueError as exc:
            if raw and str(raw).strip():
                persist_llm_planner_raw_on_failure(
                    raw, milestone.id, reason=str(exc)
                )
            raise

    def metadata(self) -> dict:
        meta = {
            "mode": self.mode,
            "is_nondeterministic": True,
            "llm_client": getattr(self.llm_client, "client_id", "unknown"),
            "llm_model": getattr(self.llm_client, "model_name", None),
        }
        if self.last_normalization_notes:
            meta["normalization_notes"] = self.last_normalization_notes
        return meta


def _doc_excerpt(path, *, max_chars: int = 1200) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return "(unavailable)"
    trimmed = text.strip()
    if not trimmed:
        return "(empty)"
    if len(trimmed) > max_chars:
        return trimmed[:max_chars] + "\n...[truncated]"
    return trimmed


def _build_llm_plan_prompt(milestone: Milestone) -> str:
    requirements = _doc_excerpt(Paths.REQUIREMENTS_FILE)
    architecture = _doc_excerpt(Paths.ARCHITECTURE_FILE)
    decisions = _doc_excerpt(Paths.DECISIONS_FILE)
    return (
        "You are generating a Forge milestone execution plan.\n"
        "Return ONLY a JSON object with this exact shape:\n"
        "{\"actions\": [\"<forge-action-line>\", \"...\"]}\n\n"
        "Hard constraints:\n"
        "- No prose, no markdown, no code fences.\n"
        "- Use only these action verbs:\n"
        "  append_section <target> <Section Heading> | <body>\n"
        "  replace_section <target> <Section Heading> | <body>\n"
        "- CRITICAL for append_section / replace_section: there must be THREE space-separated "
        "tokens BEFORE the first ' | ' (verb, target, section heading). "
        "Do NOT write 'append_section requirements | ...' — that is invalid. "
        "The <Section Heading> is a short title (e.g. Overview), not the whole section body.\n"
        "- Prefer write_file / bounded file edits for code; use append_section only for doc sections.\n"
        "  write_file <rel_path> | <body with \\\\n for newlines>\n"
        "  insert_after_in_file <rel_path> | anchor @@FORGE@@ insertion\n"
        "  insert_before_in_file <rel_path> | anchor @@FORGE@@ insertion\n"
        "  replace_text_in_file <rel_path> | old_text @@FORGE@@ new_text\n"
        "  replace_block_in_file <rel_path> | start @@FORGE@@ end @@FORGE@@ new_body\n"
        "  replace_lines_in_file <rel_path> | start_line @@FORGE@@ end_line @@FORGE@@ replacement\n"
        "  Optional trailing: | occurrence=N must_be_unique=false line_match=true\n"
        "  (use literal @@FORGE@@ with spaces as shown; \\\\n for newlines in parts)\n"
        "  add_decision | <title> | <rationale>\n"
        "  mark_milestone_completed\n"
        "- Bounded file paths must start with examples/, src/, scripts/, or tests/.\n"
        "- Allowed targets: requirements, architecture, decisions, milestones.\n"
        "- Prefer a small plan (2-8 actions) that satisfies the milestone.\n\n"
        "Milestone:\n"
        f"- id: {milestone.id}\n"
        f"- title: {milestone.title}\n"
        f"- objective: {milestone.objective}\n"
        f"- scope: {milestone.scope}\n"
        f"- validation: {milestone.validation}\n\n"
        "Repository context excerpts:\n"
        f"=== requirements.md ===\n{requirements}\n\n"
        f"=== architecture.md ===\n{architecture}\n\n"
        f"=== decisions.md ===\n{decisions}\n"
    )


def _parse_llm_actions(raw: str, fallback_actions: list[str] | None) -> list[str]:
    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"LLM planner returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM planner output must be a JSON object.")
    actions_raw = parsed.get("actions")
    if not isinstance(actions_raw, list):
        if fallback_actions:
            return list(fallback_actions)
        raise ValueError("LLM planner output must include an 'actions' array.")
    return actions_raw
