from __future__ import annotations

import json
from dataclasses import dataclass, field

from forge.design_manager import Milestone

from forge.execution.models import ExecutionPlan
from forge.execution.parse import (
    BOUNDED_FILE_EDIT_CMDS,
    FORGE_BOUNDED_EDIT_SEP,
    parse_forge_action_line,
)
from forge.execution.plan import ExecutionPlanBuilder
from forge.llm import LLMClient
from forge.paths import Paths
from forge.planner_normalize import (
    normalize_llm_planner_action_line,
    persist_llm_planner_raw_on_failure,
)
from forge.project_profile import detect_project_profile, planner_guidance_for_profile
from forge.task_ir import extract_behavior_signals
from forge.vertical_slice_json import extract_vertical_slice_json_text


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
    last_normalization_events: list[dict[str, str]] = field(default_factory=list)
    last_json_extraction_kind: str | None = None

    def build_plan(
        self, milestone: Milestone, *, repair_context: dict | None = None
    ) -> ExecutionPlan:
        self.last_normalization_notes = []
        self.last_normalization_events = []
        self.last_json_extraction_kind = None
        prompt = _build_llm_plan_prompt(milestone)
        if repair_context:
            from forge.task_feedback import repair_context_to_prompt_appendix

            prompt += repair_context_to_prompt_appendix(repair_context)
        raw = ""
        parse_error: ValueError | None = None
        last_bad_action: str | None = None
        for attempt in (1, 2):
            try:
                raw = self.llm_client.generate(prompt)
                try:
                    json_text, ext_kind = extract_vertical_slice_json_text(raw)
                except ValueError as exc:
                    raise ValueError(f"LLM planner: JSON extraction failed: {exc}") from exc
                self.last_json_extraction_kind = ext_kind
                try:
                    parsed = json.loads(json_text)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"LLM planner: invalid JSON after {ext_kind} extraction: {exc}"
                    ) from exc
                actions_raw = _parse_llm_actions_payload(
                    parsed,
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
                        _validate_llm_action_shape(item)
                        normalized, notes = normalize_llm_planner_action_line(item)
                        for n in notes:
                            self.last_normalization_notes.append(f"action {idx}: {n}")
                        if normalized != item:
                            self.last_normalization_events.append(
                                {
                                    "action_index": str(idx),
                                    "original_action": item,
                                    "normalized_action": normalized,
                                    "reason": (notes[0] if notes else "normalized at planner boundary"),
                                }
                            )
                        actions.append(parse_forge_action_line(normalized, milestone))
                    except ValueError as exc:
                        raise ValueError(
                            f"LLM planner action {idx} invalid: {exc} Bad action: {item!r}"
                        ) from exc
                return ExecutionPlan(milestone_id=milestone.id, actions=actions)
            except ValueError as exc:
                parse_error = exc
                msg = str(exc)
                last_bad_action = _extract_bad_action_from_error(msg)
                if (
                    attempt == 1
                    and _is_retryable_planner_action_error(msg)
                    and last_bad_action is not None
                ):
                    prompt = _build_llm_planner_retry_prompt(
                        milestone=milestone,
                        previous_prompt=prompt,
                        bad_action=last_bad_action,
                        error_message=msg,
                    )
                    continue
                break

        assert parse_error is not None
        exc = parse_error
        try:
            artifact_path = None
            if raw and str(raw).strip():
                artifact_path = persist_llm_planner_raw_on_failure(
                    raw, milestone.id, reason=str(exc)
                )
            msg = str(exc)
            if artifact_path is not None:
                msg = f"{msg} Raw planner output saved to: {artifact_path}"
            raise ValueError(msg) from exc
        except ValueError:
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
        if self.last_normalization_events:
            meta["normalization_events"] = self.last_normalization_events
        if self.last_json_extraction_kind:
            meta["json_extraction_kind"] = self.last_json_extraction_kind
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
    profile = detect_project_profile(
        texts=[
            milestone.title,
            milestone.objective,
            milestone.scope,
            milestone.validation,
            requirements,
            architecture,
            decisions,
        ]
    )
    profile_guide = planner_guidance_for_profile(profile)
    behavior_signals = extract_behavior_signals(
        milestone.title, milestone.objective, milestone.scope, milestone.validation
    )
    behavioral_depth_guidance = ""
    if behavior_signals:
        behavioral_depth_guidance = (
            "Behavioral depth requirements:\n"
            f"- Detected behavior signals: {', '.join(behavior_signals)}\n"
            "- Do not stop at file read + filter-only logic.\n"
            "- Include at least one meaningful transformation such as counting/aggregation/grouping/sorting.\n"
            "- Prefer composable function boundaries (e.g., parse -> count -> top-k formatting).\n"
            "- Use structured outputs (dict, Counter, list[tuple], or similar), not raw passthrough lines.\n\n"
        )
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
        "- For NEW files (especially tests/*), use write_file with full file content.\n"
        "- Do NOT use insert_after_in_file/insert_before_in_file on files created in this same plan.\n"
        "  write_file <rel_path> | <body with \\\\n for newlines> "
        "(body may contain the substring ' | ' — only the delimiter after <rel_path> splits path vs body)\n"
        "  insert_after_in_file <rel_path> | <anchor> @@FORGE@@ <insertion>\n"
        "  insert_before_in_file <rel_path> | <anchor> @@FORGE@@ <insertion>\n"
        "  replace_text_in_file <rel_path> | <old_text> @@FORGE@@ <new_text>\n"
        "  replace_block_in_file <rel_path> | <start> @@FORGE@@ <end> @@FORGE@@ <new_body>\n"
        "  replace_lines_in_file <rel_path> | <start_line> @@FORGE@@ <end_line> @@FORGE@@ <replacement>\n"
        "  Optional trailing: | occurrence=N must_be_unique=false line_match=true\n"
        "  (CRITICAL: bounded edits must include literal ' @@FORGE@@ ' separators; \\\\n for newlines in parts)\n"
        "  add_decision | <title> | <rationale>\n"
        "  mark_milestone_completed\n"
        "- Bounded file paths must start with examples/, src/, scripts/, or tests/.\n"
        "- Allowed targets: requirements, architecture, decisions, milestones.\n"
        "- Prefer a small plan (2-8 actions) that satisfies the milestone.\n\n"
        f"Detected project profile: {profile.profile_name}\n"
        f"Profile guidance: {profile_guide}\n\n"
        f"{behavioral_depth_guidance}"
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


def _validate_llm_action_shape(action: str) -> None:
    """
    Cheap deterministic pre-parse checks for common malformed bounded-edit output.
    """
    s = (action or "").strip()
    if not s:
        raise ValueError("empty action line")
    cmd = s.split(None, 1)[0].lower()
    if cmd not in BOUNDED_FILE_EDIT_CMDS:
        return
    if " | " not in s:
        raise ValueError(
            f"{cmd} must include ' | ' after <rel_path> and use {FORGE_BOUNDED_EDIT_SEP!r} between parts."
        )
    # Bounded edits are expected to include at least one separator in payload.
    if FORGE_BOUNDED_EDIT_SEP not in s:
        raise ValueError(
            f"{cmd} missing required bounded-edit separator {FORGE_BOUNDED_EDIT_SEP!r}. "
            "Use canonical syntax with @@FORGE@@ separators."
        )


def _is_retryable_planner_action_error(message: str) -> bool:
    m = (message or "").lower()
    return (
        "llm planner action" in m
        and (
            "@@forge@@" in m
            or "bounded-edit separator" in m
            or "needs exactly one separator" in m
            or "replace_lines_in_file needs" in m
        )
    )


def _extract_bad_action_from_error(message: str) -> str | None:
    marker = "Bad action:"
    i = message.find(marker)
    if i < 0:
        return None
    return message[i + len(marker) :].strip()


def _build_llm_planner_retry_prompt(
    *,
    milestone: Milestone,
    previous_prompt: str,
    bad_action: str,
    error_message: str,
) -> str:
    return (
        previous_prompt
        + "\n\nRETRY REQUIRED: the previous action list contained invalid Forge syntax.\n"
        + f"- Invalid action: {bad_action}\n"
        + f"- Parser error: {error_message}\n"
        + "Return a fresh full JSON action list using ONLY canonical Forge grammar.\n"
        + "Do not emit bounded edits unless the target file exists and you can provide exact @@FORGE@@ separators.\n"
        + "If creating a new file (especially under tests/), use write_file <path> | <full file body>.\n"
    )


def _parse_llm_actions_payload(parsed: dict, fallback_actions: list[str] | None) -> list[str]:
    if not isinstance(parsed, dict):
        raise ValueError("LLM planner output must be a JSON object.")
    actions_raw = parsed.get("actions")
    if not isinstance(actions_raw, list):
        if fallback_actions:
            return list(fallback_actions)
        raise ValueError("LLM planner output must include an 'actions' array.")
    return actions_raw
