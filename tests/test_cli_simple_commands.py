"""Tests for simplified CLI entry points (build, fix, start, doctor, logs)."""

from __future__ import annotations

import json

from forge.cli import ForgeCLI, main
from forge.paths import Paths


def test_cli_build_routes_to_vertical_slice_demo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["forge", "build", "--json"])
    rc = main()
    assert rc in (0, 1)
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload.get("command") == "vertical-slice"
    assert "stages" in payload


def test_cli_fix_aliases_run_next(tmp_path, monkeypatch, capsys):
    """`forge fix` should dispatch to the same handler as run-next."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    capsys.readouterr()
    called = {"n": 0}

    def fake_execute_next():
        called["n"] += 1
        print("executed-next-stub")

    monkeypatch.setattr(ForgeCLI, "execute_next", staticmethod(fake_execute_next))
    monkeypatch.setattr("sys.argv", ["forge", "fix"])
    Paths.refresh(tmp_path)
    main()
    assert called["n"] == 1


def test_cli_doctor_runs_without_full_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "doctor"])
    rc = main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Forge doctor" in out
