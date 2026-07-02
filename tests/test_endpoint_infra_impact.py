"""Tests for endpoint-scoped infra blast radius (get_endpoint_impact include_infra).

P1 of docs/prd-endpoint-infra-impact.md: collect_project_intel factor-out +
downstream fusion. Fixture repos follow the test_endpoint_impact pattern.
"""

from jcodemunch_mcp.tools.index_folder import index_folder
from jcodemunch_mcp.tools.get_endpoint_impact import (
    get_endpoint_impact,
    _classify_cross_ref_source,
    _infra_for_impact,
)
from jcodemunch_mcp.tools.get_project_intel import (
    get_project_intel,
    collect_project_intel,
)


def _index(src, store):
    result = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
    assert result["success"] is True
    return result["repo"], str(store)


def _flask_repo_with_infra(tmp_path):
    """Flask handler + Dockerfile ENTRYPOINT naming its file + compose build context."""
    src = tmp_path / "src"
    store = tmp_path / "store"
    src.mkdir()
    store.mkdir()
    (src / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.get('/users')\n"
        "def list_users():\n"
        "    return []\n"
    )
    (src / "Dockerfile").write_text(
        "FROM python:3.12-slim\n"
        "COPY app.py /srv/app.py\n"
        "ENTRYPOINT [\"python\", \"app.py\"]\n"
    )
    (src / ".env.example").write_text("DATABASE_URL=postgres://localhost/dev\n")
    return _index(src, store)


def _compose_subdir_repo(tmp_path):
    """Handler under api/ with a compose service whose build context is ./api."""
    src = tmp_path / "src"
    store = tmp_path / "store"
    api = src / "api"
    api.mkdir(parents=True)
    store.mkdir()
    (api / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.get('/orders')\n"
        "def list_orders():\n"
        "    return []\n"
    )
    (src / "docker-compose.yml").write_text(
        "services:\n"
        "  api:\n"
        "    build: ./api\n"
        "    ports:\n"
        "      - '8000:8000'\n"
    )
    return _index(src, store)


def _plain_repo(tmp_path):
    """Handler with no IaC anywhere in the tree."""
    src = tmp_path / "src"
    store = tmp_path / "store"
    src.mkdir()
    store.mkdir()
    (src / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.get('/ping')\n"
        "def ping():\n"
        "    return 'pong'\n"
    )
    return _index(src, store)


# --- pure helpers -----------------------------------------------------------

def test_classify_cross_ref_source():
    assert _classify_cross_ref_source("env:DATABASE_URL") == ("env", "DATABASE_URL")
    assert _classify_cross_ref_source("compose:db") == ("compose", "db")
    assert _classify_cross_ref_source("ci:.github/workflows/test.yml:build") == (
        "ci", ".github/workflows/test.yml:build")
    assert _classify_cross_ref_source("script:lint") == ("script", "lint")
    assert _classify_cross_ref_source("Dockerfile:ENTRYPOINT") == ("docker", "Dockerfile:ENTRYPOINT")
    assert _classify_cross_ref_source("docker/api.dockerfile:COPY") == (
        "docker", "docker/api.dockerfile:COPY")
    assert _classify_cross_ref_source("weird") == ("other", "weird")


def test_infra_for_impact_intersection_and_dedupe():
    impact = {
        "handler": {"file": "api/app.py"},
        "affected_files": ["api/db.py", "./api/models.py"],
        "rendered_views": [{"template": "users.html", "file": "templates/users.html"}],
    }
    cross_refs = [
        # env var hits two blast files -> ONE deduped row
        {"source": "env:DATABASE_URL", "target_file": "api/db.py", "type": "env_usage"},
        {"source": "env:DATABASE_URL", "target_file": "api/models.py", "type": "env_usage"},
        # directory-target (build_context) prefix-matches blast files
        {"source": "compose:api", "target_file": "api", "type": "build_context"},
        # outside the blast radius -> excluded
        {"source": "env:REDIS_URL", "target_file": "worker/jobs.py", "type": "env_usage"},
        # rendered view file counts as blast
        {"source": "ci:.github/workflows/ui.yml:build", "target_file": "templates/users.html",
         "type": "ci_target"},
    ]
    infra = _infra_for_impact(impact, cross_refs)
    keys = {(d["category"], d["label"]) for d in infra["downstream"]}
    assert ("env", "DATABASE_URL") in keys
    assert ("compose", "api") in keys
    assert ("ci", ".github/workflows/ui.yml:build") in keys
    assert ("env", "REDIS_URL") not in keys
    assert len([d for d in infra["downstream"] if d["label"] == "DATABASE_URL"]) == 1
    assert infra["exposes"] == []
    assert infra["_meta"]["cross_refs_scanned"] == 5
    assert infra["_meta"]["blast_radius_files"] == 4


# --- factor-out equivalence -------------------------------------------------

def test_collect_matches_tool_response(tmp_path):
    """get_project_intel's public fields come verbatim from collect_project_intel."""
    repo, store = _flask_repo_with_infra(tmp_path)
    full = get_project_intel(repo, storage_path=store)
    assert "error" not in full

    from jcodemunch_mcp.storage import IndexStore
    from jcodemunch_mcp.tools._utils import resolve_repo
    owner, name = resolve_repo(repo, store)
    index = IndexStore(base_path=store).load_index(owner, name)
    collected = collect_project_intel(index, index.source_root)

    assert full["categories"] == collected["categories"]
    assert full["cross_references"] == collected["cross_references"]
    assert full["file_count"] == collected["file_count"]
    assert full["category_count"] == collected["category_count"]
    # the fixture's Dockerfile must actually be discovered
    assert full["categories"]["infra"]["dockerfiles"]


def test_collect_single_category_api(tmp_path):
    """Index-only categories still work through the factored path."""
    repo, store = _plain_repo(tmp_path)
    res = get_project_intel(repo, category="api", storage_path=store)
    assert "error" not in res
    assert set(res["categories"].keys()) == {"api"}


def test_collect_missing_source_root_is_empty():
    collected = collect_project_intel(None, "/does/not/exist-xyz")
    assert collected["cross_references"] == []
    assert collected["categories"] == {}
    assert collected["file_count"] == 0


# --- downstream fusion end-to-end -------------------------------------------

def test_dockerfile_entrypoint_downstream(tmp_path):
    repo, store = _flask_repo_with_infra(tmp_path)
    res = get_endpoint_impact(repo, endpoint="GET /users", include_infra=True,
                              storage_path=store)
    assert "error" not in res
    imp = res["impacts"][0]
    assert "infra" in imp
    docker_rows = [d for d in imp["infra"]["downstream"] if d["category"] == "docker"]
    assert docker_rows, imp["infra"]
    assert any(d["type"] == "entrypoint" and d["target_file"] == "app.py"
               for d in docker_rows)


def test_compose_build_context_downstream(tmp_path):
    repo, store = _compose_subdir_repo(tmp_path)
    res = get_endpoint_impact(repo, endpoint="GET /orders", include_infra=True,
                              storage_path=store)
    assert "error" not in res
    imp = res["impacts"][0]
    compose_rows = [d for d in imp["infra"]["downstream"] if d["category"] == "compose"]
    assert any(d["label"] == "api" and d["type"] == "build_context" for d in compose_rows), \
        imp["infra"]


# --- honest-empty + default-unchanged ----------------------------------------

def test_no_infra_coupling_returns_empty_block(tmp_path):
    repo, store = _plain_repo(tmp_path)
    res = get_endpoint_impact(repo, endpoint="GET /ping", include_infra=True,
                              storage_path=store)
    imp = res["impacts"][0]
    assert imp["infra"]["downstream"] == []
    assert imp["infra"]["exposes"] == []
    assert "blast_radius_files" in imp["infra"]["_meta"]


def test_no_source_root_reason(tmp_path, monkeypatch):
    repo, store = _flask_repo_with_infra(tmp_path)
    from jcodemunch_mcp.storage import IndexStore
    real_load = IndexStore.load_index

    def _load_no_root(self, owner, name):
        index = real_load(self, owner, name)
        if index is not None:
            index.source_root = ""
        return index

    monkeypatch.setattr(IndexStore, "load_index", _load_no_root)
    res = get_endpoint_impact(repo, endpoint="GET /users", include_infra=True,
                              storage_path=store)
    assert "error" not in res
    imp = res["impacts"][0]
    assert imp["infra"]["downstream"] == []
    assert imp["infra"]["_meta"]["reason"] == "no_local_source_root"


def test_default_output_has_no_infra_key(tmp_path):
    repo, store = _flask_repo_with_infra(tmp_path)
    res = get_endpoint_impact(repo, endpoint="GET /users", storage_path=store)
    assert "error" not in res
    for imp in res["impacts"]:
        assert "infra" not in imp


# --- P2: upstream exposes ----------------------------------------------------

def test_k8s_parser_captures_exposure_fields():
    from jcodemunch_mcp.tools.get_project_intel import _parse_k8s_manifest
    manifest = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api-deploy\n"
        "spec:\n"
        "  replicas: 2\n"
        "  template:\n"
        "    metadata:\n"
        "      labels:\n"
        "        app: myapp\n"
        "    spec:\n"
        "      containers:\n"
        "        - name: api\n"
        "          image: myapp:latest\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: api-svc\n"
        "spec:\n"
        "  selector:\n"
        "    app: myapp\n"
        "  ports:\n"
        "    - port: 80\n"
        "      targetPort: 8000\n"
        "---\n"
        "apiVersion: networking.k8s.io/v1\n"
        "kind: Ingress\n"
        "metadata:\n"
        "  name: api-ing\n"
        "spec:\n"
        "  rules:\n"
        "    - host: api.example.com\n"
        "      http:\n"
        "        paths:\n"
        "          - path: /users\n"
        "            pathType: Prefix\n"
        "            backend:\n"
        "              service:\n"
        "                name: api-svc\n"
        "                port:\n"
        "                  number: 80\n"
    )
    resources = _parse_k8s_manifest(manifest, "k8s/all.yaml")
    by_kind = {r["kind"]: r for r in resources}
    assert by_kind["Deployment"]["labels"] == {"app": "myapp"}
    assert by_kind["Service"]["selector"] == {"app": "myapp"}
    assert by_kind["Service"]["ports"] == [80]
    assert by_kind["Ingress"]["ingress_rules"] == [
        {"host": "api.example.com", "path": "/users", "service": "api-svc"}]


def test_k8s_parser_legacy_ingress_backend():
    from jcodemunch_mcp.tools.get_project_intel import _parse_k8s_manifest
    manifest = (
        "apiVersion: extensions/v1beta1\n"
        "kind: Ingress\n"
        "metadata:\n"
        "  name: legacy-ing\n"
        "spec:\n"
        "  rules:\n"
        "    - http:\n"
        "        paths:\n"
        "          - path: /orders\n"
        "            backend:\n"
        "              serviceName: orders-svc\n"
        "              servicePort: 80\n"
    )
    resources = _parse_k8s_manifest(manifest, "k8s/ing.yaml")
    assert resources[0]["ingress_rules"] == [
        {"host": None, "path": "/orders", "service": "orders-svc"}]


def _INFRA_DISC():
    """Synthetic project-intel infra discoveries: one anchored app + one stranger."""
    return {
        "compose_services": [
            {"name": "api", "image": "myapp:latest", "build_context": "./api",
             "ports": ["8000:8000"], "env_vars": [], "depends_on": []},
            {"name": "other", "image": "otherapp:1", "build_context": "./other",
             "ports": ["9000:9000"], "env_vars": [], "depends_on": []},
        ],
        "k8s_resources": [
            {"file": "k8s/deploy.yaml", "kind": "Deployment", "name": "api-deploy",
             "namespace": None, "images": ["myapp:v2"], "ports": [8000],
             "replicas": 2, "labels": {"app": "myapp"}},
            {"file": "k8s/svc.yaml", "kind": "Service", "name": "api-svc",
             "namespace": None, "images": [], "ports": [80], "replicas": None,
             "selector": {"app": "myapp"}},
            {"file": "k8s/svc.yaml", "kind": "Service", "name": "stranger-svc",
             "namespace": None, "images": [], "ports": [81], "replicas": None,
             "selector": {"app": "stranger"}},
            {"file": "k8s/ing.yaml", "kind": "Ingress", "name": "api-ing",
             "namespace": None, "images": [], "ports": [], "replicas": None,
             "ingress_rules": [
                 {"host": "api.example.com", "path": "/users", "service": "api-svc"},
                 {"host": "api.example.com", "path": "/", "service": "api-svc"},
             ]},
        ],
    }


def test_exposes_compose_anchor_and_k8s_chain():
    from jcodemunch_mcp.tools.get_endpoint_impact import _exposes_for_impact
    blast = {"api/app.py", "api/db.py"}
    exposes = _exposes_for_impact(blast, "/users", _INFRA_DISC())
    by_kind_label = {(e["kind"], e["label"]): e for e in exposes}

    # compose: only the service whose build_context contains blast files
    assert ("compose_port", "api") in by_kind_label
    assert ("compose_port", "other") not in by_kind_label
    assert by_kind_label[("compose_port", "api")]["precision"] == "host_port"

    # k8s service: selector chain through the image-anchored Deployment
    assert ("k8s_service", "api-svc") in by_kind_label
    assert by_kind_label[("k8s_service", "api-svc")]["precision"] == "host_port"
    # unanchored selector is skipped, not guessed
    assert ("k8s_service", "stranger-svc") not in by_kind_label

    # ingress: the /users rule names the endpoint -> real endpoint-level link
    ing = by_kind_label[("k8s_ingress", "api-ing")]
    assert ing["precision"] == "ingress_path"
    assert ing["path"] == "/users"


def test_exposes_root_path_rule_is_not_ingress_path():
    from jcodemunch_mcp.tools.get_endpoint_impact import _exposes_for_impact
    disc = _INFRA_DISC()
    disc["k8s_resources"][-1]["ingress_rules"] = [
        {"host": "api.example.com", "path": "/", "service": "api-svc"}]
    exposes = _exposes_for_impact({"api/app.py"}, "/users", disc)
    ings = [e for e in exposes if e["kind"] == "k8s_ingress"]
    # '/' says nothing route-specific; anchored via the service chain -> host_port
    assert ings and all(e["precision"] == "host_port" for e in ings)


def test_exposes_ingress_path_reverse_anchors_backend_service():
    """A path-matched Ingress rule anchors its backend Service even with no
    compose/image chain (e.g. k8s-only repo)."""
    from jcodemunch_mcp.tools.get_endpoint_impact import _exposes_for_impact
    disc = {
        "compose_services": [],
        "k8s_resources": [
            {"file": "k8s/svc.yaml", "kind": "Service", "name": "api-svc",
             "namespace": None, "images": [], "ports": [80], "replicas": None,
             "selector": {"app": "myapp"}},
            {"file": "k8s/ing.yaml", "kind": "Ingress", "name": "api-ing",
             "namespace": None, "images": [], "ports": [], "replicas": None,
             "ingress_rules": [
                 {"host": None, "path": "/users", "service": "api-svc"}]},
        ],
    }
    exposes = _exposes_for_impact({"app.py"}, "/users", disc)
    kinds = {(e["kind"], e["precision"]) for e in exposes}
    assert ("k8s_ingress", "ingress_path") in kinds
    assert ("k8s_service", "host_port") in kinds


def test_exposes_prefix_path_match():
    from jcodemunch_mcp.tools.get_endpoint_impact import _exposes_for_impact
    disc = {"compose_services": [], "k8s_resources": [
        {"file": "k8s/ing.yaml", "kind": "Ingress", "name": "api-ing",
         "namespace": None, "images": [], "ports": [], "replicas": None,
         "ingress_rules": [{"host": None, "path": "/api", "service": None}]},
    ]}
    exposes = _exposes_for_impact({"app.py"}, "/api/users", disc)
    assert exposes and exposes[0]["precision"] == "ingress_path"
    # unrelated endpoint does not match
    assert _exposes_for_impact({"app.py"}, "/health", disc) == []


def test_compose_ports_exposed_end_to_end(tmp_path):
    repo, store = _compose_subdir_repo(tmp_path)
    res = get_endpoint_impact(repo, endpoint="GET /orders", include_infra=True,
                              storage_path=store)
    assert "error" not in res
    infra = res["impacts"][0]["infra"]
    compose_rows = [e for e in infra["exposes"] if e["kind"] == "compose_port"]
    assert compose_rows, infra
    assert compose_rows[0]["label"] == "api"
    assert compose_rows[0]["ports"] == ["8000:8000"]
    assert compose_rows[0]["precision"] == "host_port"
    assert "honest_note" in infra["_meta"]


def test_ingress_path_exposed_end_to_end(tmp_path):
    src = tmp_path / "src"
    store = tmp_path / "store"
    k8s = src / "k8s"
    k8s.mkdir(parents=True)
    store.mkdir()
    (src / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.get('/users')\n"
        "def list_users():\n"
        "    return []\n"
    )
    (k8s / "ingress.yaml").write_text(
        "apiVersion: networking.k8s.io/v1\n"
        "kind: Ingress\n"
        "metadata:\n"
        "  name: api-ing\n"
        "spec:\n"
        "  rules:\n"
        "    - host: api.example.com\n"
        "      http:\n"
        "        paths:\n"
        "          - path: /users\n"
        "            pathType: Prefix\n"
        "            backend:\n"
        "              service:\n"
        "                name: api-svc\n"
        "                port:\n"
        "                  number: 80\n"
    )
    repo, store = _index(src, store)
    res = get_endpoint_impact(repo, endpoint="GET /users", include_infra=True,
                              storage_path=store)
    assert "error" not in res
    infra = res["impacts"][0]["infra"]
    ings = [e for e in infra["exposes"] if e["kind"] == "k8s_ingress"]
    assert ings, infra
    assert ings[0]["precision"] == "ingress_path"
    assert ings[0]["host"] == "api.example.com"


def test_no_exposes_means_no_honest_note(tmp_path):
    repo, store = _plain_repo(tmp_path)
    res = get_endpoint_impact(repo, endpoint="GET /ping", include_infra=True,
                              storage_path=store)
    infra = res["impacts"][0]["infra"]
    assert infra["exposes"] == []
    assert "honest_note" not in infra["_meta"]
