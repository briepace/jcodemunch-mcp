"""Tests for JCODEMUNCH_EXTRA_EXTENSIONS env var handling."""

import pytest
from jcodemunch_mcp.parser.languages import (
    LANGUAGE_EXTENSIONS,
    _apply_extra_extensions,
)


@pytest.fixture(autouse=True)
def restore_extensions():
    """Restore LANGUAGE_EXTENSIONS to its original state after each test."""
    original = dict(LANGUAGE_EXTENSIONS)
    yield
    LANGUAGE_EXTENSIONS.clear()
    LANGUAGE_EXTENSIONS.update(original)


def test_valid_extra_extensions(monkeypatch):
    """Valid .ext:lang pairs are merged into LANGUAGE_EXTENSIONS."""
    monkeypatch.setenv("JCODEMUNCH_EXTRA_EXTENSIONS", ".cgi:perl,.psgi:perl")
    _apply_extra_extensions()
    assert LANGUAGE_EXTENSIONS[".cgi"] == "perl"
    assert LANGUAGE_EXTENSIONS[".psgi"] == "perl"


def test_unknown_language_skipped(monkeypatch, caplog):
    """Unknown language values are skipped with a WARNING log."""
    import logging
    monkeypatch.setenv("JCODEMUNCH_EXTRA_EXTENSIONS", ".xyz:cobol")
    with caplog.at_level(logging.WARNING):
        _apply_extra_extensions()
    assert ".xyz" not in LANGUAGE_EXTENSIONS
    assert any("cobol" in r.message or "cobol" in str(r.args) for r in caplog.records)


def test_malformed_entry_no_colon(monkeypatch, caplog):
    """Entry with no colon separator is skipped with a WARNING log."""
    import logging
    monkeypatch.setenv("JCODEMUNCH_EXTRA_EXTENSIONS", ".cgiperls")
    with caplog.at_level(logging.WARNING):
        _apply_extra_extensions()
    assert ".cgiperls" not in LANGUAGE_EXTENSIONS
    assert len(caplog.records) >= 1


def test_malformed_entry_empty_ext(monkeypatch, caplog):
    """Entry with empty extension is skipped with a WARNING log."""
    import logging
    monkeypatch.setenv("JCODEMUNCH_EXTRA_EXTENSIONS", ":perl")
    with caplog.at_level(logging.WARNING):
        _apply_extra_extensions()
    assert "" not in LANGUAGE_EXTENSIONS
    assert len(caplog.records) >= 1


def test_malformed_entry_empty_lang(monkeypatch, caplog):
    """Entry with empty language is skipped with a WARNING log."""
    import logging
    monkeypatch.setenv("JCODEMUNCH_EXTRA_EXTENSIONS", ".cgi:")
    with caplog.at_level(logging.WARNING):
        _apply_extra_extensions()
    assert ".cgi" not in LANGUAGE_EXTENSIONS
    assert len(caplog.records) >= 1


def test_empty_env_var(monkeypatch):
    """Absent or empty env var leaves LANGUAGE_EXTENSIONS unchanged."""
    monkeypatch.delenv("JCODEMUNCH_EXTRA_EXTENSIONS", raising=False)
    before = dict(LANGUAGE_EXTENSIONS)
    _apply_extra_extensions()
    assert LANGUAGE_EXTENSIONS == before


def test_whitespace_only_env_var(monkeypatch):
    """Whitespace-only env var leaves LANGUAGE_EXTENSIONS unchanged."""
    monkeypatch.setenv("JCODEMUNCH_EXTRA_EXTENSIONS", "   ")
    before = dict(LANGUAGE_EXTENSIONS)
    _apply_extra_extensions()
    assert LANGUAGE_EXTENSIONS == before


def test_override_builtin_extension(monkeypatch):
    """A valid entry can override an existing built-in extension mapping."""
    monkeypatch.setenv("JCODEMUNCH_EXTRA_EXTENSIONS", ".pl:python")
    _apply_extra_extensions()
    assert LANGUAGE_EXTENSIONS[".pl"] == "python"


def test_mixed_valid_and_invalid(monkeypatch, caplog):
    """Valid entries are applied even when mixed with invalid ones."""
    import logging
    monkeypatch.setenv(
        "JCODEMUNCH_EXTRA_EXTENSIONS",
        ".cgi:perl,.xyz:cobol,.psgi:perl,badentry"
    )
    with caplog.at_level(logging.WARNING):
        _apply_extra_extensions()
    assert LANGUAGE_EXTENSIONS[".cgi"] == "perl"
    assert LANGUAGE_EXTENSIONS[".psgi"] == "perl"
    assert ".xyz" not in LANGUAGE_EXTENSIONS
    assert len(caplog.records) >= 2


def test_extra_whitespace_in_entries(monkeypatch):
    """Leading/trailing whitespace in tokens is stripped."""
    monkeypatch.setenv("JCODEMUNCH_EXTRA_EXTENSIONS", " .cgi : perl , .psgi : perl ")
    _apply_extra_extensions()
    assert LANGUAGE_EXTENSIONS[".cgi"] == "perl"
    assert LANGUAGE_EXTENSIONS[".psgi"] == "perl"
