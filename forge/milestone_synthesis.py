from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from forge.design_manager import MilestoneService
from forge.llm import LLMClient
from forge.paths import Paths


def reviewed_milestones_dir() -> Path:
    return Paths.SYSTEM_DIR / "reviewed_milestones"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return _sha256_text(path.read_text(encoding="utf-8"))


def _doc_excerpt(path: Path, *, max_chars: int = 2000) -> str:
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


def build_milestone_synthesis_prompt(*, desired_count: int) -> str:
    req = _doc_excerpt(Paths.REQUIREMENTS_FILE)
    arch = _doc_excerpt(Paths.ARCHITECTURE_FILE)
    dec = _doc_excerpt(Paths.DECISIONS_FILE)
    existing = _doc_excerpt(Paths.MILESTONES_FILE)
    return (
        "Synthesize the next Forge milestones for this repository.\n"
        "Return ONLY valid JSON with exact shape:\n"
        "{\"milestones\":[{\"title\":\"...\",\"objective\":\"...\",\"scope\":\"...\",\"validation\":\"...\"}]}\n\n"
        "Constraints:\n"
        f"- Produce 1 to {desired_count} milestones.\n"
        "- Keep each field concise and actionable.\n"
        "- Do not include markdown, comments, or extra keys.\n"
        "- The milestones must be independent from IDs; IDs are assigned by Forge.\n\n"
        "Repository context excerpts:\n"
        f"=== requirements.md ===\n{req}\n\n"
        f"=== architecture.md ===\n{arch}\n\n"
        f"=== decisions.md ===\n{dec}\n\n"
        f"=== milestones.md (current) ===\n{existing}\n"
    )


def parse_synthesized_milestones(raw: str, *, desired_count: int) -> tuple[list[dict[str, str]], list[str]]:
    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Synthesized milestones response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Synthesized milestones response must be a JSON object.")
    items = parsed.get("milestones")
    if not isinstance(items, list):
        raise ValueError("Synthesized milestones response must include a 'milestones' array.")
    if not items:
        raise ValueError("Synthesized milestones response has no milestones.")

    out: list[dict[str, str]] = []
    warnings: list[str] = []
    if len(items) > desired_count:
        warnings.append(
            f"Provider returned {len(items)} milestones; expected at most {desired_count}."
        )
    seen_titles: set[str] = set()
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Synthesized milestone {idx} must be an object.")
        title = str(item.get("title", "")).strip()
        objective = str(item.get("objective", "")).strip()
        scope = str(item.get("scope", "")).strip()
        validation = str(item.get("validation", "")).strip()
        if not title:
            raise ValueError(f"Synthesized milestone {idx} missing required 'title'.")
        if not objective:
            raise ValueError(f"Synthesized milestone {idx} missing required 'objective'.")
        if not scope:
            raise ValueError(f"Synthesized milestone {idx} missing required 'scope'.")
        if not validation:
            raise ValueError(f"Synthesized milestone {idx} missing required 'validation'.")
        if len(title) > 160:
            raise ValueError(f"Synthesized milestone {idx} title too long (>160 chars).")
        tkey = title.lower()
        if tkey in seen_titles:
            raise ValueError(f"Synthesized milestones include duplicate title '{title}'.")
        seen_titles.add(tkey)
        out.append(
            {
                "title": title,
                "objective": objective,
                "scope": scope,
                "validation": validation,
            }
        )
    return out, warnings


def _format_markdown_block(milestones: list[dict[str, str]], *, start_id: int) -> str:
    lines: list[str] = []
    for i, m in enumerate(milestones, start=start_id):
        lines.extend(
            [
                f"## Milestone {i}: {m['title']}",
                f"- **Objective**: {m['objective']}",
                f"- **Scope**: {m['scope']}",
                f"- **Validation**: {m['validation']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def synthesize_milestones(
    llm_client: LLMClient,
    *,
    desired_count: int = 3,
) -> dict[str, Any]:
    prompt = build_milestone_synthesis_prompt(desired_count=desired_count)
    raw = llm_client.generate(prompt)
    milestones, warnings = parse_synthesized_milestones(raw, desired_count=desired_count)

    existing = MilestoneService.list_milestones()
    preview_markdown = _format_markdown_block(milestones, start_id=len(existing) + 1)
    # Sanity-check parseability with existing parser before persisting.
    _ = MilestoneService.parse_milestones("# Milestones\n\n" + preview_markdown)

    reviewed_milestones_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "milestone_synthesis",
        "created_at": datetime.now().isoformat(),
        "planner_metadata": {
            "mode": "llm",
            "is_nondeterministic": True,
            "llm_client": getattr(llm_client, "client_id", "unknown"),
            "llm_model": getattr(llm_client, "model_name", None),
        },
        "warnings": warnings,
        "desired_count": desired_count,
        "source_hashes": {
            "requirements": _file_hash(Paths.REQUIREMENTS_FILE),
            "architecture": _file_hash(Paths.ARCHITECTURE_FILE),
            "decisions": _file_hash(Paths.DECISIONS_FILE),
            "milestones": _file_hash(Paths.MILESTONES_FILE),
        },
        "milestones": milestones,
        "markdown_preview": preview_markdown,
    }
    synthesis_id = _sha256_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )[:12]
    payload["synthesis_id"] = synthesis_id
    path = reviewed_milestones_dir() / f"{synthesis_id}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def load_synthesized_milestones(synthesis_id: str) -> dict[str, Any] | None:
    path = reviewed_milestones_dir() / f"{synthesis_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def accept_synthesized_milestones(synthesis_id: str) -> dict[str, Any]:
    payload = load_synthesized_milestones(synthesis_id)
    if payload is None:
        return {"ok": False, "message": f"Synthesized milestone artifact '{synthesis_id}' not found."}
    if payload.get("source_hashes", {}).get("milestones") != _file_hash(Paths.MILESTONES_FILE):
        return {
            "ok": False,
            "message": "milestones.md changed since synthesis. Re-run milestone-synthesize.",
            "synthesis_id": synthesis_id,
        }
    milestones = payload.get("milestones", [])
    if not isinstance(milestones, list) or not milestones:
        return {"ok": False, "message": "Synthesized artifact has no milestones.", "synthesis_id": synthesis_id}

    existing_text = Paths.MILESTONES_FILE.read_text(encoding="utf-8")
    existing = MilestoneService.list_milestones()
    block = _format_markdown_block(milestones, start_id=len(existing) + 1)
    new_text = existing_text.rstrip() + "\n\n" + block
    # Validate merged output before write.
    _ = MilestoneService.parse_milestones(new_text)
    Paths.MILESTONES_FILE.write_text(new_text, encoding="utf-8")
    return {
        "ok": True,
        "synthesis_id": synthesis_id,
        "accepted_count": len(milestones),
        "message": f"Accepted {len(milestones)} synthesized milestone(s).",
    }
