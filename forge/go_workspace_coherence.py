"""
Deterministic checks for minimal Go workspace consistency under Forge-managed trees.

Catches common LLM failure modes: *_test.go without go.mod, tests-only trees, and
http.DefaultServeMux-based tests with no handler registration anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

# Match where Forge may write .go sources (same roots as safe_paths prefixes).
_GO_SCAN_DIR_NAMES = ("src", "tests", "examples", "scripts")

# Registration on default mux (http.HandleFunc) or on a typed mux (mux.HandleFunc).
_HANDLE_REGISTER_RE = re.compile(
    r"\bhttp\.HandleFunc\s*\(|\bhttp\.Handle\s*\(|\.HandleFunc\s*\(",
)


def iter_managed_go_files(base_dir: Path) -> list[Path]:
    """All *.go files under Forge-bounded code directories (non-recursive skip: rglob)."""
    found: list[Path] = []
    for name in _GO_SCAN_DIR_NAMES:
        root = base_dir / name
        if not root.is_dir():
            continue
        for p in root.rglob("*.go"):
            if p.is_file():
                found.append(p)
    return sorted(found)


def check_go_workspace_coherence(base_dir: Path) -> tuple[bool, str]:
    """
    If any managed .go file exists, require go.mod at repo root, non-test sources
    when tests exist, and handler registration when tests use http.DefaultServeMux.

    Returns (True, "") when checks pass or no Go files are present.
    """
    go_files = iter_managed_go_files(base_dir)
    if not go_files:
        return True, ""

    mod_path = base_dir / "go.mod"
    if not mod_path.is_file():
        rels = ", ".join(str(p.relative_to(base_dir)) for p in go_files[:5])
        more = f" (+{len(go_files) - 5} more)" if len(go_files) > 5 else ""
        return False, (
            "Go workspace coherence: found .go file(s) under src/, tests/, examples/, or "
            f"scripts/ ({rels}{more}) but no go.mod at the repository root ({mod_path}). "
            "Add write_file go.mod | module <name>\\n\\ngo 1.22\\n (adjust path/version) "
            "so `go test ./...` can run. Root go.mod is allowed by Forge path policy."
        )

    test_files = [p for p in go_files if p.name.endswith("_test.go")]
    impl_files = [p for p in go_files if not p.name.endswith("_test.go")]
    if test_files and not impl_files:
        tshow = ", ".join(str(p.relative_to(base_dir)) for p in test_files[:5])
        more = f" (+{len(test_files) - 5} more)" if len(test_files) > 5 else ""
        return False, (
            "Go workspace coherence: only *_test.go file(s) were found "
            f"({tshow}{more}) with no non-test .go implementation files under the same trees. "
            "Tests must target real code: add src/*.go (or scripts/*.go, etc.) that implements "
            "handlers or functions the tests exercise—do not ship tests alone."
        )

    mux_test_files: list[Path] = []
    chunks: list[str] = []
    for p in go_files:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        chunks.append(text)
        if p.name.endswith("_test.go") and "http.DefaultServeMux" in text:
            mux_test_files.append(p)

    if mux_test_files:
        blob = "\n".join(chunks)
        if not _HANDLE_REGISTER_RE.search(blob):
            shown = ", ".join(str(p.relative_to(base_dir)) for p in mux_test_files[:3])
            more = (
                f" (+{len(mux_test_files) - 3} more)" if len(mux_test_files) > 3 else ""
            )
            return False, (
                "Go workspace coherence: test file(s) reference http.DefaultServeMux "
                f"({shown}{more}) but no `http.HandleFunc`/`http.Handle` call was found in any "
                "managed .go file. Serving tests will 404 unless handlers are registered on the "
                "default mux. Fix by: (1) registering routes (e.g. in TestMain or init) before "
                "ServeHTTP, or (2) prefer testing a concrete http.Handler with "
                "httptest.NewRecorder without DefaultServeMux."
            )

    return True, ""
