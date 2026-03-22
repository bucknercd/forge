"""Tests for validation substring unquoting (path_file_contains / file_contains needles)."""

from __future__ import annotations

import pytest

from forge.execution.parse import parse_forge_validation_line
from forge.execution.validation_rules import (
    RuleFileContains,
    RulePathFileContains,
    validate_rule,
)
from forge.execution.validation_substring_parse import parse_validation_needle


def test_parse_needle_single_quotes_strips_outer_quotes() -> None:
    r = parse_validation_needle("'def count_errors'")
    assert r.needle == "def count_errors"
    assert r.quote_style == "single"
    assert r.raw_input == "'def count_errors'"


def test_parse_needle_double_quotes_strips_outer_quotes() -> None:
    r = parse_validation_needle('"def count_errors"')
    assert r.needle == "def count_errors"
    assert r.quote_style == "double"


def test_parse_needle_double_quotes_escapes() -> None:
    r = parse_validation_needle(r'"a\"b\\c"')
    assert r.needle == 'a"b\\c'
    r2 = parse_validation_needle(r'"\nline"')
    assert r2.needle == "\nline"


def test_parse_needle_unquoted_unchanged() -> None:
    r = parse_validation_needle("def count_errors")
    assert r.needle == "def count_errors"
    assert r.quote_style == "none"


def test_parse_needle_unquoted_preserves_internal_apostrophe() -> None:
    r = parse_validation_needle("it's fine")
    assert r.needle == "it's fine"


def test_parse_needle_malformed_unclosed_single() -> None:
    with pytest.raises(ValueError, match="unclosed single"):
        parse_validation_needle("'def")


def test_parse_needle_malformed_mismatched_quotes() -> None:
    with pytest.raises(ValueError, match="mismatched|unclosed"):
        parse_validation_needle("'def\"")


def test_parse_needle_single_quote_inner_forbidden() -> None:
    with pytest.raises(ValueError, match="single-quoted substring cannot contain"):
        parse_validation_needle("""'it's'""")


def test_path_file_contains_line_single_quoted() -> None:
    rule = parse_forge_validation_line(
        "path_file_contains src/logcheck.py 'def count_errors'"
    )
    assert isinstance(rule, RulePathFileContains)
    assert rule.rel_path == "src/logcheck.py"
    assert rule.substring == "def count_errors"
    assert rule.substring_quote_style == "single"
    assert rule.substring_input == "'def count_errors'"


def test_path_file_contains_line_double_quoted() -> None:
    rule = parse_forge_validation_line(
        'path_file_contains src/logcheck.py "def count_errors"'
    )
    assert isinstance(rule, RulePathFileContains)
    assert rule.substring == "def count_errors"
    assert rule.substring_quote_style == "double"


def test_path_file_contains_line_unquoted_still_works() -> None:
    rule = parse_forge_validation_line(
        "path_file_contains src/logcheck.py def count_errors"
    )
    assert isinstance(rule, RulePathFileContains)
    assert rule.substring == "def count_errors"
    assert rule.substring_quote_style == "none"


def test_file_contains_quoted_needle() -> None:
    rule = parse_forge_validation_line(
        "file_contains requirements 'Vertical slice marker'"
    )
    assert isinstance(rule, RuleFileContains)
    assert rule.substring == "Vertical slice marker"
    assert rule.substring_quote_style == "single"


def test_parse_forge_validation_stable_roundtrip_repr() -> None:
    line = "path_file_contains src/logcheck.py 'def count_errors'"
    r1 = parse_forge_validation_line(line)
    r2 = parse_forge_validation_line(line)
    assert r1 == r2


def test_validate_rule_path_file_contains_passes_without_quotes_in_file(
    tmp_path,
) -> None:
    """Regression: file has `def count_errors` but validation line used quotes."""

    root = tmp_path / "proj"
    root.mkdir()
    sub = root / "src"
    sub.mkdir(parents=True)
    f = sub / "logcheck.py"
    f.write_text("def count_errors(log_file):\n    return 0\n", encoding="utf-8")

    class Paths:
        BASE_DIR = root

    rule = parse_forge_validation_line(
        "path_file_contains src/logcheck.py 'def count_errors'"
    )
    ok, msg = validate_rule(rule, Paths)
    assert ok, msg


def test_validate_rule_failure_includes_diag(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "logcheck.py").write_text("pass\n", encoding="utf-8")

    class Paths:
        BASE_DIR = root

    rule = parse_forge_validation_line(
        "path_file_contains src/logcheck.py 'def count_errors'"
    )
    ok, msg = validate_rule(rule, Paths)
    assert not ok
    assert "def count_errors" in msg
    assert "unquote_applied=yes" in msg
    assert "raw_substring_field=" in msg
