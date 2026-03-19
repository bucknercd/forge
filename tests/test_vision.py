# tests/test_vision.py

import pytest
from forge.vision import VisionManager
from forge.paths import Paths
from pathlib import Path

def test_load_vision(tmp_path):
    # Create a temporary vision file
    vision_file = tmp_path / "vision.txt"
    vision_file.write_text("Test Vision Content")

    # Override the path for testing
    original_path = Paths.VISION_FILE
    Paths.VISION_FILE = vision_file

    try:
        # Load the vision content
        content = VisionManager.load_vision()
        assert content == "Test Vision Content"
    finally:
        # Restore the original path
        Paths.VISION_FILE = original_path

def test_save_vision(tmp_path):
    # Create a temporary vision file
    vision_file = tmp_path / "vision.txt"

    # Override the path for testing
    original_path = Paths.VISION_FILE
    Paths.VISION_FILE = vision_file

    try:
        # Save vision content
        VisionManager.save_vision("New Vision Content")
        assert vision_file.read_text() == "New Vision Content"
    finally:
        # Restore the original path
        Paths.VISION_FILE = original_path