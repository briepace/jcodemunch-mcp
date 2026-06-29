"""Tests for v1.108.84 — install-mechanism-aware `jcodemunch-mcp upgrade` (#357).

A pipx/uv-managed venv ships no `pip` module, so the old
`python -m pip install -U` died with `No module named pip` and skipped the
hook refresh. The fix: detect the mechanism, print the exact upgrade command
for it, and still refresh hooks/config in-process (needs no pip).
"""

from __future__ import annotations

from unittest import mock

from jcodemunch_mcp.cli import upgrade as up


class _FakeProc:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


# ---------------------------------------------------------------------------
# detect_install_mechanism
# ---------------------------------------------------------------------------


class TestDetectInstallMechanism:
    def test_pipx_venv_path(self):
        exe = "/Users/g-besoin/.local/pipx/venvs/jcodemunch-mcp/bin/python"
        with mock.patch.object(up.sys, "executable", exe), \
             mock.patch.dict(up.os.environ, {}, clear=True):
            mech, cmd = up.detect_install_mechanism()
        assert mech == "pipx"
        assert cmd == "pipx upgrade jcodemunch-mcp"

    def test_pipx_via_env(self):
        with mock.patch.object(up.sys, "executable", "/usr/bin/python3"), \
             mock.patch.dict(up.os.environ, {"PIPX_HOME": "/home/u/.local/pipx"}, clear=True):
            mech, cmd = up.detect_install_mechanism()
        assert mech == "pipx"

    def test_uv_tool_path(self):
        exe = "/home/u/.local/share/uv/tools/jcodemunch-mcp/bin/python"
        with mock.patch.object(up.sys, "executable", exe), \
             mock.patch.dict(up.os.environ, {}, clear=True):
            mech, cmd = up.detect_install_mechanism()
        assert mech == "uv"
        assert cmd == "uv tool upgrade jcodemunch-mcp"

    def test_uvx_cache_path(self):
        exe = "/home/u/.cache/uv/archive-v0/abc/bin/python"
        with mock.patch.object(up.sys, "executable", exe), \
             mock.patch.dict(up.os.environ, {}, clear=True):
            mech, cmd = up.detect_install_mechanism()
        assert mech == "uvx"
        assert cmd and cmd.startswith("uvx jcodemunch-mcp@latest")

    def test_plain_pip_when_pip_present(self):
        exe = "/usr/bin/python3"
        with mock.patch.object(up.sys, "executable", exe), \
             mock.patch.dict(up.os.environ, {}, clear=True), \
             mock.patch.object(up, "_pip_available", return_value=True):
            mech, cmd = up.detect_install_mechanism()
        assert mech == "pip"
        assert cmd is None


# ---------------------------------------------------------------------------
# run_upgrade
# ---------------------------------------------------------------------------


class TestRunUpgrade:
    def test_pipx_absent_pip_does_not_shell_to_pip_and_refreshes(self, capsys):
        """pipx env: never invoke pip, print pipx command, refresh hooks, rc=0."""
        with mock.patch.object(up, "_pip_available", return_value=False), \
             mock.patch.object(up, "detect_install_mechanism",
                               return_value=("pipx", "pipx upgrade jcodemunch-mcp")), \
             mock.patch.object(up, "_refresh_hooks", return_value=0) as refresh, \
             mock.patch.object(up.subprocess, "run") as sp_run:
            rc = up.run_upgrade()

        assert rc == 0
        # pip subprocess must NOT have been launched
        sp_run.assert_not_called()
        refresh.assert_called_once()
        out = capsys.readouterr().out
        assert "pipx upgrade jcodemunch-mcp" in out
        assert "pip is not available" in out

    def test_uv_absent_pip_prints_uv_command(self, capsys):
        with mock.patch.object(up, "_pip_available", return_value=False), \
             mock.patch.object(up, "detect_install_mechanism",
                               return_value=("uv", "uv tool upgrade jcodemunch-mcp")), \
             mock.patch.object(up, "_refresh_hooks", return_value=0), \
             mock.patch.object(up.subprocess, "run") as sp_run:
            rc = up.run_upgrade()
        assert rc == 0
        sp_run.assert_not_called()
        assert "uv tool upgrade jcodemunch-mcp" in capsys.readouterr().out

    def test_pip_present_runs_pip_then_refreshes(self):
        with mock.patch.object(up, "_pip_available", return_value=True), \
             mock.patch.object(up.subprocess, "run",
                               return_value=_FakeProc(0)) as sp_run, \
             mock.patch.object(up, "_refresh_hooks", return_value=0) as refresh:
            rc = up.run_upgrade()
        assert rc == 0
        # first subprocess call is the pip install
        pip_call = sp_run.call_args_list[0].args[0]
        assert pip_call[1:] == ["-m", "pip", "install", "-U", "jcodemunch-mcp"]
        refresh.assert_called_once()

    def test_pip_present_but_fails_still_refreshes_and_preserves_rc(self, capsys):
        with mock.patch.object(up, "_pip_available", return_value=True), \
             mock.patch.object(up.subprocess, "run",
                               return_value=_FakeProc(7)), \
             mock.patch.object(up, "_refresh_hooks", return_value=0) as refresh:
            rc = up.run_upgrade()
        # genuine pip failure code is preserved...
        assert rc == 7
        # ...but hooks were refreshed anyway
        refresh.assert_called_once()
        assert "refreshing hooks anyway" in capsys.readouterr().err

    def test_no_pip_skips_detection_and_pip(self):
        with mock.patch.object(up, "_pip_available") as pip_avail, \
             mock.patch.object(up, "detect_install_mechanism") as detect, \
             mock.patch.object(up.subprocess, "run") as sp_run, \
             mock.patch.object(up, "_refresh_hooks", return_value=0) as refresh:
            rc = up.run_upgrade(no_pip=True)
        assert rc == 0
        pip_avail.assert_not_called()
        detect.assert_not_called()
        sp_run.assert_not_called()
        refresh.assert_called_once()

    def test_refresh_failure_propagates_when_pip_absent(self):
        with mock.patch.object(up, "_pip_available", return_value=False), \
             mock.patch.object(up, "detect_install_mechanism",
                               return_value=("pipx", "pipx upgrade jcodemunch-mcp")), \
             mock.patch.object(up, "_refresh_hooks", return_value=3), \
             mock.patch.object(up.subprocess, "run"):
            rc = up.run_upgrade()
        assert rc == 3
