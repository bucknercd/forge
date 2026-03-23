"""Regression: repo root on sys.path so `from src...` works under pytest."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def test_repo_root_is_on_sys_path() -> None:
    root = Path(__file__).resolve().parents[1]
    assert str(root) in sys.path, "tests/conftest.py should insert repo root into sys.path"


def test_src_style_import_works_when_src_package_exists(tmp_path) -> None:
    """
    Mimics generated projects: with repo root on sys.path, `import src.mod` resolves.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "mod.py").write_text("X = 42\n", encoding="utf-8")

    root = str(tmp_path.resolve())
    if root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)

    try:
        spec = importlib.util.find_spec("src.mod")
        assert spec is not None
        mod = importlib.import_module("src.mod")
        assert mod.X == 42
    finally:
        sys.path.remove(root)
        for key in list(sys.modules):
            if key == "src" or key.startswith("src."):
                del sys.modules[key]
