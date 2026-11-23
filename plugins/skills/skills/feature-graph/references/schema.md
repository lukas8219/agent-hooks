# Feature graph schema and payload

## Nodes

| Label | Key | Properties |
|---|---|---|
| `Repo` | `name` = `owner/name` (from `git remote get-url origin`) | `url`, `default_branch`, `stack`, `mapped_sha`, `mapped_at` |
| `Feature` | `id` = `<repo>:<slug>` | `repo`, `slug`, `name`, `summary`, `kind`, `mapped_sha` |
| `File` | `id` = `<repo>:<path>` | `repo`, `path` (repo-relative), `last_seen_sha` |
| `Interface` | `id` = `<kind>:<key>`. It is global, so other repos join on it | `kind`, `key` |
| `Check` | `id` = `<repo>:<slug>` | `repo`, `kind` (`test`/`manual`), `command`, `description`, `paths` |

## Edges

| Edge | Meaning |
|---|---|
| `(Repo)-[:HAS_FEATURE]->(Feature)` | the repo owns the feature |
| `(Repo)-[:HAS_FILE]->(File)` | the repo owns the file |
| `(Feature)-[:TOUCHES {role, confidence}]->(File)` | the core map. `role`: `entry`, `core`, `view`, `test`, `config`, `migration` |
| `(Feature)-[:VERIFIED_BY]->(Check)` | how to verify the feature |
| `(Feature)-[:DEPENDS_ON {via}]->(Feature)` | a dependency inside one repo. Dependencies across repos come from Interfaces at query time |
| `(File)-[:EXPOSES {evidence}]->(Interface)` | this file serves or publishes the interface |
| `(File)-[:CONSUMES {evidence}]->(Interface)` | this file calls or subscribes to the interface |
| `(Repo)-[:REQUIRES {reason, source}]->(Repo)` | a full test of this repo needs the other one. `source`: `declared` (from the user) or `inferred` |

## Interface keys

Keys must be written the same way in every repo, because that is what joins repos. Normalize before you write a key:

| kind | key format | example |
|---|---|---|
| `http` | `METHOD /path` with params as `:name`, no host, no query string, no trailing slash, no format suffix | `POST /api/v1/instances/:id/restart` |
| `amqp` | `<exchange>/<routing_key>`, or `queue/<queue>` for direct consumers | `amq.topic/instance.created`, `queue/billing.events` |
| `db_table` | `<database_role>.<table>` when it is a shared DB, otherwise just `<table>` | `instances` |
| `gem` | gem or package name | `84codes-auth` |
| `env` | the env var that holds the other service's URL | `ACCOUNT_CONSOLE_URL` |
| `webhook` | `<provider>/<event>` | `stripe/invoice.paid` |
| `grpc` | `<package.Service>/<Method>` | `machines.v1.Machines/Create` |
| `file` | a shared file path or artifact name | `config/plans.yml` |

When a consumer builds the path from a base URL plus a template, record the template path. Rewrite interpolations as `:name`. If you are unsure, give the key you guessed and mention it in `evidence`.

## Payload (`graph.py upsert --json payload.json`)

```json
{
  "mode": "full",
  "repo": {
    "name": "84codes/customer-console",
    "url": "git@github.com:84codes/customer-console.git",
    "default_branch": "main",
    "sha": "<git rev-parse HEAD>",
    "stack": ["ruby", "sinatra", "postgres"]
  },
  "features": [
    {
      "slug": "create-instance",
      "name": "Create instance",
      "summary": "Customer picks a plan and region and creates a new instance.",
      "kind": "ui",
      "files": [
        {"path": "app/controllers/instances.rb", "role": "entry", "confidence": 0.95},
        {"path": "lib/account_client.rb", "role": "core", "confidence": 0.7},
        {"path": "spec/requests/instances_spec.rb", "role": "test"}
      ],
      "checks": [
        {"slug": "create-instance-spec", "kind": "test",
         "command": "bundle exec rspec spec/requests/instances_spec.rb",
         "paths": ["spec/requests/instances_spec.rb"]},
        {"slug": "create-instance-manual", "kind": "manual",
         "description": "Log in, create an instance on the free plan, and see it listed as running."}
      ],
      "depends_on": [{"feature": "plans", "via": "plan selection"}]
    }
  ],
  "interfaces": [
    {"kind": "http", "key": "POST /api/instances", "direction": "consumes",
     "files": ["lib/account_client.rb"], "evidence": "AccountClient#create_instance"}
  ],
  "requires": [
    {"repo": "84codes/account-console", "reason": "instance creation goes through the account API", "source": "declared"}
  ]
}
```

- `kind` (feature): `ui`, `api`, `job`, `cli`, `integration`, `library`.
- `confidence` defaults to 0.8. Use about 0.9 or more for files you read and saw on the path. Use about 0.5 to 0.7 for files that only co-change or that you inferred.
- `mode: "full"` replaces everything this repo owns in the graph.
- `mode: "partial"` replaces only the listed features and the interface links of the listed files. It also takes `removed_features: [slug]` and `removed_files: [path]`. In partial mode, leave out `requires` to keep the existing edges. If you include it, it replaces them.
- `graph.py validate --json payload.json` checks the shape offline. `graph.py upsert --dry-run` prints the Cypher it would run.
- The upsert never touches another repo's Features, Files or Checks. It deletes an `Interface` once nothing links to it.

## Useful read queries (`graph.py read '<cypher>' --param k=v`)

```cypher
MATCH (r:Repo)-[:HAS_FEATURE]->(f)-[:TOUCHES]->(x) RETURN r.name, f.name, collect(x.path)

MATCH (x:File)-[:EXPOSES]->(i:Interface)<-[:CONSUMES]-(y:File)
WHERE x.repo <> y.repo RETURN i.id, x.repo AS provider, y.repo AS consumer

MATCH (f:Feature {id: $id})-[:TOUCHES]->(x:File)-[:EXPOSES|CONSUMES]->(i)<-[:EXPOSES|CONSUMES]-(y:File)<-[:TOUCHES]-(g:Feature)
WHERE y.repo <> f.repo RETURN DISTINCT i.id, g.id

MATCH (c:Repo)-[:HAS_FILE]->(:File)-[:CONSUMES]->(i:Interface) WHERE NOT (i)<-[:EXPOSES]-()
RETURN c.name, collect(i.id) AS dangling
```
