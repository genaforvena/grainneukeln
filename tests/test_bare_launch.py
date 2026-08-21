"""The double-click path: a bare invocation must OPEN the app, not print usage.

Why this test exists: the released bundle is a console executable, so a friend
who double-clicks it in Finder gets whatever `main.py` with no arguments does.
It used to print argparse's help and exit 1 -- a window that flashes a wall of
flags and closes, which reads as "the program is broken" to anyone who did not
write it.  Nothing in the repo asserted otherwise, and no test could have caught
it, because the behaviour lived in an `elif` at the bottom of `__main__`.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main as main_mod  # noqa: E402


def test_falls_through_to_the_tui_when_no_gui_is_bundled(monkeypatch):
    """macOS ships without PySide6 (10.13 floor vs PySide6's macOS 12+ wheels),
    so on THAT build the ladder's second rung is the whole app."""
    calls = []
    monkeypatch.setattr(main_mod, "launch_gui", lambda: None)
    fake_tui = type(sys)("tui.app")
    fake_tui.run_tui = lambda: calls.append("tui")
    monkeypatch.setitem(sys.modules, "tui.app", fake_tui)

    assert main_mod.launch_best_ui() == 0
    assert calls == ["tui"], "no GUI in the bundle must open the TUI, not a usage screen"


def test_prefers_the_gui_when_it_is_there(monkeypatch):
    monkeypatch.setattr(main_mod, "launch_gui", lambda: 0)
    fake_tui = type(sys)("tui.app")
    fake_tui.run_tui = lambda: pytest.fail("GUI was available; the TUI must not be reached")
    monkeypatch.setitem(sys.modules, "tui.app", fake_tui)
    assert main_mod.launch_best_ui() == 0


def test_reports_rather_than_pretending_when_neither_ui_exists(monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "launch_gui", lambda: None)
    broken = type(sys)("tui.app")   # a module with no run_tui -> AttributeError on import-from
    monkeypatch.setitem(sys.modules, "tui.app", broken)
    assert main_mod.launch_best_ui() is None
    assert "terminal UI is unavailable" in capsys.readouterr().out


def test_a_wrong_invocation_still_gets_the_help_screen():
    """The fallback is for the BARE case only.  Someone at a prompt who typed a
    half-command must still be told what the flags are."""
    proc = subprocess.run(
        [sys.executable, "main.py", "--seed", "1"],
        cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 1
    assert "usage:" in (proc.stdout + proc.stderr).lower()
