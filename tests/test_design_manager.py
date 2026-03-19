# tests/test_design_manager.py

import pytest
from forge.design_manager import DesignManager
from pathlib import Path

def test_load_document(tmp_path):
    # Create a temporary document
    doc_file = tmp_path / "test_doc.md"
    doc_file.write_text("Test Document Content")

    # Load the document
    content = DesignManager.load_document(doc_file)
    assert content == "Test Document Content"

def test_save_document(tmp_path):
    # Create a temporary document path
    doc_file = tmp_path / "test_doc.md"

    # Save content to the document
    DesignManager.save_document(doc_file, "New Document Content")
    assert doc_file.read_text() == "New Document Content"