"""v1.108.81: get_watch_status skips the per-repo git identity probe when there
is no in-memory reindex state to look up.

reindex_state lives only in memory, populated by a watcher/server process. A cold
`list-repos` CLI process has none, so resolving each discovered folder's repo_id
key — a git identity probe (resolve_index_identity) via _reindex_key — yielded
nothing yet fanned out one git subprocess per repo, scaling `list-repos` to 60s+
on many-repo hosts. The probe is now gated on has_any_reindex_state().
"""

from jcodemunch_mcp.tools import get_watch_status as gws


class TestWatchStatusLazyKeyResolution:
    def test_skips_key_resolution_when_no_reindex_state(self, tmp_path, monkeypatch):
        folders = [str(tmp_path / "a"), str(tmp_path / "b"), str(tmp_path / "c")]
        monkeypatch.setattr(gws, "discover_local_repos", lambda sp=None: folders)
        monkeypatch.setattr(gws, "service_status", lambda: {"active": False})
        monkeypatch.setattr(gws.process_locks, "inspect", lambda *a, **k: None)
        monkeypatch.setattr(gws, "has_any_reindex_state", lambda: False)

        calls = []
        # _reindex_key is the git identity probe; it must NOT run on the cold path.
        monkeypatch.setattr(gws, "_reindex_key", lambda f, sp: calls.append(f) or f)

        def _boom(_k):
            raise AssertionError("get_reindex_status must not be consulted with no state")

        monkeypatch.setattr(gws, "get_reindex_status", _boom)

        out = gws.get_watch_status(str(tmp_path / "store"))

        assert calls == []  # zero git identity probes
        assert out["repo_count"] == 3
        assert out["any_stale"] is False
        # default freshness fields are still present so the output shape is stable
        assert all(e.get("index_stale") is False for e in out["repos"])
        assert all("reindex_in_progress" in e for e in out["repos"])

    def test_resolves_keys_when_reindex_state_present(self, tmp_path, monkeypatch):
        folder = str(tmp_path / "repo")
        monkeypatch.setattr(gws, "discover_local_repos", lambda sp=None: [folder])
        monkeypatch.setattr(gws, "service_status", lambda: {"active": False})
        monkeypatch.setattr(gws.process_locks, "inspect", lambda *a, **k: None)
        monkeypatch.setattr(gws, "has_any_reindex_state", lambda: True)

        calls = []
        monkeypatch.setattr(gws, "_reindex_key", lambda f, sp: calls.append(f) or "local/repo-abc123")
        monkeypatch.setattr(
            gws,
            "get_reindex_status",
            lambda k: {"index_stale": True, "reindex_in_progress": False, "stale_since_ms": 10},
        )

        out = gws.get_watch_status(str(tmp_path / "store"))

        assert calls == [folder]  # key resolved (probe runs) when state exists
        assert out["any_stale"] is True
        assert out["repos"][0]["index_stale"] is True
