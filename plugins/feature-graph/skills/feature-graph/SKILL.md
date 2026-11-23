---
name: feature-graph
description: Build or refresh this repository's part of the cross-repo feature knowledge graph in Neo4j. It maps
  features to files, interfaces (HTTP, AMQP, DB tables, gems) and checks, and links repos through the interfaces
  they share. Run once per repo. /verify-changed reads the result.
disable-model-invocation: true
argument-hint: '[refresh | <feature-slug>]'
metadata:
  aip:
    spec: https://github.com/zach-blumenfeld/aip/tree/v0.3a3
    schemaId: https://raw.githubusercontent.com/zach-blumenfeld/aip/v0.3a3/assets/aip-schemas/procedure.schema.json
---

```yaml
purpose: >-
  Build or refresh this repository's features, files, checks, interfaces, and
  repository dependencies in a shared Neo4j graph. Shared Interface nodes connect
  providers and consumers across repositories; each repository owns its subgraph.
trigger_when:
  - The user invokes feature-graph to map a repository, refresh its map, or remap one feature.
do_not_use_when:
  - The user only wants to verify a diff; use the bundled verify-changed skill.
scope_and_approval: >-
  Use static analysis only; do not boot or drive the app or modify repository source.
  Write artifacts only to the scratchpad, and graph data only through graph.py init
  and upsert. Obtain confirmation of the concrete feature list, interfaces, repository
  dependencies, and removals before either graph-writing step. Existing explicit
  approval covering that exact plan suffices. If approval is declined or pending,
  stop before initializing or writing. Never persist secrets, environment values,
  tokens, or hostnames from .env in the graph; environment variable names are allowed.
steps:
  - name: identify-repository
    description: Run python3 -I scripts/graph.py whoami from the target repository.
    script: scripts/graph.py
    inputs:
      - name: repository-directory
        type: string
        description: 'External: working directory of the repository to map.'
    outputs:
      - name: repository
        type: object
        description: Repository owner/name, URL, root, HEAD SHA, branch, and default branch.
  - name: inspect-graph
    description: Run python3 -I scripts/graph.py status --repo <repository.name>; report connection or credential errors and stop on failure.
    script: scripts/graph.py
    depends_on: [identify-repository]
    inputs:
      - {name: repository, type: object}
    outputs:
      - name: graph-status
        type: object
        description: Mapping status, mapped_sha, feature paths, linked and dangling interfaces, and requires edges.
  - name: select-scope
    description: >-
      With no argument and mapped=true, report feature count, mapped_sha versus HEAD,
      commits behind, and linked/dangling interfaces, propose refresh, then stop this
      invocation without continuing. With no existing map, select a full build.
      For refresh, check git merge-base --is-ancestor <mapped_sha> HEAD; missing or
      non-ancestor mapped_sha requires a full build. Otherwise inspect git diff
      --name-status <mapped_sha>..HEAD: remap features whose graph-status paths changed
      plus new entry points, and retain deleted paths for removal. A feature slug
      limits a partial remap to that feature. Record the mode and affected paths in
      mapping-scope; preserve stable slugs.
    depends_on: [inspect-graph]
    one_of: [report-status-and-stop, full-build, partial-refresh, single-feature]
    inputs:
      - {name: repository, type: object}
      - {name: graph-status, type: object}
      - name: requested-mode
        type: string
        nullable: true
        description: 'External: omitted, refresh, or a feature slug from the user invocation.'
    outputs:
      - name: mapping-scope
        type: object
        description: Full or partial mode, selected features, changed paths, and proposed removals for a continuing invocation.
  - name: discover-map
    description: >-
      Read references/discovery.md for entry points, file roles, co-change evidence,
      feature granularity, and test command discovery. Read references/schema.md for
      payload fields and exact interface key normalization. Group entry points into
      features a user would name. Follow entry/core/view/config/migration/test files,
      add confidence to inferred links, and record test commands and one or two manual
      paths per feature. Map local feature dependencies. Infer exposed and consumed
      interfaces with evidence for uncertain keys, and repository requires edges from
      consumed services, compose files, .env.example, and README. For partial mode,
      re-extract interfaces only for changed files; list every file whose interface
      links are being replaced. Propose removed_files and removed_features explicitly.
      For a large repository, discovery may be split by area across available Explore
      subagents, returning the same payload shape. Keep stack-specific reasoning here.
    depends_on: [select-scope]
    inputs:
      - {name: repository, type: object}
      - {name: graph-status, type: object}
      - {name: mapping-scope, type: object}
    outputs:
      - name: draft-map
        type: object
        description: Features, files, checks, interfaces, dependencies, evidence, confidence, and proposed removals.
  - name: prepare-payload
    description: >-
      Build the JSON payload in references/schema.md with repo.sha equal to the
      inspected HEAD and the selected full/partial mode. Save it as
      feature-graph-<repo>.json in the scratchpad, never in repository source. In
      partial mode omit requires unless changing them; including it replaces those
      edges. An empty requires list clears them. Keep inferred dependencies marked
      inferred and user-declared dependencies marked declared. Retain the path for
      validation and user review.
    depends_on: [discover-map]
    inputs:
      - {name: repository, type: object}
      - {name: mapping-scope, type: object}
      - {name: draft-map, type: object}
    outputs:
      - {name: payload-path, type: string, description: Scratchpad JSON payload path.}
  - name: validate-payload
    description: Run python3 -I scripts/graph.py validate --json <payload-path>; fix reported payload errors before continuing.
    script: scripts/graph.py
    depends_on: [prepare-payload]
    inputs:
      - {name: payload-path, type: string}
    outputs:
      - {name: validation, type: object, description: The client returns ok=true on successful offline validation.}
  - name: confirm-mapping
    description: >-
      Show feature slug/name/kind and file/check counts, exposed/consumed interfaces
      by kind with consumed HTTP/AMQP keys in full, inferred requires with reasons,
      and all proposed removals. Obtain confirmation, including repositories always
      needed for full testing. Apply renames, merges, and declared dependencies to
      the draft and repeat prepare-payload and validate-payload before requesting
      approval of a changed plan. Continue only with validation.ok=true and approval
      covering the final payload. If repository HEAD changes, rebuild and revalidate
      the payload before proceeding. Preserve the approved payload unchanged.
    depends_on: [validate-payload]
    inputs:
      - {name: repository, type: object}
      - {name: mapping-scope, type: object}
      - {name: draft-map, type: object}
      - {name: payload-path, type: string}
      - {name: validation, type: object}
    outputs:
      - {name: approval, type: boolean, description: True only after the user approves the final concrete mapping.}
      - {name: approved-payload-path, type: string}
  - name: initialize-graph
    description: With approval=true, run python3 -I scripts/graph.py init to create constraints and indexes.
    script: scripts/graph.py
    depends_on: [confirm-mapping]
    inputs:
      - {name: approval, type: boolean}
    outputs:
      - {name: initialization, type: object, description: The client returns ok=true and the number of constraints.}
  - name: write-graph
    description: With approval=true and initialization.ok=true, run python3 -I scripts/graph.py upsert --json <approved-payload-path>.
    script: scripts/graph.py
    depends_on: [initialize-graph]
    inputs:
      - {name: approval, type: boolean}
      - {name: initialization, type: object}
      - {name: approved-payload-path, type: string}
    outputs:
      - {name: written-status, type: object, description: Status returned after the transactional upsert.}
  - name: report-result
    description: >-
      Briefly report the database base URL without credentials, repository and SHA,
      counts of features/files/interfaces/checks, cross-repo linked interfaces, and
      dangling consumes grouped by likely provider. Include uncovered directories
      and intentionally omitted shared utilities. For a partial update describe
      added/remapped/removed features and links gained or lost. Recommend one next
      step, such as mapping a provider repository or running verify-changed.
    depends_on: [write-graph]
    inputs:
      - {name: repository, type: object}
      - {name: graph-status, type: object}
      - {name: mapping-scope, type: object}
      - {name: approved-payload-path, type: string}
      - {name: written-status, type: object}
    outputs:
      - {name: mapping-report, type: string}
modes:
  - name: full
    body: With no existing map, replace this repository's owned subgraph; do not touch other repositories' features, files, or checks.
  - name: refresh
    body: Update since Repo.mapped_sha, falling back to full discovery for unrelated history; confirm removed features before writing.
  - name: single-feature
    body: Limit partial discovery and replacement to the requested feature slug.
integrations:
  - partner: Neo4j Query API
    body: >-
      Require NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD; NEO4J_DATABASE is optional
      and defaults to neo4j. Name missing required variables and stop. Read operations
      may use NEO4J_READ_USERNAME and NEO4J_READ_PASSWORD. The existing graph.py client
      handles URI conversion, validation, transactions, and repository ownership.
  - partner: verify-changed
    body: The sibling skill reads this graph to plan verification; both skills ship in the feature-graph plugin.
anti_patterns:
  - Initializing indexes or upserting before the confirmation step succeeds.
  - Using graph.py write for mapping, or treating a partial payload's requires field as additive.
  - Running the application during static discovery or storing secret values in the graph.
```
