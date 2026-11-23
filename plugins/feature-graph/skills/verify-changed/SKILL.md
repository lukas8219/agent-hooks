---
name: verify-changed
description: Plan and run verification for the current branch's changes using the cross-repo feature graph in Neo4j,
  which it only reads. Finds the affected features, the tests and manual checks, and other repos that consume or
  provide the interfaces you touched. Then runs this repo's tests. Use before opening a PR or when asked what a
  change affects.
argument-hint: '[base-ref] [--plan-only]'
metadata:
  aip:
    spec: https://github.com/zach-blumenfeld/aip/tree/v0.3a3
    schemaId: https://raw.githubusercontent.com/zach-blumenfeld/aip/v0.3a3/assets/aip-schemas/procedure.schema.json
---

```yaml
purpose: >-
  Turn the current repository's committed, staged, unstaged, and untracked changes
  into a verification plan using the shared feature graph, then run the selected
  local tests. Include affected features, manual checks, and cross-repo effects.
trigger_when:
  - The user invokes verify-changed, asks what a change affects, or requests verification before a PR.
do_not_use_when:
  - The user wants to build or update the graph; use the bundled feature-graph skill.
scope_and_approval: >-
  Never write to Neo4j. Use the local scripts/graph.py read-only adapter, which rejects
  init, upsert, and write. Reads use transactions that are always rolled back and
  reject database updates. Run tests only in the current repository and only when
  --plan-only was not requested. List other repositories' commands for the user.
  Do not install dependencies or start missing services unless separately requested.
steps:
  - name: collect-changes
    description: Run python3 -I scripts/changed_files.py with optional --base-ref <base-ref>, saving stdout to a scratchpad changes.json; stop with a no-changes report when files is empty.
    script: scripts/changed_files.py
    inputs:
      - name: repository-directory
        type: string
        description: 'External: working directory of the repository to verify.'
      - name: base-ref
        type: string
        nullable: true
        description: 'External: user-supplied base reference; omitted uses the merge base with origin/default_branch.'
    outputs:
      - name: changes
        type: object
        description: Repository identity, base_ref/base_sha/merge_base, files, and deleted_files.
      - {name: changes-path, type: string, description: Scratchpad path containing the changes JSON.}
  - name: query-impact
    description: Run python3 -I scripts/graph.py impact --changes-json <changes-path>; on connection or credential failure retain the error and use a null graph-impact for fallback planning.
    script: scripts/graph.py
    depends_on: [collect-changes]
    inputs:
      - {name: changes-path, type: string}
    outputs:
      - name: graph-impact
        type: object
        nullable: true
        description: Mapping SHA, features, dependents, interfaces/counterparts, checks, requires, and unmapped files; null on failure.
      - {name: graph-error, type: string, nullable: true, description: 'Client failure details, with credential values omitted.'}
  - name: plan-verification
    description: >-
      Read references/verification.md for the plan format and interface compatibility
      decisions. With a mapped graph, inspect features and dependents through their
      via paths, direct/indirect interfaces and other repositories' counterparts,
      checks, outgoing/incoming requires, and unmapped_files. Verify mapped_sha is an
      ancestor of HEAD before reporting git rev-list --count <mapped_sha>..HEAD;
      missing or unrelated SHAs mean stale or different history, not a fresh map.
      Inspect git diff <changes.merge_base> -- <file> for changes to routes, params,
      response fields, message payloads, or table columns. If graph-impact is null
      or mapped=false, explain why, use specs mirroring changed files and diff evidence
      for routes, HTTP clients, publishers, and service URL names; label this plan
      not graph-backed and recommend feature-graph. In either case, print the plan
      in chat and include local tests/manual checks, cross-repo actions, and gaps.
      Preserve deleted paths in impact analysis but exclude them from runnable tests.
    depends_on: [query-impact]
    inputs:
      - {name: changes, type: object}
      - {name: graph-impact, type: object, nullable: true}
      - {name: graph-error, type: string, nullable: true}
    outputs:
      - name: verification-plan
        type: object
        description: Local tests, manual checks, remote commands with reasons, affected features, and confidence gaps.
  - name: run-local-tests
    description: >-
      If plan-only=true, execute nothing and record the skipped result. Otherwise,
      select test checks belonging to changes.repo.name. Merge commands with the
      same runner using the union of spec paths, add changed test files, and remove
      nonexistent paths. Run the local commands and capture actual results; never
      execute counterpart repositories' checks. If a runner, dependency, or service
      is missing, report the exact error and runnable command without setting it up.
      Test selection remains a judgment step because runner semantics vary by repo.
    depends_on: [plan-verification]
    inputs:
      - {name: changes, type: object}
      - {name: verification-plan, type: object}
      - name: plan-only
        type: boolean
        description: 'External: true when --plan-only was supplied; otherwise false.'
    outputs:
      - name: test-results
        type: object
        description: Per-command pass/fail, failing examples, or explicit skip/missing-environment results.
  - name: report-verification
    description: >-
      Report observed results per command with failures, skipped work, manual checks,
      and cross-repo commands for the user. Distinguish planned checks from tests
      actually run. Recommend feature-graph refresh only when staleness or coverage
      gaps matter; never refresh the graph as part of verification.
    depends_on: [run-local-tests]
    inputs:
      - {name: verification-plan, type: object}
      - {name: test-results, type: object}
    outputs:
      - {name: verification-report, type: string}
modes:
  - name: default
    body: Plan with the graph when available and run selected local tests; use a clearly labeled diff-only plan when graph access fails.
  - name: plan-only
    body: Pass --plan-only in the skill invocation to produce a plan without running tests; graph access remains read-only.
integrations:
  - partner: Git
    body: >-
      changed_files.py resolves the base to a commit, collects the union of branch,
      working-tree, index, and untracked changes with NUL-delimited paths, and retains
      deleted/renamed paths for impact. If the default remote ref is missing, fetch
      origin <default_branch> then retry; do not silently substitute another base.
  - partner: Neo4j Query API
    body: >-
      Set NEO4J_URI with NEO4J_READ_USERNAME/NEO4J_READ_PASSWORD (preferred) or
      NEO4J_USERNAME/NEO4J_PASSWORD. NEO4J_DATABASE is optional. The read-only adapter
      supports ping, status, impact, read, whoami, and uri through the shared client
      at ../feature-graph/scripts/graph.py, inside the same plugin. For additional
      graph inspection use python3 -I scripts/graph.py status or read; handle failures
      with the same diff-only fallback.
  - partner: feature-graph
    body: This sibling skill authors the graph. Recommend its mapping or refresh command when needed; do not invoke its write commands during verification.
anti_patterns:
  - Writing to the graph, including creating constraints, during verification.
  - Running tests under --plan-only, in counterpart repos, or claiming unrun tests passed.
  - Dropping deleted paths before impact analysis or treating missing/unrelated mapped_sha as current.
```
