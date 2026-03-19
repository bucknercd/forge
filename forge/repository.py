# forge/repository.py

from pathlib import Path

class FileRepository:
    @staticmethod
    def read_file(path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def write_file(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def append_to_file(path: Path, content: str) -> None:
        with path.open("a", encoding="utf-8") as file:
            file.write(content + "\n")