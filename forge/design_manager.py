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
        depends_on: List[int] | None = None,
    ):
        self.id = id
        self.title = title
        self.objective = objective
        self.scope = scope
        self.validation = validation
        self.depends_on = depends_on or []

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
                    f"Milestone {milestone.id} is missing required objective field."
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
                )
            elif current_milestone and line.startswith("- **Objective**:"):
                current_milestone.objective = line.split(":", 1)[1].strip()
            elif current_milestone and line.startswith("- **Scope**:"):
                current_milestone.scope = line.split(":", 1)[1].strip()
            elif current_milestone and line.startswith("- **Validation**:"):
                current_milestone.validation = line.split(":", 1)[1].strip()
            elif current_milestone and line.startswith("- **Depends On**:"):
                # Accept flexible formatting like: "1, 2", "[1,2]", "1"
                deps_text = line.split(":", 1)[1].strip()
                current_milestone.depends_on = [
                    int(m.group(0)) for m in re.finditer(r"\d+", deps_text)
                ]

        if current_milestone:
            milestones.append(current_milestone)

        MilestoneService._validate_milestones(milestones)
        return milestones

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