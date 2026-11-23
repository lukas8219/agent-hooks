---
name: feature-graph
description: Build or refresh this repository's part of the cross-repo feature knowledge graph in Neo4j. It maps features to files, interfaces (HTTP, AMQP, DB tables, gems) and checks, and links repos through the interfaces they share. Run once per repo. /verify-changed reads the result.
disable-model-invocation: true
argument-hint: "[refresh | <feature-slug>]"
---

# feature-graph

This skill maps the repo it runs in into a Neo4j knowledge graph. That graph is shared across repos: 84codes/customer-console, 84codes/account-console, machines and others each upsert their own subgraph, one run per repo. Repos link to each other through `Interface` nodes. Repo A `EXPOSES` an interface, repo B `CONSUMES` the same one, and the link appears once both repos are mapped. `/verify-changed` reads the graph to plan verification for a diff.

The analysis is static only. Do not boot or drive the app.

## Setup

- `G=<this skill's base directory>/scripts/graph.py`. Run it as `python3 -I "$G" ...`.
- Env: `NEO4J_URI` (`neo4j+s://…` from Aura is fine), `NEO4J_USERNAME`, `NEO4J_PASSWORD`, optional `NEO4J_DATABASE`. If any of them is missing, tell the user which one and stop.
- Reference: `references/schema.md` (graph model, interface key normalization, payload format), `references/discovery.md` (where features and interfaces hide, by stack).

## Hard rules

- Never modify the repo's source. Write only to the graph and the scratchpad. The payload JSON goes in the scratchpad, never in the repo.
- Never put secrets in the graph: no env var values, tokens or hostnames from `.env`. Env var names are fine.
- Write only through `graph.py upsert` (and `graph.py init`). Do not use `graph.py write` for mapping work.
- Show the user the feature list and repo dependencies, and get confirmation before writing.
- Mark guesses. Use lower `confidence` for inferred files, and put the reasoning in `evidence` for interface keys that are not certain.

## Commands

| Invocation | Action |
|---|---|
| `/feature-graph` | If the repo is not mapped, do a full build. If it is mapped, report status and propose a next step (usually `refresh`). |
| `/feature-graph refresh` | Incremental update since `Repo.mapped_sha`. |
| `/feature-graph <slug>` | Remap one feature (a partial upsert). |

## 1. Preflight

```sh
python3 -I "$G" ping
python3 -I "$G" init
python3 -I "$G" whoami
python3 -I "$G" status
```

`whoami` gives `name` (`owner/repo`), `sha` and `default_branch`. If `status` says `mapped: true` and no argument was given, report what is mapped: feature count, `mapped_sha` against HEAD, how many commits behind, linked and dangling interfaces. Then propose a next step and stop.

## 2. Discover features

Follow `references/discovery.md`. List entry points (routes, controllers, jobs, consumers, CLIs, rake tasks) and group them into features a user would name. For a large repo, split discovery by area (for example web UI, API, workers) across parallel Explore subagents. Each one returns features, files with roles, interfaces and specs in the payload shape.

## 3. Map files, checks and interfaces

For each feature:
- **files**: entry, then core, view, config, migration and test, with a role and a confidence (see discovery.md, "Mapping files to a feature"). Use git co-change to find files the static pass missed.
- **checks**: one `test` check per runnable spec group, with an exact command and `paths`. Add one or two `manual` checks that describe the main user path in a sentence.
- **depends_on**: other features in this repo that this one needs.

For the repo as a whole, list **interfaces** it exposes and consumes, with normalized keys. The keys are what join repos, so follow the normalization table in schema.md exactly.

## 4. Repo dependencies (confirm with the user)

Infer `requires` from the interfaces this repo consumes and the services it calls, and from docker-compose, `.env.example` and README. Then show the user, in one message:

1. The features: slug, name, kind, file count and check count.
2. The interfaces it exposes and consumes, with counts by kind. List the consumed `http`/`amqp` keys in full.
3. Inferred `requires` edges, with reasons.

Ask the user to confirm, rename or merge features, and to add repos that a full test always needs (e.g. "customer-console always needs account-console"). Those go in as `source: "declared"`. Adjust, then write.

## 5. Write

Build the payload described in `references/schema.md` with `mode: "full"` and `repo.sha` = HEAD. Save it to the scratchpad as `feature-graph-<repo>.json`.

```sh
python3 -I "$G" validate --json "$PAYLOAD"
python3 -I "$G" upsert --json "$PAYLOAD"
```

`upsert` runs in one transaction and prints the new `status`.

## 6. Report (in chat, short)

- Where it was written: the Neo4j base URL (no credentials), the repo name and the sha.
- Features, files, interfaces and checks, by count.
- **Cross-repo links** (`linked_interfaces`): which other repos are now connected, and through what.
- **Dangling consumes**: interfaces this repo uses that no mapped repo exposes yet. Group them by the likely provider repo, and suggest running `/feature-graph` there next.
- Files that no feature covers, if any directories stand out (for example `lib/` with no features), and shared utilities you left out on purpose.
- One recommended next step.

## Refresh

1. Run `status`, and get `mapped_sha`. If `git merge-base --is-ancestor <mapped_sha> HEAD` fails, do a full build instead.
2. Run `git diff --name-status <mapped_sha>..HEAD`.
3. Affected features are those whose files changed (from `status`.`features_list`), plus new entry points among the added files.
4. Remap only those features. Put deleted paths in `removed_files`, and features that no longer exist in `removed_features` after the user confirms.
5. Re-extract interfaces only for the changed files, and include those files in `interfaces` (partial mode resets the interface links of the files listed there).
6. Upsert with `mode: "partial"`. Leave out `requires` unless it changed.
7. Report what changed: features added, remapped and removed, and links that were gained or lost.

`/feature-graph <slug>` is the same flow limited to one feature.
