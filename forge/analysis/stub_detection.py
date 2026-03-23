"""
Deterministic detection of structural CLI stubs (scaffold without core logic).

Used after Forge validation and repo tests pass to avoid false SUCCESS on
argument-parsing-only implementations.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

# Non-comment, non-blank lines below this suggest too little implementation for a typical tool.
TINY_LOC_THRESHOLD = 18

_DOMAIN_NAME_FRAGMENTS = (
    "parse",
    "count",
    "process",
    "analyze",
    "analyse",
    "aggregate",
    "compute",
    "summarize",
    "summarise",
    "filter",
    "extract",
    "load_log",
    "read_log",
    "handle",
    "ingest",
)


def _logical_line_count(content: str) -> int:
    n = 0
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        n += 1
    return n


def _is_name_main_guard(test: ast.AST) -> bool:
    """True for ``if __name__ == '__main__'`` (and common variants)."""
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    left = test.left
    comparators = test.comparators
    if len(comparators) != 1:
        return False
    if not isinstance(left, ast.Name) or left.id != "__name__":
        return False
    c0 = comparators[0]
    if isinstance(c0, ast.Constant) and isinstance(c0.value, str):
        return c0.value == "__main__"
    return False


class _Analysis(ast.NodeVisitor):
    def __init__(self) -> None:
        self.has_loop = False
        self.has_file_io = False
        self.has_meaningful_if = False

    def visit_For(self, node: ast.For) -> Any:
        self.has_loop = True
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> Any:
        self.has_loop = True
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> Any:
        self.has_loop = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "open":
            self.has_file_io = True
        elif isinstance(fn, ast.Attribute):
            if fn.attr in ("read", "read_text", "read_bytes", "open", "iterdir", "glob"):
                self.has_file_io = True
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> Any:
        for item in node.items:
            ctx = item.context_expr
            if isinstance(ctx, ast.Call):
                if isinstance(ctx.func, ast.Name) and ctx.func.id == "open":
                    self.has_file_io = True
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> Any:
        if not _is_name_main_guard(node.test):
            self.has_meaningful_if = True
        self.generic_visit(node)


def _domain_name_match(name: str) -> bool:
    lower = name.lower()
    return any(v in lower for v in _DOMAIN_NAME_FRAGMENTS)


def _collect_all_function_names(tree: ast.AST) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            out.append(node.name)
        elif isinstance(node, ast.AsyncFunctionDef):
            out.append(node.name)
    return out


def detect_missing_impl(file_path: str, content: str) -> dict[str, Any]:
    """
    Return ``{"is_stub": bool, "signals": [str], "confidence": float}``.

    Heuristic: combines tiny size, CLI-only scaffold, missing I/O, missing loops,
    missing domain-oriented function names, and main-only layout. Deterministic; no LLM.
    """
    signals: list[str] = []
    confidence = 0.0

    if not file_path.endswith(".py"):
        return {"is_stub": False, "signals": [], "confidence": 0.0}

    loc = _logical_line_count(content)
    if loc < TINY_LOC_THRESHOLD:
        signals.append("tiny_file")
        confidence += 0.32

    text_l = content.lower()
    cli_hint = "argparse" in text_l or "sys.argv" in text_l

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return {
            "is_stub": False,
            "signals": ["syntax_error_skip"],
            "confidence": 0.0,
        }

    analysis = _Analysis()
    analysis.visit(tree)

    all_names = _collect_all_function_names(tree)
    has_domain_fn = any(_domain_name_match(n) for n in all_names)

    top_defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    only_main_wrapper = len(top_defs) == 1 and top_defs[0] == "main"

    has_loop = analysis.has_loop
    has_file_io = analysis.has_file_io
    meaningful_if = analysis.has_meaningful_if

    # "Collections / processing": loop or comprehension
    has_comp = any(isinstance(n, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)) for n in ast.walk(tree))
    has_processing = has_loop or has_comp or meaningful_if

    only_cli_scaffold = cli_hint and not has_loop and not has_file_io
    if only_cli_scaffold:
        signals.append("only_cli_scaffold")
        confidence += 0.42

    if not has_file_io and (cli_hint or loc < 28):
        signals.append("no_file_io")
        confidence += 0.18

    if not has_processing:
        signals.append("no_processing_logic")
        confidence += 0.2

    if not has_domain_fn and len(all_names) > 0:
        signals.append("no_domain_functions")
        confidence += 0.14

    if only_main_wrapper and len(all_names) <= 2:
        signals.append("only_main_wrapper")
        confidence += 0.12

    confidence = min(1.0, round(confidence, 3))

    # Require at least one "structural" hint to avoid flagging tiny pure libs
    structural = bool(
        {s for s in signals} & {"only_cli_scaffold", "tiny_file", "only_main_wrapper"}
    )
    is_stub = structural and confidence >= 0.7

    return {
        "is_stub": is_stub,
        "signals": signals,
        "confidence": confidence,
    }


def should_analyze_path(file_path: str) -> bool:
    """Limit to Python under typical product roots (posix rel path or abs)."""
    p = file_path.replace("\\", "/")
    for prefix in ("examples/", "src/", "scripts/", "tests/"):
        if f"/{prefix}" in f"/{p}" or p.startswith(prefix):
            return p.endswith(".py")
    return False


def analyze_changed_python_files(
    files_changed: list[str],
    base_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Run :func:`detect_missing_impl` on each changed path that
    :func:`should_analyze_path` accepts.

    Returns ``(all_records, stub_records)`` where ``stub_records`` are entries with
    ``is_stub`` True and confidence >= 0.7.
    """
    all_records: list[dict[str, Any]] = []
    stub_records: list[dict[str, Any]] = []
    for raw in files_changed:
        p = Path(raw)
        try:
            rel = p.resolve().relative_to(base_dir.resolve()).as_posix()
        except Exception:
            rel = str(p)
        if not should_analyze_path(rel) and not should_analyze_path(str(p)):
            continue
        if not p.is_file():
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            continue
        result = detect_missing_impl(rel, content)
        rec = {
            "path": str(p),
            "rel_path": rel,
            "is_stub": result["is_stub"],
            "confidence": result["confidence"],
            "signals": list(result["signals"]),
        }
        all_records.append(rec)
        if result["is_stub"] and float(result["confidence"]) >= 0.7:
            stub_records.append(rec)
    return all_records, stub_records


def persist_stub_detection_results(
    base_dir: Path,
    run_id: str,
    records: list[dict[str, Any]],
) -> Path:
    """Write ``.artifacts/<run_id>/analysis/stub_detection.json`` under ``base_dir``."""
    root = base_dir / ".artifacts" / run_id / "analysis"
    root.mkdir(parents=True, exist_ok=True)
    out = root / "stub_detection.json"
    payload = {"run_id": run_id, "files": records}
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out
