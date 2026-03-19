# forge/vision.py

from forge.paths import Paths
from forge.repository import FileRepository

class VisionManager:
    @staticmethod
    def load_vision() -> str:
        return FileRepository.read_file(Paths.VISION_FILE)

    @staticmethod
    def save_vision(content: str) -> None:
        FileRepository.write_file(Paths.VISION_FILE, content)