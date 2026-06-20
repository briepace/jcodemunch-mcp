"""v1.108.64 — logging honors the log_file / log_level config keys.

`_setup_logging` previously read only the CLI flag / env var, so a value set via
`config set log_file <path>` was inert. `_resolve_log_config` now applies a full
precedence chain (CLI flag > env var > config key > hardcoded default) so the
config can drive logging (e.g. when the jMunch Console enables it) while an
explicit env/CLI from the launching client still wins.
"""
from types import SimpleNamespace

import pytest

from jcodemunch_mcp import config as config_module
from jcodemunch_mcp.server import _resolve_log_config


def _args(log_level=None, log_file=None):
    return SimpleNamespace(log_level=log_level, log_file=log_file)


@pytest.fixture
def cfg(monkeypatch):
    """Replace config.get with a dict-backed stub honoring the passed default."""
    store: dict = {}

    def fake_get(key, default=None, repo=None):
        return store.get(key, default)

    monkeypatch.setattr(config_module, "get", fake_get)
    # A clean env so the precedence chain is exercised deterministically.
    monkeypatch.delenv("JCODEMUNCH_LOG_LEVEL", raising=False)
    monkeypatch.delenv("JCODEMUNCH_LOG_FILE", raising=False)
    return store


def test_default_when_nothing_set(cfg):
    # No CLI, no env, config returns the defaults → WARNING + stderr (None).
    assert _resolve_log_config(_args()) == ("WARNING", None)


def test_config_log_file_drives_logging(cfg):
    cfg["log_file"] = "/var/log/jcm.log"
    level, log_file = _resolve_log_config(_args())
    assert log_file == "/var/log/jcm.log"
    assert level == "WARNING"  # untouched


def test_config_log_level_honored(cfg):
    cfg["log_level"] = "INFO"
    cfg["log_file"] = "/var/log/jcm.log"
    assert _resolve_log_config(_args()) == ("INFO", "/var/log/jcm.log")


def test_env_overrides_config(cfg, monkeypatch):
    cfg["log_file"] = "/from/config.log"
    cfg["log_level"] = "ERROR"
    monkeypatch.setenv("JCODEMUNCH_LOG_FILE", "/from/env.log")
    monkeypatch.setenv("JCODEMUNCH_LOG_LEVEL", "DEBUG")
    assert _resolve_log_config(_args()) == ("DEBUG", "/from/env.log")


def test_cli_flag_wins(cfg, monkeypatch):
    cfg["log_file"] = "/from/config.log"
    monkeypatch.setenv("JCODEMUNCH_LOG_FILE", "/from/env.log")
    monkeypatch.setenv("JCODEMUNCH_LOG_LEVEL", "DEBUG")
    level, log_file = _resolve_log_config(_args(log_level="ERROR", log_file="/from/cli.log"))
    assert log_file == "/from/cli.log"
    assert level == "ERROR"


def test_level_name_is_uppercased(cfg):
    cfg["log_level"] = "info"
    assert _resolve_log_config(_args())[0] == "INFO"
