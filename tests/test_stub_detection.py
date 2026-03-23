"""Unit tests for deterministic stub / missing-implementation detection."""

from __future__ import annotations

from forge.analysis.stub_detection import detect_missing_impl


def test_cli_only_skeleton_flagged_as_stub() -> None:
    content = '''
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Log check")
    parser.add_argument("path")
    args = parser.parse_args()
    print("usage:", args.path)
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
    r = detect_missing_impl("examples/logcheck.py", content)
    assert r["is_stub"] is True
    assert r["confidence"] >= 0.7
    assert "only_cli_scaffold" in r["signals"]
    assert "no_file_io" in r["signals"]
    assert "no_processing_logic" in r["signals"]


def test_real_impl_with_loop_and_file_read_not_stub() -> None:
    content = '''
import argparse
import sys

def count_errors(path: str) -> int:
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "ERROR" in line:
                n += 1
    return n

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path")
    args = p.parse_args()
    print(count_errors(args.path))
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
    r = detect_missing_impl("examples/logcheck.py", content)
    assert r["is_stub"] is False
    assert "only_cli_scaffold" not in r["signals"]


def test_medium_file_with_processing_logic_not_stub() -> None:
    content = '''
import sys

def aggregate(values):
    total = 0
    for v in values:
        total += v
    if total > 100:
        return total // 2
    return total

def main():
    print(aggregate([10, 20, 30, 5, 5, 5, 5, 5, 5, 5]))
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
    r = detect_missing_impl("scripts/sum_tool.py", content)
    assert r["is_stub"] is False


def test_go_todo_stub_flagged_as_suspicious() -> None:
    content = """
package main

func CountErrors(lines []string) int {
    panic("TODO")
}
"""
    r = detect_missing_impl("src/logcheck.go", content)
    assert "go_todo_stub" in r["signals"]
    assert r["is_stub"] is True or r["confidence"] >= 0.6


def test_terraform_placeholder_only_flagged() -> None:
    content = """
# TODO: implement terraform module
# placeholder only
"""
    r = detect_missing_impl("infra/main.tf", content)
    assert "tf_placeholder_only" in r["signals"] or "no_meaningful_terraform_blocks" in r["signals"]
    assert r["is_stub"] is True or r["confidence"] >= 0.6
