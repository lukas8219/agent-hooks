#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

FEATURE_KINDS = {"ui", "api", "job", "cli", "integration", "library"}
FILE_ROLES = {"entry", "core", "view", "test", "config", "migration"}
CHECK_KINDS = {"test", "manual"}
INTERFACE_KINDS = {"http", "amqp", "db_table", "gem", "env", "webhook", "grpc", "file"}
DIRECTIONS = {"exposes", "consumes"}
REQUIRE_SOURCES = {"declared", "inferred"}

CONSTRAINTS = [
    "CREATE CONSTRAINT repo_name IF NOT EXISTS FOR (n:Repo) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT feature_id IF NOT EXISTS FOR (n:Feature) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT file_id IF NOT EXISTS FOR (n:File) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT interface_id IF NOT EXISTS FOR (n:Interface) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT check_id IF NOT EXISTS FOR (n:Check) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX file_path IF NOT EXISTS FOR (n:File) ON (n.repo, n.path)",
]


class GraphError(Exception):
    pass


def http_base(uri):
    if not uri:
        raise GraphError("NEO4J_URI is not set")
    parsed = urllib.parse.urlparse(uri.strip())
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    if not host:
        raise GraphError(f"cannot parse NEO4J_URI: {uri}")
    port = parsed.port
    if scheme in ("http", "https"):
        netloc = host if port is None else f"{host}:{port}"
        return f"{scheme}://{netloc}"
    tls = scheme.endswith("+s") or scheme.endswith("+ssc")
    if scheme.split("+")[0] not in ("neo4j", "bolt"):
        raise GraphError(f"unsupported NEO4J_URI scheme: {scheme}")
    if tls:
        if port in (None, 443, 7687):
            return f"https://{host}" if port in (None, 443) else f"https://{host}:7473"
        return f"https://{host}:{port}"
    if port in (None, 7687):
        return f"http://{host}:7474"
    return f"http://{host}:{port}"


def credentials(read_only):
    if read_only and os.environ.get("NEO4J_READ_USERNAME"):
        user = os.environ.get("NEO4J_READ_USERNAME")
        password = os.environ.get("NEO4J_READ_PASSWORD", "")
    else:
        user = os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER")
        password = os.environ.get("NEO4J_PASSWORD", "")
    if not user:
        raise GraphError("NEO4J_USERNAME is not set")
    if not password:
        raise GraphError("NEO4J_PASSWORD is not set")
    return user, password


def one_line(statement):
    return re.sub(r"\s+", " ", statement).strip()


class Session:
    def __init__(self, read_only):
        self.read_only = read_only
        self.base = http_base(os.environ.get("NEO4J_URI"))
        self.database = os.environ.get("NEO4J_DATABASE") or "neo4j"
        user, password = credentials(read_only)
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.tx = None

    def url(self, suffix=""):
        return f"{self.base}/db/{urllib.parse.quote(self.database)}/query/v2{suffix}"

    def request(self, method, url, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode() or "{}"
                affinity = resp.headers.get("neo4j-cluster-affinity")
        except urllib.error.HTTPError as err:
            raw = err.read().decode() or "{}"
            affinity = None
            if err.code == 401:
                raise GraphError("authentication failed (check NEO4J_USERNAME/NEO4J_PASSWORD)")
        except urllib.error.URLError as err:
            raise GraphError(f"cannot reach {self.base}: {err.reason}")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise GraphError(f"unexpected response from {url}: {raw[:300]}")
        if affinity:
            self.headers["neo4j-cluster-affinity"] = affinity
        errors = payload.get("errors") or []
        if errors:
            raise GraphError("; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors))
        return payload

    def begin(self):
        payload = self.request("POST", self.url("/tx"), {})
        self.tx = (payload.get("transaction") or {}).get("id")
        if not self.tx:
            raise GraphError("server did not open a transaction")

    def run(self, statement, params=None):
        body = {"statement": one_line(statement), "parameters": params or {}}
        if self.read_only:
            body["includeCounters"] = True
        if self.tx is None:
            payload = self.request("POST", self.url(), body)
        else:
            payload = self.request("POST", self.url(f"/tx/{self.tx}"), body)
            if "transaction" not in payload:
                self.tx = None
                raise GraphError("transaction closed by the server")
        counters = payload.get("counters") or {}
        if self.read_only and (counters.get("containsUpdates") or counters.get("containsSystemUpdates")):
            raise GraphError("read-only session: the statement tried to write and was rolled back")
        data = payload.get("data") or {}
        fields = data.get("fields") or []
        return [dict(zip(fields, row)) for row in data.get("values") or []]

    def commit(self):
        if self.tx:
            tx, self.tx = self.tx, None
            self.request("POST", self.url(f"/tx/{tx}/commit"), {})

    def rollback(self):
        if self.tx:
            tx, self.tx = self.tx, None
            try:
                self.request("DELETE", self.url(f"/tx/{tx}"))
            except GraphError:
                pass

    def __enter__(self):
        self.begin()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None and not self.read_only:
            self.commit()
        else:
            self.rollback()
        return False


def git(*args, cwd=None):
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    return out.stdout.strip()


def repo_name_from_url(url):
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", url or "")
    return match.group(1) if match else ""


def whoami(cwd=None):
    url = git("remote", "get-url", "origin", cwd=cwd)
    top = git("rev-parse", "--show-toplevel", cwd=cwd)
    name = repo_name_from_url(url) or os.path.basename(top)
    head = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=cwd)
    default_branch = head.split("/", 1)[1] if "/" in head else ""
    if not default_branch:
        for candidate in ("main", "master"):
            if git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{candidate}", cwd=cwd):
                default_branch = candidate
                break
    return {
        "name": name,
        "url": url,
        "root": top,
        "sha": git("rev-parse", "HEAD", cwd=cwd),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd),
        "default_branch": default_branch or "main",
    }


def require(cond, message, problems):
    if not cond:
        problems.append(message)


def slug_ok(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value) is not None


def validate(payload):
    problems = []
    repo = payload.get("repo") or {}
    require(isinstance(repo.get("name"), str) and "/" in repo.get("name", ""), "repo.name must be owner/name", problems)
    require(isinstance(repo.get("sha"), str) and len(repo.get("sha", "")) >= 7, "repo.sha is required", problems)
    mode = payload.get("mode", "full")
    require(mode in ("full", "partial"), "mode must be full or partial", problems)
    slugs = set()
    for i, feature in enumerate(payload.get("features") or []):
        where = f"features[{i}]"
        require(slug_ok(feature.get("slug")), f"{where}.slug must be a lowercase slug", problems)
        require(feature.get("slug") not in slugs, f"{where}.slug is duplicated", problems)
        slugs.add(feature.get("slug"))
        require(bool(feature.get("name")), f"{where}.name is required", problems)
        require(feature.get("kind", "ui") in FEATURE_KINDS, f"{where}.kind must be one of {sorted(FEATURE_KINDS)}", problems)
        for j, f in enumerate(feature.get("files") or []):
            require(bool(f.get("path")) and not f.get("path", "").startswith("/"), f"{where}.files[{j}].path must be repo-relative", problems)
            require(f.get("role", "core") in FILE_ROLES, f"{where}.files[{j}].role must be one of {sorted(FILE_ROLES)}", problems)
            conf = f.get("confidence", 0.8)
            require(isinstance(conf, (int, float)) and 0 <= conf <= 1, f"{where}.files[{j}].confidence must be 0..1", problems)
        for j, c in enumerate(feature.get("checks") or []):
            require(slug_ok(c.get("slug")), f"{where}.checks[{j}].slug must be a lowercase slug", problems)
            require(c.get("kind") in CHECK_KINDS, f"{where}.checks[{j}].kind must be test or manual", problems)
            if c.get("kind") == "test":
                require(bool(c.get("command")), f"{where}.checks[{j}].command is required for test checks", problems)
            else:
                require(bool(c.get("description")), f"{where}.checks[{j}].description is required for manual checks", problems)
    for i, feature in enumerate(payload.get("features") or []):
        for j, dep in enumerate(feature.get("depends_on") or []):
            require(dep.get("feature") in slugs or mode == "partial", f"features[{i}].depends_on[{j}].feature is not a feature in this payload", problems)
    for i, itf in enumerate(payload.get("interfaces") or []):
        where = f"interfaces[{i}]"
        require(itf.get("kind") in INTERFACE_KINDS, f"{where}.kind must be one of {sorted(INTERFACE_KINDS)}", problems)
        require(bool(itf.get("key")), f"{where}.key is required", problems)
        require(itf.get("direction") in DIRECTIONS, f"{where}.direction must be exposes or consumes", problems)
        require(bool(itf.get("files")), f"{where}.files must list at least one path", problems)
        if itf.get("kind") == "http":
            require(re.fullmatch(r"[A-Z]+ /\S*", itf.get("key", "")) is not None, f"{where}.key must look like 'GET /path/:id'", problems)
    for i, req in enumerate(payload.get("requires") or []):
        require(isinstance(req.get("repo"), str) and "/" in req.get("repo", ""), f"requires[{i}].repo must be owner/name", problems)
        require(req.get("repo") != repo.get("name"), f"requires[{i}].repo cannot be the repo itself", problems)
        require(req.get("source", "declared") in REQUIRE_SOURCES, f"requires[{i}].source must be declared or inferred", problems)
    return problems


def interface_id(itf):
    return f"{itf['kind']}:{itf['key']}"


def upsert_statements(payload):
    repo = payload["repo"]
    name = repo["name"]
    sha = repo["sha"]
    mode = payload.get("mode", "full")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    features = []
    touches = []
    checks = []
    deps = []
    for feature in payload.get("features") or []:
        fid = f"{name}:{feature['slug']}"
        features.append({
            "id": fid,
            "slug": feature["slug"],
            "name": feature["name"],
            "summary": feature.get("summary", ""),
            "kind": feature.get("kind", "ui"),
        })
        for f in feature.get("files") or []:
            touches.append({
                "feature": fid,
                "file": f"{name}:{f['path']}",
                "path": f["path"],
                "role": f.get("role", "core"),
                "confidence": float(f.get("confidence", 0.8)),
            })
        for c in feature.get("checks") or []:
            checks.append({
                "feature": fid,
                "id": f"{name}:{c['slug']}",
                "kind": c["kind"],
                "command": c.get("command", ""),
                "description": c.get("description", ""),
                "paths": list(c.get("paths") or []),
            })
        for dep in feature.get("depends_on") or []:
            deps.append({"from": fid, "to": f"{name}:{dep['feature']}", "via": dep.get("via", "")})
    links = []
    for itf in payload.get("interfaces") or []:
        for path in itf["files"]:
            links.append({
                "interface": interface_id(itf),
                "kind": itf["kind"],
                "key": itf["key"],
                "direction": itf["direction"],
                "file": f"{name}:{path}",
                "path": path,
                "evidence": itf.get("evidence", ""),
            })
    requires = [
        {"repo": r["repo"], "reason": r.get("reason", ""), "source": r.get("source", "declared")}
        for r in payload.get("requires") or []
    ]
    feature_ids = [f["id"] for f in features]
    removed_features = [f"{name}:{s}" for s in payload.get("removed_features") or []]
    removed_files = [f"{name}:{p}" for p in payload.get("removed_files") or []]
    interface_files = sorted({link["file"] for link in links})
    statements = []

    def add(statement, **params):
        statements.append((one_line(statement), params))

    add(
        """MERGE (r:Repo {name: $name})
           SET r.url = $url, r.default_branch = $default_branch, r.stack = $stack""",
        name=name,
        url=repo.get("url", ""),
        default_branch=repo.get("default_branch", "main"),
        stack=list(repo.get("stack") or []),
    )
    if mode == "full":
        add("MATCH (:Repo {name: $name})-[:HAS_FEATURE]->(f:Feature) DETACH DELETE f", name=name)
        add("MATCH (c:Check {repo: $name}) DETACH DELETE c", name=name)
        add("MATCH (:Repo {name: $name})-[:HAS_FILE]->(x:File) DETACH DELETE x", name=name)
        add("MATCH (:Repo {name: $name})-[q:REQUIRES]->() DELETE q", name=name)
    else:
        add(
            """MATCH (f:Feature) WHERE f.id IN $ids
               OPTIONAL MATCH (f)-[:VERIFIED_BY]->(c:Check)
               DETACH DELETE c""",
            ids=feature_ids + removed_features,
        )
        add(
            "MATCH (f:Feature)-[e:TOUCHES|DEPENDS_ON]->() WHERE f.id IN $ids DELETE e",
            ids=feature_ids,
        )
        add("MATCH (f:Feature) WHERE f.id IN $ids DETACH DELETE f", ids=removed_features)
        add(
            "MATCH (x:File)-[e:EXPOSES|CONSUMES]->() WHERE x.id IN $ids DELETE e",
            ids=interface_files,
        )
        add("MATCH (x:File) WHERE x.id IN $ids DETACH DELETE x", ids=removed_files)
        if payload.get("requires") is not None:
            add("MATCH (:Repo {name: $name})-[q:REQUIRES]->() DELETE q", name=name)
    add(
        """MATCH (r:Repo {name: $name})
           UNWIND $rows AS row
           MERGE (f:Feature {id: row.id})
           SET f.repo = $name, f.slug = row.slug, f.name = row.name,
               f.summary = row.summary, f.kind = row.kind, f.mapped_sha = $sha
           MERGE (r)-[:HAS_FEATURE]->(f)""",
        name=name, sha=sha, rows=features,
    )
    add(
        """MATCH (r:Repo {name: $name})
           UNWIND $rows AS row
           MATCH (f:Feature {id: row.feature})
           MERGE (x:File {id: row.file})
           SET x.repo = $name, x.path = row.path, x.last_seen_sha = $sha
           MERGE (r)-[:HAS_FILE]->(x)
           MERGE (f)-[t:TOUCHES]->(x)
           SET t.role = row.role, t.confidence = row.confidence""",
        name=name, sha=sha, rows=touches,
    )
    add(
        """UNWIND $rows AS row
           MATCH (f:Feature {id: row.feature})
           MERGE (c:Check {id: row.id})
           SET c.repo = $name, c.kind = row.kind, c.command = row.command,
               c.description = row.description, c.paths = row.paths
           MERGE (f)-[:VERIFIED_BY]->(c)""",
        name=name, rows=checks,
    )
    add(
        """UNWIND $rows AS row
           MATCH (a:Feature {id: row.from}), (b:Feature {id: row.to})
           MERGE (a)-[d:DEPENDS_ON]->(b)
           SET d.via = row.via""",
        rows=deps,
    )
    add(
        """MATCH (r:Repo {name: $name})
           UNWIND $rows AS row
           MERGE (i:Interface {id: row.interface})
           SET i.kind = row.kind, i.key = row.key
           MERGE (x:File {id: row.file})
           SET x.repo = $name, x.path = row.path, x.last_seen_sha = $sha
           MERGE (r)-[:HAS_FILE]->(x)
           FOREACH (_ IN CASE WHEN row.direction = 'exposes' THEN [1] ELSE [] END |
             MERGE (x)-[e:EXPOSES]->(i) SET e.evidence = row.evidence)
           FOREACH (_ IN CASE WHEN row.direction = 'consumes' THEN [1] ELSE [] END |
             MERGE (x)-[e:CONSUMES]->(i) SET e.evidence = row.evidence)""",
        name=name, sha=sha, rows=links,
    )
    add(
        """MATCH (r:Repo {name: $name})
           UNWIND $rows AS row
           MERGE (o:Repo {name: row.repo})
           MERGE (r)-[q:REQUIRES]->(o)
           SET q.reason = row.reason, q.source = row.source""",
        name=name, rows=requires,
    )
    add(
        """MATCH (:Repo {name: $name})-[:HAS_FILE]->(x:File)
           WHERE NOT (x)<-[:TOUCHES]-() AND NOT (x)-[:EXPOSES|CONSUMES]->()
           DETACH DELETE x""",
        name=name,
    )
    add("MATCH (i:Interface) WHERE NOT (i)--() DELETE i")
    add(
        "MATCH (r:Repo {name: $name}) SET r.mapped_sha = $sha, r.mapped_at = $now",
        name=name, sha=sha, now=now,
    )
    return statements


def impact(session, repo, paths):
    paths = sorted(set(paths))
    file_ids = [f"{repo}:{p}" for p in paths]
    info = session.run(
        "MATCH (r:Repo {name: $repo}) RETURN r.mapped_sha AS mapped_sha, r.mapped_at AS mapped_at, r.default_branch AS default_branch",
        {"repo": repo},
    )
    known = {
        row["path"]
        for row in session.run("MATCH (x:File) WHERE x.id IN $ids RETURN x.path AS path", {"ids": file_ids})
    }
    touch_rows = session.run(
        """MATCH (feat:Feature)-[t:TOUCHES]->(x:File) WHERE x.id IN $ids
           RETURN feat.id AS id, feat.name AS name, feat.kind AS kind, x.path AS path, t.role AS role""",
        {"ids": file_ids},
    )
    features = {}
    for row in touch_rows:
        entry = features.setdefault(row["id"], {"id": row["id"], "name": row["name"], "kind": row["kind"], "via": []})
        entry["via"].append({"path": row["path"], "role": row["role"]})
    fids = sorted(features)
    dependents = session.run(
        """MATCH (d:Feature)-[e:DEPENDS_ON]->(feat:Feature) WHERE feat.id IN $fids AND NOT d.id IN $fids
           RETURN d.id AS id, d.name AS name, feat.id AS depends_on, e.via AS via""",
        {"fids": fids},
    )
    feature_files = [
        row["id"]
        for row in session.run(
            "MATCH (feat:Feature)-[:TOUCHES]->(x:File) WHERE feat.id IN $fids RETURN DISTINCT x.id AS id",
            {"fids": fids},
        )
    ]
    direct = set(file_ids)
    itf_rows = session.run(
        """MATCH (x:File)-[e:EXPOSES|CONSUMES]->(i:Interface) WHERE x.id IN $ids
           OPTIONAL MATCH (i)<-[e2:EXPOSES|CONSUMES]-(o:File) WHERE o.repo <> $repo
           OPTIONAL MATCH (ofeat:Feature)-[:TOUCHES]->(o)
           RETURN i.id AS id, i.kind AS kind, i.key AS key, type(e) AS direction, x.id AS file, x.path AS path,
                  o.repo AS other_repo, type(e2) AS other_direction, o.path AS other_path,
                  ofeat.id AS other_feature, ofeat.name AS other_feature_name""",
        {"ids": sorted(direct | set(feature_files)), "repo": repo},
    )
    interfaces = {}
    other_fids = set()
    for row in itf_rows:
        entry = interfaces.setdefault(row["id"], {
            "id": row["id"], "kind": row["kind"], "key": row["key"],
            "direction": row["direction"].lower(), "level": "indirect",
            "files": set(), "counterparts": {},
        })
        entry["files"].add(row["path"])
        if row["file"] in direct:
            entry["level"] = "direct"
        if row["other_repo"]:
            key = (row["other_repo"], row["other_path"])
            cp = entry["counterparts"].setdefault(key, {
                "repo": row["other_repo"], "path": row["other_path"],
                "direction": (row["other_direction"] or "").lower(), "features": {},
            })
            if row["other_feature"]:
                cp["features"][row["other_feature"]] = row["other_feature_name"]
                other_fids.add(row["other_feature"])
    check_rows = session.run(
        """MATCH (feat:Feature)-[:VERIFIED_BY]->(c:Check) WHERE feat.id IN $fids
           RETURN feat.id AS feature, c.id AS id, c.repo AS repo, c.kind AS kind,
                  c.command AS command, c.description AS description, c.paths AS paths""",
        {"fids": sorted(set(fids) | other_fids | {d["id"] for d in dependents})},
    )
    outgoing = session.run(
        "MATCH (:Repo {name: $repo})-[q:REQUIRES]->(o:Repo) RETURN o.name AS repo, q.reason AS reason, q.source AS source",
        {"repo": repo},
    )
    incoming = session.run(
        "MATCH (o:Repo)-[q:REQUIRES]->(:Repo {name: $repo}) RETURN o.name AS repo, q.reason AS reason, q.source AS source",
        {"repo": repo},
    )
    checks = {}
    for row in check_rows:
        entry = checks.setdefault(row["id"], {k: row[k] for k in ("id", "repo", "kind", "command", "description", "paths")})
        entry.setdefault("features", []).append(row["feature"])
    interface_list = []
    for entry in sorted(interfaces.values(), key=lambda e: (e["level"] != "direct", e["id"])):
        entry["files"] = sorted(entry["files"])
        cps = []
        for cp in entry["counterparts"].values():
            cp["features"] = [{"id": k, "name": v} for k, v in sorted(cp["features"].items())]
            cps.append(cp)
        entry["counterparts"] = sorted(cps, key=lambda c: (c["repo"], c["path"]))
        interface_list.append(entry)
    return {
        "repo": repo,
        "mapped": bool(info),
        "mapped_sha": info[0]["mapped_sha"] if info else None,
        "mapped_at": info[0]["mapped_at"] if info else None,
        "changed_files": paths,
        "unmapped_files": [p for p in paths if p not in known],
        "features": [features[k] for k in fids],
        "dependents": dependents,
        "interfaces": interface_list,
        "checks": sorted(checks.values(), key=lambda c: (c["repo"] != repo, c["repo"], c["kind"], c["id"])),
        "requires": {"outgoing": outgoing, "incoming": incoming},
    }


def status(session, repo):
    rows = session.run(
        """MATCH (r:Repo {name: $repo})
           OPTIONAL MATCH (r)-[:HAS_FEATURE]->(f:Feature)
           WITH r, count(DISTINCT f) AS features
           OPTIONAL MATCH (r)-[:HAS_FILE]->(x:File)
           WITH r, features, count(DISTINCT x) AS files
           OPTIONAL MATCH (r)-[:HAS_FILE]->(:File)-[:EXPOSES|CONSUMES]->(i:Interface)
           RETURN r.name AS repo, r.mapped_sha AS mapped_sha, r.mapped_at AS mapped_at,
                  features, files, count(DISTINCT i) AS interfaces""",
        {"repo": repo},
    )
    if not rows:
        return {"repo": repo, "mapped": False}
    result = dict(rows[0], mapped=True)
    result["linked_interfaces"] = session.run(
        """MATCH (:Repo {name: $repo})-[:HAS_FILE]->(x:File)-[e:EXPOSES|CONSUMES]->(i:Interface)<-[e2:EXPOSES|CONSUMES]-(o:File)
           WHERE o.repo <> $repo
           RETURN DISTINCT i.id AS interface, type(e) AS ours, o.repo AS other_repo, type(e2) AS theirs""",
        {"repo": repo},
    )
    result["dangling_consumes"] = [
        row["interface"]
        for row in session.run(
            """MATCH (:Repo {name: $repo})-[:HAS_FILE]->(:File)-[:CONSUMES]->(i:Interface)
               WHERE NOT (i)<-[:EXPOSES]-()
               RETURN DISTINCT i.id AS interface ORDER BY interface""",
            {"repo": repo},
        )
    ]
    result["requires"] = session.run(
        "MATCH (:Repo {name: $repo})-[q:REQUIRES]->(o:Repo) RETURN o.name AS repo, q.reason AS reason, q.source AS source",
        {"repo": repo},
    )
    result["features_list"] = session.run(
        """MATCH (:Repo {name: $repo})-[:HAS_FEATURE]->(f:Feature)
           OPTIONAL MATCH (f)-[:TOUCHES]->(x:File)
           RETURN f.slug AS slug, f.name AS name, f.kind AS kind, f.mapped_sha AS mapped_sha,
                  collect(x.path) AS paths ORDER BY slug""",
        {"repo": repo},
    )
    return result


def parse_params(pairs, params_json):
    params = {}
    if params_json:
        with open(params_json) as fh:
            params.update(json.load(fh))
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise GraphError(f"--param needs key=value, got {pair}")
        try:
            params[key] = json.loads(value)
        except json.JSONDecodeError:
            params[key] = value
    return params


def read_statement(args):
    if args.file:
        with open(args.file) as fh:
            return fh.read()
    if not args.statement:
        raise GraphError("give a Cypher statement or --file")
    return args.statement


def load_payload(path):
    with open(path) as fh:
        payload = json.load(fh)
    problems = validate(payload)
    if problems:
        raise GraphError("invalid payload:\n  " + "\n  ".join(problems))
    return payload


def emit(value):
    json.dump(value, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def cmd_ping(args):
    with Session(read_only=True) as s:
        rows = s.run("CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition")
    emit({"ok": True, "base": http_base(os.environ.get("NEO4J_URI")), "server": rows})


def cmd_init(args):
    for statement in CONSTRAINTS:
        Session(read_only=False).run(statement)
    emit({"ok": True, "constraints": len(CONSTRAINTS)})


def cmd_read(args):
    statement = read_statement(args)
    params = parse_params(args.param, args.params_json)
    with Session(read_only=True) as s:
        emit(s.run(statement, params))


def cmd_write(args):
    statement = read_statement(args)
    params = parse_params(args.param, args.params_json)
    with Session(read_only=False) as s:
        emit(s.run(statement, params))


def cmd_upsert(args):
    payload = load_payload(args.json)
    statements = upsert_statements(payload)
    if args.dry_run:
        emit([{"statement": st, "parameters": params} for st, params in statements])
        return
    with Session(read_only=False) as s:
        for statement, params in statements:
            s.run(statement, params)
    with Session(read_only=True) as s:
        emit(status(s, payload["repo"]["name"]))


def cmd_validate(args):
    load_payload(args.json)
    emit({"ok": True})


def cmd_status(args):
    repo = args.repo or whoami()["name"]
    with Session(read_only=True) as s:
        emit(status(s, repo))


def cmd_impact(args):
    repo = args.repo or whoami()["name"]
    paths = list(args.paths or [])
    if args.files_from:
        source = sys.stdin if args.files_from == "-" else open(args.files_from)
        paths += [line.strip() for line in source if line.strip()]
    with Session(read_only=True) as s:
        emit(impact(s, repo, paths))


def cmd_whoami(args):
    emit(whoami())


def cmd_uri(args):
    emit({"base": http_base(args.uri if args.uri is not None else os.environ.get("NEO4J_URI"))})


def build_parser():
    parser = argparse.ArgumentParser(prog="graph.py", description="Neo4j feature graph client (Query API v2)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", help="check connection and credentials").set_defaults(func=cmd_ping)
    sub.add_parser("init", help="create constraints and indexes").set_defaults(func=cmd_init)
    sub.add_parser("whoami", help="print this git repo's identity").set_defaults(func=cmd_whoami)
    p = sub.add_parser("uri", help="print the HTTP base derived from NEO4J_URI")
    p.add_argument("uri", nargs="?")
    p.set_defaults(func=cmd_uri)
    for name, func, text in (
        ("read", cmd_read, "run Cypher in a transaction that is always rolled back"),
        ("write", cmd_write, "run Cypher and commit"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("statement", nargs="?")
        p.add_argument("--file")
        p.add_argument("--param", action="append", metavar="KEY=VALUE")
        p.add_argument("--params-json")
        p.set_defaults(func=func)
    p = sub.add_parser("upsert", help="replace this repo's subgraph from a payload")
    p.add_argument("--json", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_upsert)
    p = sub.add_parser("validate", help="check a payload without connecting")
    p.add_argument("--json", required=True)
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("status", help="summarize a repo's subgraph")
    p.add_argument("--repo")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("impact", help="features, checks, interfaces and repos affected by paths")
    p.add_argument("--repo")
    p.add_argument("--files-from", metavar="FILE|-")
    p.add_argument("paths", nargs="*")
    p.set_defaults(func=cmd_impact)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except GraphError as err:
        print(f"graph.py: {err}", file=sys.stderr)
        return 1
    except OSError as err:
        print(f"graph.py: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
