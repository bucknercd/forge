# forge/design_manager.py

from pathlib import Path
from forge.repository import FileRepository
from typing import List, Optional
from forge.paths import Paths

class DesignManager:
    @staticmethod
    def load_document(path: Path) -> str:
        return FileRepository.read_file(path)

    @staticmethod
    def save_document(path: Path, content: str) -> None:
        FileRepository.write_file(path, content)

class Milestone:
    def __init__(self, id: int, title: str, objective: str, scope: str, validation: str):
        self.id = id
        self.title = title
        self.objective = objective
        self.scope = scope
        self.validation = validation

    def __str__(self):
        return f"Milestone {self.id}: {self.title}\nObjective: {self.objective}\nScope: {self.scope}\nValidation: {self.validation}"

class MilestoneService:
    @staticmethod
    def parse_milestones(content: str) -> List[Milestone]:
        milestones = []
        current_milestone = None

        for line in content.splitlines():
            line = line.strip()

            if line.startswith("## Milestone"):
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

        if current_milestone:
            milestones.append(current_milestone)

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