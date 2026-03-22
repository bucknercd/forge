# forge/design_manager.py

from pathlib import Path
from forge.repository import FileRepository
from typing import List, Optional
from forge.paths import Paths
import re

class DesignManager:
    @staticmethod
    def load_document(path: Path) -> str:
        return FileRepository.read_file(path)

    @staticmethod
    def save_document(path: Path, content: str) -> None:
        FileRepository.write_file(path, content)

class Milestone:
    def __init__(
        self,
        id: int,
        title: str,
        objective: str,
        scope: str,
        validation: str,
        summary: str = "",
        depends_on: List[int] | None = None,
        forge_actions: List[str] | None = None,
        forge_validation: List[str] | None = None,
        forge_actions_with_lines: List[tuple[int, str]] | None = None,
        forge_validation_with_lines: List[tuple[int, str]] | None = None,
    ):
        self.id = id
        self.title = title
        self.objective = objective
        self.scope = scope
        self.validation = validation
        self.summary = summary
        self.depends_on = depends_on or []
        self.forge_actions = forge_actions or []
        self.forge_validation = forge_validation or []
        self.forge_actions_with_lines = forge_actions_with_lines or []
        self.forge_validation_with_lines = forge_validation_with_lines or []

    def __str__(self):
        return (
            f"Milestone {self.id}: {self.title}\n"
            f"Objective: {self.objective}\n"
            f"Scope: {self.scope}\n"
            f"Validation: {self.validation}"
        )

class MilestoneService:
    MILESTONE_HEADING_RE = re.compile(r"^##\s+Milestone\s+(\d+)\s*:\s+(.+)$")

    @staticmethod
    def _validate_milestones(milestones: List[Milestone]) -> None:
        for milestone in milestones:
            if not milestone.objective.strip():
                raise ValueError(
                    f"Milestone {milestone.id} is missing required objective field "
                    "(expected a line like '- **Objective**: <non-empty text>')."
                )
            if not milestone.scope.strip():
                raise ValueError(
                    f"Milestone {milestone.id} is missing required scope field "
                    "(expected a line like '- **Scope**: <non-empty text>')."
                )
            if not milestone.validation.strip():
                raise ValueError(
                    f"Milestone {milestone.id} is missing required validation field "
                    "(expected a line like '- **Validation**: <non-empty text>')."
                )

    @staticmethod
    def parse_milestones(content: str) -> List[Milestone]:
        milestones = []
        current_milestone = None

        for line in content.splitlines():
            line = line.strip()

            if line.startswith("## Milestone"):
                match = MilestoneService.MILESTONE_HEADING_RE.match(line)
                if not match:
                    raise ValueError(
                        f"Malformed milestone heading: '{line}'. "
                        "Expected format: '## Milestone <number>: <title>'."
                    )
                if current_milestone:
                    milestones.append(current_milestone)
                title = line[3:].strip()
                current_milestone = Milestone(
                    id=len(milestones) + 1,
                    title=title,
                    objective="",
                    scope="",
                    validation="",
                    summary="",
                )
            elif current_milestone and line.startswith("- **Objective**:"):
                current_milestone.objective = line.split(":", 1)[1].strip()
            elif current_milestone and line.startswith("- **Scope**:"):
                current_milestone.scope = line.split(":", 1)[1].strip()
            elif current_milestone and line.startswith("- **Validation**:"):
                current_milestone.validation = line.split(":", 1)[1].strip()
            elif current_milestone and line.startswith("- **Summary**:"):
                current_milestone.summary = line.split(":", 1)[1].strip()
            elif current_milestone and line.startswith("- **Depends On**:"):
                # Accept flexible formatting like: "1, 2", "[1,2]", "1"
                deps_text = line.split(":", 1)[1].strip()
                current_milestone.depends_on = [
                    int(m.group(0)) for m in re.finditer(r"\d+", deps_text)
                ]

        if current_milestone:
            milestones.append(current_milestone)

        MilestoneService._validate_milestones(milestones)
        for m in milestones:
            block, start_line = MilestoneService._milestone_block(content, m.id)
            m.forge_actions_with_lines = MilestoneService._parse_forge_list(
                block, "Forge Actions", block_start_line=start_line, milestone_id=m.id
            )
            m.forge_validation_with_lines = MilestoneService._parse_forge_list(
                block, "Forge Validation", block_start_line=start_line, milestone_id=m.id
            )
            m.forge_actions = [text for _, text in m.forge_actions_with_lines]
            m.forge_validation = [text for _, text in m.forge_validation_with_lines]
        return milestones

    @staticmethod
    def _milestone_block(content: str, milestone_id: int) -> tuple[str, int]:
        pattern = re.compile(
            rf"(?ms)^##\s+Milestone\s+{milestone_id}\s*:\s*.+?(?=^##\s+Milestone\s+\d+|\Z)"
        )
        m = pattern.search(content)
        if not m:
            return "", 1
        start_line = content[: m.start()].count("\n") + 1
        return m.group(0), start_line

    @staticmethod
    def _parse_forge_list(
        block: str,
        field: str,
        block_start_line: int,
        milestone_id: int,
    ) -> List[tuple[int, str]]:
        if not block:
            return []
        needle = f"- **{field}**:"
        idx = block.find(needle)
        if idx == -1:
            return []
        rest = block[idx + len(needle) :]
        header_line = block_start_line + block[:idx].count("\n")
        lines: List[tuple[int, str]] = []
        saw_non_empty = False
        current_chunks: List[str] = []
        current_start_line: int | None = None

        for i, line in enumerate(rest.splitlines(), start=1):
            line_no = header_line + i
            stripped = line.strip()
            if stripped.startswith("- **"):
                if current_chunks and current_start_line is not None:
                    lines.append(
                        (current_start_line, "\n".join(current_chunks).strip())
                    )
                current_chunks = []
                current_start_line = None
                break
            if stripped:
                saw_non_empty = True
            if stripped.startswith("- ") and not stripped.startswith("- **"):
                if current_chunks and current_start_line is not None:
                    lines.append(
                        (current_start_line, "\n".join(current_chunks).strip())
                    )
                current_chunks = [stripped[2:].strip()]
                current_start_line = line_no
            elif stripped == "":
                if current_chunks:
                    current_chunks.append("")
            elif stripped:
                if not current_chunks:
                    raise ValueError(
                        f"Milestone {milestone_id} malformed {field} at line {line_no}: "
                        "continuation line before first '- ' list item."
                    )
                current_chunks.append(stripped)

        if current_chunks and current_start_line is not None:
            lines.append((current_start_line, "\n".join(current_chunks).strip()))

        if saw_non_empty and not lines:
            raise ValueError(
                f"Milestone {milestone_id} malformed {field} near line {header_line}: "
                "no valid list items found."
            )
        return lines

    @staticmethod
    def list_milestones() -> List[Milestone]:
        content = FileRepository.read_file(Paths.MILESTONES_FILE)
        return MilestoneService.parse_milestones(content)

    @staticmethod
    def get_milestone(index: int) -> Optional[Milestone]:
        milestones = MilestoneService.list_milestones()
        if 1 <= index <= len(milestones):
            return milestones[index - 1]
        return None